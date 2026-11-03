"""Explicit post-generation grades; strict checks remain the authority on facts."""
import copy
import re
from jsonschema import Draft202012Validator
from .rag.core import GroundingError,fingerprint
from .rag.quality_contract import QualityContract,SCHEMA
from .rag.comparison_validation import check_comparison_directions


class AnswerRejected(GroundingError):
    def __init__(self,message,code='validation_rejected'):
        super().__init__(message);self.code=code


class AssessmentContract:
    """Recover only named metadata/coverage issues, never arbitrary exceptions."""
    def __init__(self,strict):
        self.strict=strict;self.mode='qa';self.wire_schema=None

    def request(self,*args,**kwargs):
        request=self.strict.request(*args,**kwargs)
        self.mode=self.strict.mode
        self.wire_schema=copy.deepcopy(request['text']['format']['schema'])
        return request

    def _evaluate(self,raw,registry):
        if not isinstance(raw,dict):raise AnswerRejected('Model answer is not a structured object','invalid_schema')
        candidate=copy.deepcopy(raw);warnings=[];coverage_uncertain=False
        def warn(code,message,path='',ids=()):
            warnings.append({'code':code,'message':message,'path':path,'source_ids':list(dict.fromkeys(ids)),'severity':'review'})
        categories=SCHEMA['properties']['sections']['items']['properties']['category']['enum']
        for i,section in enumerate(candidate.get('sections',[]) if isinstance(candidate.get('sections'),list) else []):
            if isinstance(section,dict) and isinstance(section.get('category'),str) and section['category'] not in categories:
                warn('category_label','段落分類標籤無法辨識；保留回答文字，分類與完整性待核對。',f'sections/{i}/category')
                section['category']='comparison';coverage_uncertain=True
        schema=self.wire_schema or SCHEMA
        errors=list(Draft202012Validator(schema).iter_errors(candidate))
        if errors:raise AnswerRejected('Invalid answer/source-selection schema: '+errors[0].message,'invalid_schema')
        resolved=copy.deepcopy(candidate)
        def resolve(item):
            key=item.get('source_id',item.get('evidence_id'))
            if key not in registry:raise AnswerRejected('Unknown source ID '+str(key),'unknown_source')
            if 'source_id' in item:
                if key not in self.strict.allowed_sources:raise AnswerRejected('Ineligible source selection '+key,'unknown_source')
                quote=registry[key]['text']
            else:quote=item['quote']
            if len(quote.strip())<20 or quote not in registry[key]['text']:
                raise AnswerRejected('Support must be a substantial exact original quote: '+key,'nonexistent_quote')
            return {'evidence_id':key,'quote':quote}
        for section in resolved['sections']:
            for statement in section['statements']:
                statement['support']=[resolve(item) for item in statement['support']]
                # Unsupported free-form numbers must not be hidden by a review fallback.
                if re.search(r'\d',statement['text']):
                    raise AnswerRejected('Numerical prose requires original structured/quoted evidence','unvalidated_number')
        for view in resolved['table_views']:
            if view['evidence_id'] not in registry:raise AnswerRejected('Unknown table source '+view['evidence_id'],'unknown_source')
        resolved['numeric_observations']=[resolve(item) for item in resolved['numeric_observations']]
        try:check_comparison_directions(resolved['sections'],registry)
        except GroundingError as error:raise AnswerRejected(str(error),'comparison_contradiction') from None
        display=copy.deepcopy(resolved);projection=copy.deepcopy(resolved)
        kept=[]
        for i,observation in enumerate(projection['numeric_observations']):
            key=observation['evidence_id']
            if registry[key].get('facts'):
                raise AnswerRejected('Table values require structured table_views, not a quote bypass','invalid_numeric_evidence')
            metadata={'Section: '+' / '.join(registry[key].get('section_path',[]))}
            body='\n'.join(line for line in observation['quote'].splitlines() if line not in metadata and not re.fullmatch(r'\[(?:C|S)\d+ \| PDF pages .+\]',line))
            if not re.search(r'\d',body):
                warn('non_numeric_observation','數值觀察選中了沒有數字的定性原文；未作為數值證據，請核對來源。',f'numeric_observations/{i}',[key])
            else:kept.append(observation)
        projection['numeric_observations']=kept
        for i,section in enumerate(projection['sections']):
            retained=[]
            for j,statement in enumerate(section['statements']):
                if statement['support']:retained.append(statement)
                else:
                    warn('missing_support','此陳述沒有可確認的引用，僅顯示為待核對文字。',f'sections/{i}/statements/{j}')
                    coverage_uncertain=True
            section['statements']=retained
        if self.mode=='final_summary':
            actual={s['category'] for s in projection['sections'] if s['statements']}
            if not {'background','method','experiments','conclusion'}.issubset(actual):
                warn('summary_coverage','主要摘要的必要類別未完整覆蓋；不能宣稱全文摘要已通過完整性驗收。')
                coverage_uncertain=True
        if not warnings:
            try:
                answer,_=self.strict.normalize(raw,registry)
                checks=self.strict.validate(answer,registry)
            except GroundingError as error:raise AnswerRejected(str(error)) from None
        else:
            validation_registry=registry
            projection_mode=self.mode
            if coverage_uncertain:
                # Only coverage/labels are deferred. Names, exact quotes, tuples,
                # group closure and numerical direction still undergo strict checks.
                validation_registry=copy.deepcopy(registry)
                for source in validation_registry.values():source.pop('required_methods',None)
                projection_mode='qa'
                projection['evidence_status']='insufficient'
                if self.mode=='final_summary':
                    for key,source in registry.items():
                        metric=next((f['metric'] for f in source.get('facts',[]) if f['metric'].lower()=='overall'),None)
                        if metric:
                            view={'evidence_id':key,'metric':metric,'datasets':[],'comparison_groups':[]}
                            if view not in projection['table_views']:projection['table_views'].append(view)
            strict=QualityContract();strict.mode=projection_mode
            try:
                answer,_=strict.normalize(projection,validation_registry)
                checks=strict.validate(answer,validation_registry)
            except GroundingError as error:raise AnswerRejected(str(error)) from None
            checks['checks_scope']='validated_projection_only; original answer requires review'
            if coverage_uncertain:
                checks['schema']='review_required'
                checks['required_method_coverage']='not_certified'
                checks['summary_coverage']='not_certified'
        status='review_required' if warnings else 'passed'
        answer['assessment']={'status':status,'warnings':warnings,'original_payload':copy.deepcopy(raw),
            'display_payload':display,'original_mode':self.mode,'coverage_uncertain':coverage_uncertain}
        checks.update(status=status,warnings=warnings)
        return answer,checks

    def restore_request(self,request):
        import json
        data=json.loads(request['input'][0]['content'][0]['text'])
        self.mode=self.strict.mode=data['task']
        self.wire_schema=copy.deepcopy(request['text']['format']['schema'])
        self.strict.selection_schema=copy.deepcopy(self.wire_schema)
        support=self.wire_schema['properties']['sections']['items']['properties']['statements']['items']['properties']['support']['items']
        self.strict.allowed_sources=set(support['properties'].get('source_id',{}).get('enum',[]))

    def recover(self,text,registry,error):
        from .failed_answer import failed_answer
        answer=failed_answer(text,error)
        return answer,self.validate(answer,registry)

    def normalize(self,raw,registry):
        answer,_=self._evaluate(raw,registry)
        return answer,[]  # No numerical or citation repairs.

    def validate(self,answer,registry):
        if 'failed_validation' in answer:
            import json
            from .failed_answer import failed_answer
            text=answer['failed_validation']['output_text']
            try:self._evaluate(json.loads(text),registry)
            except (GroundingError,json.JSONDecodeError) as error:
                rebuilt=failed_answer(text,error)
                if fingerprint(answer)!=fingerprint(rebuilt):raise AnswerRejected('Failed answer changed since validation')
                return {'status':'failed','warnings':[rebuilt['failed_validation']['warning']], 'checks_scope':'not_certified'}
            raise AnswerRejected('Failed validation record no longer matches the validator')
        metadata=answer.get('assessment')
        if metadata is None:
            checks=self.strict.validate(answer,registry)
            return {**checks,'status':'passed','warnings':[]}
        rebuilt,checks=self._evaluate(metadata['original_payload'],registry)
        if fingerprint(answer)!=fingerprint(rebuilt):raise AnswerRejected('Assessed answer changed since validation','answer_tampered')
        return checks

"""Per-stage diagnostics from request-local memory or existing offline archives."""
import json
from pathlib import Path
from .rag.core import fingerprint,count_payload,CONTEXT_LIMIT


def inspect_summary(run,artifacts=None,timestamps=None):
    run=Path(run);stages=[]
    if artifacts is None:
        def read(path):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        exists=lambda path:path.exists()
        folders=sorted(path for path in (run/'summary').iterdir() if path.is_dir())
        round_paths=sorted((run/'summary').glob('*-rounds.json'))
        files=[p for p in run.rglob('*') if p.is_file()]
        span=max(p.stat().st_mtime for p in files)-min(p.stat().st_mtime for p in files) if files else None
    else:
        # Values live only on this Generator instance, which is not retained by
        # the service after the HTTP request. Never probe old request folders.
        def key(path):return Path(path).relative_to(run).as_posix()
        def read(path):return artifacts.get(key(path),{})
        exists=lambda path:key(path) in artifacts
        folders=[run/'summary'/name for name in sorted({p.split('/')[1] for p in artifacts if p.startswith('summary/') and len(p.split('/'))>2})]
        round_paths=[run/p for p in sorted(artifacts) if p.startswith('summary/') and p.endswith('-rounds.json') and len(p.split('/'))==2]
        times=list((timestamps or {}).values());span=max(times)-min(times) if times else None
    for folder in folders:
        local=read(folder/'local-table-ledger.json')
        if local:
            stages.append({'stage':folder.name,'status':'local_table_ledger','fallback':False,
                'reasons':[local['reason']],'source_count':len(local['source_ids']),
                'official_input_tokens':None,'output_reserve':None,'safety':None,'budget_total':None,
                'within_10k':None,'generation_seconds':0,'count_seconds':0})
            continue
        request=read(folder/'request.json')
        if not request:continue
        count=read(folder/'input-count.json');result=read(folder/'result.json');metrics=read(folder/'transport-metrics.json')
        raw=read(folder/'raw-response.json');note=read(folder/'note.json');error=read(folder/'error.json')
        checks=result.get('validation',{})
        reasons=[w['message'] for w in checks.get('warnings',[])]
        fallback=bool(note.get('extractive_fallback') or exists(folder/'extractive-fallback.json') or result.get('answer',{}).get('failed_validation'))
        if error:reasons.append(error.get('error','').strip().splitlines()[-1])
        official=count.get('official_input_tokens');reserve=count.get('output_reserve');safety=count.get('safety')
        total=official+reserve+safety if all(isinstance(x,int) for x in (official,reserve,safety)) else None
        from .rag.core import canonical
        from .summary_notes import bounded_note
        data=json.loads(request['input'][0]['content'][0]['text']) if 'input' in request else None
        retained={k:note[k] for k in ('section','supported_sections','numeric_observations') if k in note}
        retained['source_type']='generated_note'
        stages.append({'request_note_bytes':len(canonical(data['evidence']).encode('utf8')) if data is not None else request.get('request_evidence_bytes'),
            'retained_note_bytes':len(canonical(retained).encode('utf8')) if note else None,
            'bounded_retained_note_bytes':len(canonical(bounded_note(note)).encode('utf8')) if note else None,
            'retained_note_tokens':None,'retained_token_scope':'Not separately recorded; no new token-count API call performed.',
            'stage':folder.name,'status':checks.get('status',raw.get('status','unknown')),
            'fallback':fallback,'reasons':reasons,'source_count':len(read(folder/'sources.json')),
            'official_input_tokens':official,'output_reserve':reserve,'safety':safety,'budget_total':total,
            'within_10k':total is not None and total<=CONTEXT_LIMIT and count.get('request_sha256')==(fingerprint(count_payload(request)) if 'input' in request else request.get('input_count_payload_sha256')) and reserve==request['max_output_tokens'],
            'generation_seconds':metrics.get('generation_latency_seconds',result.get('generation_latency_seconds')),
            'count_seconds':metrics.get('count_latency_seconds',result.get('count_latency_seconds')),
            'usage':raw.get('usage',result.get('usage',{})),
            'coverage_carried_categories':note.get('coverage_carried_categories',[])})
    ledger=read(run/'ledger.json')
    rounds=[entry for path in round_paths for entry in read(path)]
    return {'reduction_rounds':rounds,'partial_summary':read(run/'summary/partial-summary.json'),'segment_count':sum(s['stage'].startswith('map-') for s in stages),
        'stages':stages,'recorded_generation_seconds':sum(s.get('generation_seconds') or 0 for s in stages),
        'recorded_count_seconds':sum(s.get('count_seconds') or 0 for s in stages),
        'observed_file_span_seconds':span,
        'generation_requests':ledger.get('generation_requests'), 'input_count_requests':ledger.get('input_count_requests'),
        'timing_scope':'Artifact span is approximate (request-local memory for the website, files for archives); planning, validation and HTTP overhead are not fully timed.'}

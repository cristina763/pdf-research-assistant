"""Conservative, local intent routing; no model calls or document-specific rules."""
import re
import unicodedata

# Match the entire request. A topic, section qualifier, negation or additional
# instruction prevents an automatic whole-document summary.
_ENGLISH_SUMMARY = re.compile(
    r'(?:(?:please|kindly)\s+)?'
    r'(?:(?:can|could|would|will)\s+you\s+)?'
    r'(?:please\s+)?'
    r'(?:summari[sz]e\s+|summary\s+(?:of\s+)?|'
    r'(?:give|provide|write|create|make)\s+(?:me\s+)?(?:a\s+)?summary\s+(?:of\s+)?)'
    r'(?:(?:this|that|the|my|our)\s+)?'
    r'(?:(?:uploaded|attached|provided)\s+)?'
    r'(?:(?:whole|entire|full|complete)\s+)?'
    r'(?:document|pdf|paper|article|report|thesis)'
    r'(?:\s+(?:as\s+a\s+whole|in\s+its\s+entirety))?'
    r'(?:\s+please)?[.!?。！？]*'
)
_ZH_OBJECT = (
    r'(?:(?:(?:這|这|該|该|此)(?:份|篇|個|个)?(?:完整的|整份|整篇)?|'
    r'整(?:份|篇|個|个)?|全(?:篇|部)?)'
    r'(?:文件|文檔|文档|論文|论文|文章|報告|报告|pdf)|全文|本文)'
)
_ZH_PREFIX = r'(?:(?:請|请|麻煩|麻烦|可以|能否|幫我|帮我|替我|你|您)\s*)*'
_CHINESE_SUMMARY = re.compile(
    _ZH_PREFIX + r'(?:總結|总结|摘要|概述)(?:一下)?\s*' + _ZH_OBJECT + r'[。！？!?]*'
)
_CHINESE_SUMMARY_NOUN = re.compile(
    _ZH_PREFIX + r'(?:提供|給我|给我|產生|生成|做)?\s*' + _ZH_OBJECT
    + r'的?(?:全文|整篇)?(?:摘要|總結|总结)[。！？!?]*'
)


def resolve_task(question, task='auto'):
    """Explicit tasks win; only unambiguous full-document requests use summary."""
    if task in ('qa','summary'):
        return task
    if task!='auto':
        raise ValueError('task must be auto, qa or summary')
    normalized=' '.join(unicodedata.normalize('NFKC',question).casefold().split())
    if any(pattern.fullmatch(normalized) for pattern in
           (_ENGLISH_SUMMARY,_CHINESE_SUMMARY,_CHINESE_SUMMARY_NOUN)):
        return 'summary'
    return 'qa'

"""Bind Canary tracking permission to the original cached MIME, never its slug."""
from __future__ import annotations
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from functools import lru_cache

from v11_gmail import canonical_url, link_evidence


def is_canary_tracking(url):
    return (urlsplit(url).hostname or '').lower() == 'hello.canarymedia.com'


@lru_cache(maxsize=32)
def _cached_links(path, modified_ns, size):
    return link_evidence(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def candidate_link_evidence(root, candidate):
    """None means unrelated; unknown means do not open the ambiguous tracker."""
    if not is_canary_tracking(candidate.get('url','')):return None
    unknown={'allowed':None,'label':'','context':'','reason':'matching_full_mime_link_evidence_missing'}
    message_id=candidate.get('newsletter_message_id')
    if not isinstance(message_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',message_id):return unknown
    cache_root=(Path(root)/'work/gmail-body-cache').resolve()
    path=(cache_root/(message_id+'.json')).resolve()
    if not path.is_relative_to(cache_root):return unknown
    try:
        stat=path.stat()
        links=_cached_links(str(path),stat.st_mtime_ns,stat.st_size)
        result=links.get(canonical_url(candidate['url']))
        if not result or result.get('message_id')!=message_id:return unknown
        return {**result,'cache_file':str(path)}
    except (OSError,ValueError,TypeError,KeyError):return unknown


def local_link_decision(index, evidence):
    """Only unambiguous utility links are excluded. Unknown links remain pending."""
    if evidence is None or evidence.get('allowed') is True:return None
    blocked=evidence.get('allowed') is False
    reason=('원본 뉴스레터 MIME에서 계정·구독·공유·탐색용 링크로 확인되어 기사 대상 제외. 추적 링크 접속 미수행: '
            if blocked else '원본 뉴스레터에서 기사 전용 링크임을 확인할 수 없어 접속 보류. 구독·계정 링크 오접속 방지를 위한 메타데이터 확인 필요: ')+evidence.get('reason','unresolved')
    return {'index':index,'action':'reviewed' if blocked else 'defer','urgency':'none',
            'urgency_reason':'뉴스레터 링크 유형의 로컬 확인이며 산업 뉴스 발송 판단 아님',
            'sector':'market','reason':reason,'verified':blocked,
            'review_basis':'metadata' if blocked else 'unavailable',
            'review_category':'non_article' if blocked else 'access_gap',
            'source_urls':[],'source_published_at':None,'confidence':1.0 if blocked else 0.0,
            'industrial_signal':None,'message_text':None,'duplicate_of':None,
            'novelty':{'new_facts':[],'comparisons':[]}}

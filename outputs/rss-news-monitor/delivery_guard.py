"""Read-only cross-run news preflight. Similarity requests review, never deletes news.

Receipt-backed texts are delivery evidence; old outbox texts are explicitly NOT.
No date/count cutoff: ACK gaps and pre-receipt history must remain visible.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[2]

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def canonical(url):
    p = urlsplit(url.rstrip('.,)'))
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'),
                      urlencode(sorted((k,v) for k,v in parse_qsl(p.query)
                                 if not k.lower().startswith('utm_') and k.lower() not in {
                                     'ref','source','output','gclid','fbclid','mc_cid','mc_eid'})), ''))

def links(text):
    return {canonical(u) for u in re.findall(r'https?://[^\s<>]+', text)}

def story_keys(urls):
    """Recognize syndicated article slugs across different publisher domains."""
    keys=set()
    for url in urls:
        slug=urlsplit(url).path.rstrip('/').rsplit('/',1)[-1].lower()
        slug=re.sub(r'\.(?:html?|aspx)$','',slug)
        if len(slug)>=32 and slug.count('-')>=5 and re.fullmatch(r'[a-z0-9-]+',slug):
            keys.add(slug)
    return keys

def quantities(text):
    """Small, source-neutral industrial figures for near-threshold review."""
    body=unicodedata.normalize('NFKC',re.sub(r'https?://\S+','',text)).lower()
    # Longest units first: 2GWh storage energy must not become 2GW power.
    pattern=r'(?<!\d)(\d+(?:[,.]\d+)*)\s*(gwh(?![a-z])|mwh(?![a-z])|gw(?![a-z])|mw(?![a-z])|kv(?![a-z])|억|만|조|개|건|주|마일|달러|%)'
    return {number.replace(',','')+unit for number,unit in re.findall(pattern,body,re.I)}

def headline(text):
    return next((line.strip() for line in text.splitlines() if line.strip()),'')

@lru_cache(maxsize=4096)
def normalized(text):
    text = re.sub(r'https?://\S+', '', text)
    return re.sub(r'[^a-z0-9가-힣]', '', unicodedata.normalize('NFKC', text).lower())

@lru_cache(maxsize=4096)
def grams(text):
    n = normalized(text)
    # Cache by exact immutable text, not by a history snapshot. New receipts
    # still enter every preflight; repeated full-history matching avoids
    # rebuilding the same Korean/English shingles hundreds of times per send.
    return frozenset(n[i:i+3] for i in range(max(0, len(n)-2)))

def similarity(a, b):
    x, y = grams(a), grams(b)
    return len(x & y) / max(1, min(len(x), len(y)))

def history(root, current_receipt=None):
    """All verified DB/receipt texts plus review-only legacy drafts, merged by hash."""
    records = {}
    def add(text, urls, evidence, location):
        if not text or not text.strip():
            return
        key = digest(text.strip())
        row = records.setdefault(key, {'id':key, 'message_text':text.strip(), 'urls':set(),
                                      'evidence_type':evidence, 'locations':[]})
        row['urls'].update(canonical(u) for u in urls)
        row['urls'].update(links(text))
        row['locations'].append(str(location))
        if evidence == 'telegram_receipt':
            row['evidence_type'] = evidence
    db = root / 'work/rss-news-monitor.db'
    if not db.exists():
        raise ValueError('Delivery database missing; preflight cannot establish history')
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True,timeout=30)) as con:
        for url, text, sha, receipt in con.execute('SELECT url,message_text,message_sha256,receipt_file FROM delivery_history'):
            if digest(text) != sha:
                raise ValueError('Delivery history text/hash mismatch')
            add(text, [url], 'telegram_receipt', receipt)
    for path in sorted((root / 'work/runs').glob('*/receipt-*.json')):
        r = json.loads(path.read_text(encoding='utf-8-sig'))
        text = r.get('message_text', '')
        if current_receipt and path.resolve() == Path(current_receipt).resolve() and r.get('status') == 'partial' and r.get('in_flight_part') is None:
            # Sender itself verifies/resumes confirmed chunks under receipt lock.
            continue
        if r.get('status') == 'complete' and r.get('telegram_message_ids'):
            if digest(text) != r.get('message_sha256'):
                raise ValueError('Receipt text/hash mismatch: '+str(path))
            add(text, r.get('article_urls', []), 'telegram_receipt', path)
        elif r.get('status') == 'uncertain' or r.get('in_flight_part') is not None or r.get('completed_parts'):
            add(text, r.get('article_urls', []), 'uncertain_delivery', path)
    for path in sorted(p for p in (root / 'work/telegram-outbox').glob('*') if p.is_file() and p.suffix.lower() in {'.txt', '.md'}):
        text = path.read_text(encoding='utf-8-sig').strip()
        # URL-list files are not message bodies. Drafts are not delivery evidence.
        if links(text) and len(normalized(text)) >= 35:
            add(text, [], 'unverified_outbox', path)
    return records

def inspect(root, message, current_file=None, current_receipt=None):
    records = history(root, current_receipt)
    matches = []
    target = str(Path(current_file).resolve()) if current_file else None
    message_links=links(message)
    message_stories=story_keys(message_links)
    message_quantities=quantities(message)
    message_headline=headline(message)
    for row in records.values():
        # The current draft alone must not match itself; never hide old receipts.
        if target and row['evidence_type'] == 'unverified_outbox' and all(str(Path(p).resolve()) == target for p in row['locations']):
            continue
        score = similarity(message, row['message_text'])
        other_headline=headline(row['message_text'])
        title_score=similarity(message_headline,other_headline)
        shared = message_links & row['urls']
        shared_stories=message_stories & story_keys(row['urls'])
        shared_quantities=message_quantities & quantities(row['message_text'])
        exact = normalized(message) == normalized(row['message_text'])
        # A single distinctive project capacity can identify a syndication even
        # when the same story is paraphrased across languages and outlets.
        near_facts=.18<=score<.28 and bool(shared_quantities)
        near_headline=(.15<=score<.28 and title_score>=.52
                       and len(normalized(message_headline))>=22
                       and len(normalized(other_headline))>=22)
        if shared or shared_stories or score >= .28 or near_facts or near_headline or exact:
            matches.append({**row, 'urls':sorted(row['urls']), 'similarity':round(score,4),
                            'headline_similarity':round(title_score,4),
                            'shared_urls':sorted(shared),'shared_story_keys':sorted(shared_stories),
                            'shared_quantities':sorted(shared_quantities) if near_facts else [],
                            'same_content':exact})
    matches.sort(key=lambda r: (-bool(r['shared_urls']),-bool(r['shared_story_keys']),-r['similarity'],r['id']))
    return {'message_sha256':digest(message), 'history_count':len(records), 'matches':matches}

def validate(report, review):
    if review.get('message_sha256') != report['message_sha256']:
        raise ValueError('Novelty review is missing or bound to different message text')
    facts = review.get('new_facts', [])
    if not isinstance(facts, list) or not facts or any(not isinstance(f,str) or len(f.strip()) < 12 for f in facts):
        raise ValueError('Record concrete new industrial facts before sending')
    comparisons = review.get('comparisons', [])
    if not isinstance(comparisons, list) or any(not isinstance(row, dict) for row in comparisons):
        raise ValueError('Novelty comparisons must be an array of objects')
    by_id = {r['id']:r for r in comparisons}
    if len(by_id) != len(comparisons):
        raise ValueError('Duplicate comparison IDs')
    if set(by_id) != {match['id'] for match in report['matches']}:
        raise ValueError('Novelty comparisons must cover every current guard match exactly once')
    for match in report['matches']:
        if match['same_content'] and match['evidence_type'] in {'telegram_receipt','uncertain_delivery'}:
            raise ValueError('Same content already delivered or uncertain: '+match['id'])
        decision = by_id.get(match['id'], {})
        kind = decision.get('classification')
        allowed = {'followup', 'different_event'}
        if match['evidence_type'] == 'unverified_outbox':
            allowed.add('confirmed_unsent')
        if kind not in allowed or len(decision.get('reason','').strip()) < 20:
            raise ValueError('Compare prior body and document material delta; unresolved: '+match['id'])
        if (kind == 'different_event' and match.get('shared_story_keys')
                and match['evidence_type'] in {'telegram_receipt', 'uncertain_delivery'}):
            raise ValueError('Same syndicated article identity requires an evidenced follow-up delta')
        if kind == 'followup' and len(decision.get('material_delta','').strip()) < 20:
            raise ValueError('Follow-up requires explicit old fact -> new fact delta')
        if (kind == 'followup' and match.get('shared_story_keys')
                and len(decision.get('evidence','').strip()) < 20):
            raise ValueError('Same syndicated article follow-up requires evidence of a later material change')
        if kind == 'confirmed_unsent' and len(decision.get('evidence','').strip()) < 20:
            raise ValueError('Old outbox is ambiguous; provide actual evidence of non-delivery')
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--message-file', type=Path, required=True)
    parser.add_argument('--review-file', type=Path)
    parser.add_argument('--current-receipt', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    text = args.message_file.read_bytes().decode('utf-8-sig').strip()
    report = inspect(args.root, text, args.message_file, args.current_receipt)
    if args.review_file:
        validate(report, json.loads(args.review_file.read_text(encoding='utf-8-sig')))
        print(json.dumps({'valid':True,'compared_matches':len(report['matches']), 'history_count':report['history_count']}))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

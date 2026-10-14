"""Read-only migration audit: receipts, message bytes, database, and old paths."""
import datetime as dt
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from project_paths import ROOT, evidence_path
from review_state import validate_receipt, batch_candidates
from collector import canonical
from delivery_guard import inspect, validate


def main():
    errors = []
    database = ROOT / 'work/rss-news-monitor.db'
    counts = {}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as con:
        integrity = con.execute('PRAGMA integrity_check').fetchone()[0]
        for table in ('articles', 'delivery_history', 'decision_history', 'newsletter_messages', 'newsletter_message_articles'):
            counts[table] = con.execute('SELECT count(*) FROM ' + table).fetchone()[0]
        deliveries = con.execute('SELECT url,receipt_file,message_text,message_sha256 FROM delivery_history').fetchall()
    for url, receipt, message, digest in deliveries:
        try:
            result = validate_receipt(receipt, canonical(url), canonical, dt.datetime(2000,1,1,tzinfo=dt.timezone.utc))
            if result['message_text'] != message or result['message_sha256'] != digest:
                raise ValueError('DB and receipt text/hash differ')
        except Exception as error:
            errors.append({'receipt':str(evidence_path(receipt)), 'error':str(error)})
    snapshots = 0
    for path in (ROOT / 'work/runs').glob('*/snapshot.json'):
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        snapshots += 1
        if evidence_path(payload['run_files']['snapshot']) != path.resolve():
            errors.append({'snapshot':str(path), 'error':'Snapshot path mismatch'})
    candidate_page = json.loads((ROOT/'work/rss-news-candidates.json').read_text(encoding='utf-8-sig'))
    candidate_count = len(batch_candidates(candidate_page, ROOT/'work/rss-news-candidates.json'))
    blocked = False
    if deliveries:
        report = inspect(ROOT, deliveries[-1][2])
        try:
            validate(report, {'message_sha256':report['message_sha256'], 'new_facts':['This is a migration duplicate blocking check.'], 'comparisons':[]})
        except ValueError:
            blocked = True
    result = {'integrity':integrity, 'counts':counts, 'validated_delivery_rows':len(deliveries)-len(errors),
              'snapshot_paths_checked':snapshots, 'legacy_page_candidates':candidate_count,
              'already_sent_message_blocked':blocked, 'errors':errors}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if integrity == 'ok' and not errors and blocked else 1

if __name__ == '__main__':
    raise SystemExit(main())

"""Read-only Gmail ingestion evidence, including verified cached bodies.

This does not claim article review, editorial completion, or Telegram delivery.
"""
import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path
import gmail_scan

ROOT = Path(__file__).resolve().parents[2]


def _ids(scan, field, errors):
    value = scan.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append('invalid_' + field)
        return set()
    return set(value)


def check(scan, run_epoch, known_ids, now_epoch, root=None):
    errors = []
    started = scan.get('scan_started_epoch')
    if type(started) is not int or not run_epoch-3600 <= started <= now_epoch+60:
        errors.append('scan_not_current_run')
    if scan.get('pagination_complete') is not True:
        errors.append('search_pagination_incomplete')
    if scan.get('search_tool') not in gmail_scan.SEARCH_SOURCES:
        errors.append('actual_search_evidence_missing')
    if 'message_ids' not in scan:
        errors.append('invalid_message_ids')
    ids = _ids(scan, 'message_ids', errors)
    read = _ids(scan, 'read_message_ids', errors)
    new = _ids(scan, 'new_message_ids', errors)
    queued = _ids(scan, 'queued_message_ids', errors)
    cached = _ids(scan, 'cached_message_ids', errors)
    valid_cached = set()
    for message_id in cached:
        if root is not None and gmail_scan.cached_body_evidence(root, message_id) is not None:
            valid_cached.add(message_id)
        else:
            errors.append('cached_body_missing_or_changed:' + message_id)
    population = ids | queued
    if new - (read | valid_cached):
        errors.append('new_message_body_unread')
    if (new | read | cached) - population:
        errors.append('read_ids_not_in_search_or_queue')
    if root is not None:
        # Do not let omission from the scan file conceal earlier unimported mail.
        population |= set(gmail_scan._queue(root)['pending_messages'])
    missing = sorted(population - set(known_ids))
    if missing:
        errors.append('searched_messages_not_ingested')
    return {'gmail_ingestion_evidence_complete': not errors, 'errors': errors,
            'searched_messages': len(ids), 'queued_messages': len(queued),
            'new_messages': len(new), 'read_messages': len(read),
            'cached_body_messages': len(valid_cached), 'unimported_message_ids': missing,
            'editorial_completion': 'Run newsletter_completion.py separately; ingestion is not review or delivery.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan-file', type=Path, required=True)
    parser.add_argument('--run-start-epoch', type=int, required=True)
    args = parser.parse_args()
    scan = json.loads(args.scan_file.read_text(encoding='utf-8-sig'))
    with sqlite3.connect((ROOT/'work/rss-news-monitor.db').as_uri()+'?mode=ro', uri=True) as con:
        known = {row[0] for row in con.execute('SELECT message_id FROM newsletter_messages')}
    result = check(scan, args.run_start_epoch, known, int(dt.datetime.now(dt.timezone.utc).timestamp()), ROOT)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['gmail_ingestion_evidence_complete'] else 2)

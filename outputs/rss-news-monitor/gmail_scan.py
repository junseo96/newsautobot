"""Label-free Gmail checkpoints and a durable queue, independent of transport.

The search cursor may advance only after every result ID is durably queued.
The ingestion cursor and editorial/Telegram completion remain separate.
"""
import argparse
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from project_paths import evidence_path
import runtime_scope

ROOT = Path(__file__).resolve().parents[2]
OVERLAP_SECONDS = 6 * 3600
SEARCH_SOURCES = {'gmail_search_email_ids', 'gmail_api_messages_list'}


def processed_ids(root):
    db = (root / 'work/rss-news-monitor.db').resolve()
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True, timeout=30)) as con:
        return {row[0] for row in con.execute('SELECT message_id FROM newsletter_messages')}


def prompt_processed_ids(root, after_epoch):
    """Limit model exclusions to the search window; local dedup keeps all IDs.

    Import time is only a safe upper bound for legacy receive time: a message
    imported before this window cannot first arrive inside it. Rows lacking
    both valid timestamps stay in the prompt. Never use import time as article
    publication evidence or to advance the mailbox cursor.
    """
    db = (root / 'work/rss-news-monitor.db').resolve()
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=30)) as con:
        columns = {row[1] for row in con.execute('PRAGMA table_info(newsletter_messages)')}
        dates = [f'julianday({field})' for field in ('received_at', 'imported_at') if field in columns]
        if not dates:
            return {row[0] for row in con.execute('SELECT message_id FROM newsletter_messages')}
        boundary = 'COALESCE(' + ','.join(dates) + ')' if len(dates) > 1 else dates[0]
        return {row[0] for row in con.execute(f'''SELECT message_id FROM newsletter_messages
            WHERE {boundary} IS NULL OR {boundary}>=julianday(?, 'unixepoch')''',
            (int(after_epoch),))}


def _load(path, default):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def _save(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def _queue(root):
    value = _load(root / 'work/gmail-staging-state.json',
                  {'schema_version': 1, 'searched_through_epoch': 0, 'pending_messages': {}})
    if value.get('schema_version') != 1 or not isinstance(value.get('pending_messages'), dict):
        raise ValueError('Invalid Gmail staging state; preserve it and repair explicitly')
    return value


def _scan_ids(scan, now, require_tool=False, require_complete=True):
    started = scan.get('scan_started_epoch')
    ids = scan.get('message_ids')
    if type(started) is not int or started <= 0 or started > now:
        raise ValueError('Invalid scan start timestamp')
    if require_complete and scan.get('pagination_complete') is not True:
        raise ValueError('All Gmail result pages are required')
    if require_tool and scan.get('search_tool') not in SEARCH_SOURCES:
        raise ValueError('Actual Gmail plugin or Gmail API search evidence is required')
    if not isinstance(ids, list) or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError('All actual search result message IDs are required')
    return started, set(ids)


def _body_path(root, value):
    path = evidence_path(value, root=root)
    if not path.is_relative_to((root / 'work').resolve()):
        raise ValueError('Cached Gmail body must be inside the project work directory')
    return path


def cached_body_evidence(root, message_id, pending_messages=None):
    """Validate the immutable local evidence without returning the mail body."""
    entries = _queue(root)['pending_messages'] if pending_messages is None else pending_messages
    entry = entries.get(message_id, {})
    if not entry.get('body_file') or not entry.get('body_sha256'):
        return None
    try:
        path = _body_path(root, entry['body_file'])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None
    if digest != entry['body_sha256']:
        return None
    return {'message_id': message_id, 'body_file': str(path), 'body_sha256': digest}


def begin(root, now=None, compact=False):
    now = int(time.time() if now is None else now)
    state = _load(root / 'work/gmail-scan-state.json', {})
    queue = _queue(root)
    scope = runtime_scope.load(root)
    floor = int(scope.get('gmail_start_epoch', 0))
    last = max(int(state.get('completed_through_epoch', 0)), int(queue['searched_through_epoch']))
    # No three-day rolling window after a successful scan. Downtime is not capped.
    if last:
        after = max(floor, max(0, last - OVERLAP_SECONDS))
    else:
        after = floor if floor else max(0, now - 3*86400)
    known = processed_ids(root)
    pending = set(queue['pending_messages']) - known
    cached = sum(cached_body_evidence(root, message_id, queue['pending_messages']) is not None for message_id in pending)
    result = {'scan_started_epoch': now, 'scope_start_epoch': floor,
              'scan_deferred_until_start': now <= floor,
              'query_after_epoch': after,
              'query': f'after:{after} before:{now} -in:spam -in:trash -in:sent -in:drafts',
              'processed_message_count': len(known), 'queued_message_count': len(pending),
              'cached_body_count': cached, 'body_read_needed_count': len(pending) - cached}
    if not compact:
        result['processed_message_ids'] = sorted(known)
    return result


def record_search(root, scan, now=None, partial=False):
    now = int(time.time() if now is None else now)
    started, ids = _scan_ids(scan, now, require_tool=True, require_complete=not partial)
    known = processed_ids(root)
    queue = _queue(root)
    pending = {key: value for key, value in queue['pending_messages'].items() if key not in known}
    for message_id in sorted(ids - known):
        pending.setdefault(message_id, {'first_queued_epoch': started})
    complete = scan.get('pagination_complete') is True
    queue.update(pending_messages=pending)
    if complete:
        queue['searched_through_epoch'] = max(queue['searched_through_epoch'], started)
    # Queue and cursor are one atomic file: advancing cannot lose an unresolved ID.
    _save(root / 'work/gmail-staging-state.json', queue)
    cached = [entry for message_id in sorted(pending)
              if (entry := cached_body_evidence(root, message_id, pending)) is not None]
    cached_ids = {entry['message_id'] for entry in cached}
    return {'searched_message_count': len(ids), 'already_ingested_count': len(ids & known),
            'new_message_ids': sorted(ids - known), 'queued_message_ids': sorted(pending),
            'body_read_needed_ids': sorted(set(pending) - cached_ids),
            'cached_bodies': cached, 'search_cursor_advanced': complete,
            'ingestion_complete': complete and not pending, 'editorial_completion_claimed': False}


def cache_body(root, message_id, body_file):
    """Record a full plugin message envelope, never a summary or extraction."""
    queue = _queue(root)
    if message_id not in queue['pending_messages']:
        raise ValueError('Record the actual search before caching its message')
    path = _body_path(root, body_file)
    raw = path.read_bytes()
    body = json.loads(raw.decode('utf-8-sig'))
    if (not isinstance(body, dict) or body.get('message_id') != message_id
            or body.get('body_complete') is not True
            or not isinstance(body.get('message'), dict) or not body['message']):
        raise ValueError('Cache requires matching message_id, body_complete:true and the full plugin message object')
    message = body['message']
    payload = message.get('payload')
    if message.get('id') != message_id or not _full_mime_payload(payload):
        raise ValueError('Cache requires the matching plugin message.id and full Gmail MIME payload; snippets and summaries are insufficient')
    entry = queue['pending_messages'][message_id]
    entry.update(body_file=str(path), body_sha256=hashlib.sha256(raw).hexdigest())
    _save(root / 'work/gmail-staging-state.json', queue)
    return {'cached': True, 'message_id': message_id, 'body_file': str(path),
            'body_sha256': entry['body_sha256'], 'editorial_completion_claimed': False}


def _full_mime_payload(payload):
    """Recognize full Gmail MIME structure, including genuinely empty bodies."""
    if not isinstance(payload, dict) or not isinstance(payload.get('headers'), list):
        return False
    body = payload.get('body')
    parts = payload.get('parts')
    if not isinstance(body, dict) and not isinstance(parts, list):
        return False
    if parts is not None:
        if not isinstance(parts, list) or any(not _full_mime_payload(part) for part in parts):
            return False
    # MIME body metadata (size=0) is legitimate evidence for an empty message.
    # An empty placeholder dictionary without parts is not evidence of a body.
    if parts:
        return True
    if not isinstance(body, dict):
        return False
    # Gmail API names the encoded body "data"; the connected Gmail plugin
    # exposes it as "base64_url_content" and/or decoded "content".
    if any(isinstance(body.get(key), str) and body[key]
           for key in ('data', 'base64_url_content', 'content')):
        return True
    if type(body.get('size')) is int and body['size'] == 0:
        return True
    # Full Gmail messages contain attachment references, not attachment bytes.
    mime = payload.get('mimeType', payload.get('mime_type', ''))
    attachment = body.get('attachmentId', body.get('attachment_id'))
    return bool(attachment) and isinstance(mime, str) and bool(mime) and not mime.startswith('text/')


def read_cache(root, message_id):
    evidence = cached_body_evidence(root, message_id)
    if evidence is None:
        raise ValueError('Cached body missing or changed; read the full message through the Gmail plugin again')
    return json.loads(Path(evidence['body_file']).read_text(encoding='utf-8-sig'))


def finish(root, scan, now=None):
    now = int(time.time() if now is None else now)
    started, ids = _scan_ids(scan, now)
    missing = sorted((ids | set(_queue(root)['pending_messages'])) - processed_ids(root))
    if missing:
        return {'advanced': False, 'unresolved_message_ids': missing}
    path = root / 'work/gmail-scan-state.json'
    prior = _load(path, {}).get('completed_through_epoch', 0)
    state = {'completed_through_epoch': max(prior, started), 'last_scan_message_count': len(ids)}
    _save(path, state)
    return {'advanced': True, **state}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['begin', 'record-search', 'cache-body', 'read-cache', 'finish'])
    parser.add_argument('--scan-file', type=Path)
    parser.add_argument('--body-file', type=Path)
    parser.add_argument('--message-id')
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    if args.command in ('record-search', 'finish') and not args.scan_file:
        parser.error(args.command + ' requires --scan-file')
    if args.command in ('cache-body', 'read-cache') and not args.message_id:
        parser.error(args.command + ' requires --message-id')
    if args.command == 'cache-body' and not args.body_file:
        parser.error('cache-body requires --body-file')
    if args.command == 'begin':
        result = begin(ROOT, compact=args.compact)
    elif args.command == 'cache-body':
        result = cache_body(ROOT, args.message_id, args.body_file)
    elif args.command == 'read-cache':
        result = read_cache(ROOT, args.message_id)
    else:
        scan = json.loads(args.scan_file.read_text(encoding='utf-8-sig'))
        result = record_search(ROOT, scan) if args.command == 'record-search' else finish(ROOT, scan)
    print(json.dumps(result, ensure_ascii=False))

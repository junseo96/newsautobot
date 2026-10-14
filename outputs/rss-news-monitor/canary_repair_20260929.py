"""Bounded Canary active-queue repair. Dry-run never calls the network.

Only cached MIME-confirmed article links may be resolved on --apply. The
supervisor lock excludes a running service; source cache is the sole network
writer. Candidate JSON, URL, fingerprint, snapshot, journals and collector DB
are never rewritten. Queue changes require the same still-fresh active job.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid
from urllib.parse import urlsplit

import v11_source_cache as source_cache
from v11_runtime import InstanceLock, Queue, fingerprint, save_json, stamp
from v12_newsletter_context import candidate_link_evidence, is_canary_tracking


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_STATES = ('queued', 'deferred', 'inflight', 'ready_day')
UNKNOWN_DELAY = 6 * 60 * 60
REPAIR = 'canary_repair_20260929'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def host(url):
    try:
        return (urlsplit(url or '').hostname or '').lower()
    except (ValueError, TypeError):
        return ''


def read_only(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


class ReadOnlyQueue(Queue):
    """Reuse active_fresh with no constructor/schema writes, including dry-run."""
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        con = read_only(self.path)
        try:
            yield con
        finally:
            con.close()


def cached_result(root, url):
    path = Path(root) / 'work/v11/source-cache' / (digest(url) + '.json')
    try:
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        result = payload.get('result')
        return result if payload.get('url') == url and isinstance(result, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def build_plan(root):
    root = Path(root).resolve()
    queue = ReadOnlyQueue(root / 'work/v11/queue.db')
    with queue.connect() as con:
        rows = [dict(row) for row in con.execute(
            'SELECT * FROM jobs WHERE status IN (?,?,?,?) ORDER BY url', ACTIVE_STATES)]
    plan = []
    for job in rows:
        try:
            if not is_canary_tracking(job['url']):
                continue
        except (ValueError, TypeError):
            continue
        entry = {'job': job, 'fresh': False, 'allowed': None, 'eligibility': 'invalid_candidate'}
        plan.append(entry)
        try:
            candidate = json.loads(job['candidate'])
            if not isinstance(candidate, dict) or candidate.get('url') != job['url']:
                continue
            if fingerprint(candidate) != job['fingerprint']:
                continue
        except (ValueError, TypeError):
            continue
        entry['candidate'] = candidate
        entry['fresh'] = queue.active_fresh(job)
        if not entry['fresh']:
            entry['eligibility'] = 'stale_or_changed'
            continue
        try:
            evidence = candidate_link_evidence(root, candidate)
        except Exception:
            # Failed local evidence lookup is unresolved, never permission.
            evidence = None
        value = evidence.get('allowed') if isinstance(evidence, dict) else None
        entry['allowed'] = value if value is True or value is False else None
        entry['eligibility'] = 'fresh_active'
        entry['before_cache'] = cached_result(root, job['url']) if entry['allowed'] is True else {}
    return plan


def public_entry(entry):
    job = entry['job']
    return {
        'url_sha256': digest(job['url']), 'host': host(job['url']),
        'fingerprint': job['fingerprint'], 'candidate_sha256': digest(job['candidate']),
        'result_sha256': digest(job['result'] or ''), 'status_before': job['status'],
        'not_before': job['not_before'], 'attempts': job['attempts'],
        'reason_sha256': digest(job['reason'] or ''),
        'fresh': entry['fresh'], 'allowed': entry['allowed'], 'eligibility': entry['eligibility'],
    }


def has_new_clue(before, after, tracking_url):
    if not isinstance(after, dict):
        return False
    final = after.get('final_url') or tracking_url
    destination = host(final)
    resolved = bool(destination and destination != host(tracking_url))
    if resolved and final != (before.get('final_url') or tracking_url):
        return True
    if after.get('usable') is True:
        if before.get('usable') is not True:
            return True
        return any(after.get(key) != before.get(key) for key in ('text', 'published_at'))
    return False


def resolve_allowed(root, entry, queue):
    job = entry['job']
    if entry['allowed'] is not True or not entry['fresh'] or not queue.active_fresh(job):
        return {'clue': False, 'final_host': '', 'usable': False, 'resolved': False}
    try:
        # Permission comes only from cached MIME, never the tracker's URL slug.
        result = source_cache.get(root, job['url'])
    except Exception:
        result = {}
    return {
        'clue': has_new_clue(entry['before_cache'], result, job['url']),
        'final_host': host(result.get('final_url')),
        'final_url_sha256': digest(result.get('final_url') or ''),
        'usable': result.get('usable') is True,
        'resolved': bool(host(result.get('final_url')) and host(result.get('final_url')) != host(job['url'])),
    }


def apply_plan(root, plan):
    """Caller owns supervisor.lock and has persisted the sanitized pre-audit."""
    root = Path(root).resolve()
    queue = ReadOnlyQueue(root / 'work/v11/queue.db')
    allowed = [entry for entry in plan if entry['fresh'] and entry['allowed'] is True]
    with ThreadPoolExecutor(max_workers=4) as pool:
        resolved = list(pool.map(lambda entry: resolve_allowed(root, entry, queue), allowed))
    by_hash = {digest(entry['job']['url']): result for entry, result in zip(allowed, resolved)}
    outcomes = []
    con = sqlite3.connect(queue.path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            for entry in plan:
                audit = public_entry(entry)
                job = entry['job']
                audit.update(by_hash.get(audit['url_sha256'], {}))
                audit['action'] = 'untouched'
                if not entry['fresh'] or not queue.active_fresh(job):
                    audit['action'] = 'stale_or_changed'
                    outcomes.append(audit)
                    continue
                row = con.execute('SELECT * FROM jobs WHERE url=?', (job['url'],)).fetchone()
                if (row is None or row['status'] != job['status'] or row['status'] not in ACTIVE_STATES
                        or row['fingerprint'] != job['fingerprint'] or row['candidate'] != job['candidate']):
                    audit['action'] = 'stale_or_changed'
                    outcomes.append(audit)
                    continue
                if entry['allowed'] is None:
                    status, reason = 'deferred', REPAIR + ': cached MIME article-link evidence unresolved'
                    # A second application must not keep postponing an already
                    # recorded six-hour backoff without new evidence.
                    not_before = (row['not_before'] if row['status'] == status and row['reason'] == reason
                                  and row['not_before'] > time.time() else time.time() + UNKNOWN_DELAY)
                    attempts = row['attempts']
                    action = 'deferred_unknown_permission'
                elif entry['allowed'] is False:
                    status, reason, not_before, attempts = 'queued', REPAIR + ': MIME-proven utility link; local metadata ACK required', 0, row['attempts']
                    action = 'queued_for_metadata_ack'
                elif audit.get('clue'):
                    status, reason, not_before, attempts = 'queued', REPAIR + ': new resolved source evidence; normal article review required', 0, row['attempts']
                    action = 'queued_new_source_clue'
                else:
                    outcomes.append(audit)
                    continue
                fields = (status, reason, not_before, attempts)
                if fields == (row['status'], row['reason'], row['not_before'], row['attempts']):
                    audit['action'] = 'already_repaired'
                    outcomes.append(audit)
                    continue
                changed = con.execute(
                    'UPDATE jobs SET status=?,reason=?,not_before=?,attempts=? '
                    'WHERE url=? AND fingerprint=? AND status=? AND candidate=?',
                    (*fields, job['url'], job['fingerprint'], job['status'], job['candidate']))
                if changed.rowcount:
                    con.execute('INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)',
                                (stamp(), job['url'], REPAIR, action))
                    audit['action'], audit['status_after'] = action, status
                else:
                    audit['action'] = 'stale_or_changed'
                outcomes.append(audit)
    finally:
        con.close()
    return outcomes


def summary(rows):
    counts = {'selected_count': len(rows), 'fresh_count': sum(row['fresh'] for row in rows)}
    for label, value in (('true', True), ('false', False), ('unknown', None)):
        counts['permission_' + label + '_count'] = sum(row['fresh'] and row['allowed'] is value for row in rows)
    for action in sorted({row.get('action', 'planned') for row in rows}):
        counts[action + '_count'] = sum(row.get('action', 'planned') == action for row in rows)
    counts['resolved_count'] = sum(row.get('resolved') is True for row in rows)
    counts['usable_count'] = sum(row.get('usable') is True for row in rows)
    counts['distinct_resolved_url_hash_count'] = len({row['final_url_sha256'] for row in rows
                                                    if row.get('resolved') and row.get('final_url_sha256')})
    counts['hosts'] = sorted({row['final_host'] for row in rows if row.get('final_host')})
    return counts


def run(root=ROOT, apply=False):
    root = Path(root).resolve()
    # Audit directory names and contents never embed a tracking token/title.
    audit_dir = root / 'work/v12-fixes-20260929' / ('canary-' + uuid.uuid4().hex)

    def execute():
        plan = build_plan(root)
        before = [public_entry(entry) for entry in plan]
        save_json(audit_dir / 'before.json', {'apply': apply, 'rows': before, 'counts': summary(before)})
        after = apply_plan(root, plan) if apply else before
        report = {'apply': apply, 'rows': after, 'counts': summary(after)}
        save_json(audit_dir / 'result.json', report)
        return dict(report['counts'], audit_sha256=digest(json.dumps(report, sort_keys=True)),
                    dry_run_count=int(not apply), applied_run_count=int(apply))

    if apply:
        with InstanceLock(root / 'work/v11/supervisor.lock'):
            return execute()
    return execute()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.root, args.apply)
    except Exception:
        # Network exceptions and JSON errors may contain the original tracker.
        print(json.dumps({'repair_failed_count': 1}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

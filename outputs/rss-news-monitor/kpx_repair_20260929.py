"""One-time, evidence-bound KPX completion alias repair; dry-run by default.

Only the known KPX notice is eligible. A saved worker assignment must recreate
an existing raw four-field reviewed fingerprint; the stored decision must have
a matching actual reviewed ACK record. The new source-normalized fingerprint
must exactly match the current candidate. No model, collector or sender runs.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from source_normalization import is_kpx_notice_url, kpx_listing_title
from v11_runtime import InstanceLock, fingerprint, save_json, stamp


ROOT = Path(__file__).resolve().parents[2]
TARGET_URL_SHA256 = 'f41cb705ff0ecf23403f830aaaded6b8c7158085e96160f0ce47d9eb1d5b115c'
ACTIVE_STATES = {'queued', 'deferred', 'inflight', 'ready_day'}


@contextmanager
def supervisor_lock(path):
    lock = InstanceLock(path)
    try:
        with lock:
            yield
    finally:
        # InstanceLock.__enter__ may fail after opening the handle. Close it
        # even then; the failed lock must never advance to database mutation.
        if lock.file is not None:
            lock.file.close()


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def raw_fingerprint(candidate):
    content = {key: candidate.get(key) for key in ('url', 'title', 'summary', 'published_at')}
    return digest(json.dumps(content, sort_keys=True, ensure_ascii=False))


def read_only(path):
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def reviewed_result(row):
    try:
        result = json.loads(row['result'])
    except (TypeError, ValueError):
        return None
    if (row['status'] != 'reviewed' or not isinstance(result, dict)
            or result.get('action') != 'reviewed' or result.get('verified') is not True
            or not row['reason'] or result.get('reason') != row['reason']
            or result.get('message_text') is not None):
        return None
    return result


def build_plan(root, target_url_sha256=TARGET_URL_SHA256):
    root = Path(root).resolve()
    con = read_only(root / 'work/v11/queue.db')
    try:
        matches = [dict(row) for row in con.execute('SELECT * FROM jobs')
                   if digest(row['url']) == target_url_sha256 and is_kpx_notice_url(row['url'])]
        if len(matches) != 1:
            return {'status': 'no_target', 'target_url_sha256': target_url_sha256}
        job = matches[0]
        plan = {'status': 'no_proven_alias', 'target_url_sha256': target_url_sha256,
                'old_job': job, 'proof_count': 0}
        if job['status'] not in ACTIVE_STATES:
            plan['status'] = 'protected_or_already_complete'
            return plan
        candidate = json.loads(job['candidate'])
        if candidate.get('url') != job['url']:
            raise ValueError('Current candidate URL does not match its queue identity')
        normalized = fingerprint(candidate)
        if job['fingerprint'] not in {raw_fingerprint(candidate), normalized}:
            raise ValueError('Current queue fingerprint does not match its saved candidate')
        plan['normalized_fingerprint'] = normalized
        versions = {row['fingerprint']: dict(row) for row in con.execute(
            "SELECT * FROM completed_versions WHERE url=? AND status='reviewed'", (job['url'],))}
        alias = con.execute('SELECT * FROM completed_versions WHERE url=? AND fingerprint=?',
                            (job['url'], normalized)).fetchone()
        plan['existing_alias'] = dict(alias) if alias else None
    finally:
        con.close()
    ack_con = read_only(root / 'work/rss-news-monitor.db')
    try:
        acknowledgements = [dict(row) for row in ack_con.execute(
            "SELECT id,run_id,status,reason,decided_at FROM decision_history WHERE url=? AND status='reviewed' ORDER BY id DESC",
            (job['url'],))]
    finally:
        ack_con.close()
    proofs = []
    for path in sorted((root / 'work/v11/reviews').glob('*/prompt.txt')):
        raw = path.read_bytes()
        prompt = raw.decode('utf-8-sig').replace('\r\n', '\n')
        if job['url'] not in prompt:
            continue
        try:
            assignment = json.loads(prompt.split('\nASSIGNMENT\n', 1)[1])
        except (IndexError, ValueError):
            continue
        for previous in assignment.get('candidates', []):
            if not isinstance(previous, dict) or previous.get('url') != job['url']:
                continue
            # Require the observed KPX decoration; never infer semantic identity.
            if kpx_listing_title(previous['url'], previous.get('title'))[1] is None:
                continue
            raw_hash = raw_fingerprint(previous)
            completed = versions.get(raw_hash)
            if completed is None or reviewed_result(completed) is None:
                continue
            if fingerprint(previous) != normalized:
                continue
            ack = next((row for row in acknowledgements if row['reason'] == completed['reason']), None)
            if ack is None:
                continue
            proofs.append({'prompt_file': str(path), 'prompt_sha256': hashlib.sha256(raw).hexdigest(),
                           'assignment_run_id': assignment.get('run_id'),
                           'candidate': previous, 'raw_fingerprint': raw_hash,
                           'completed_version': completed, 'reviewed_ack': ack})
    plan['proof_count'] = len(proofs)
    if not proofs:
        return plan
    proofs.sort(key=lambda row: (row['reviewed_ack']['id'], row['prompt_file']), reverse=True)
    proof = proofs[0]
    if plan['existing_alias'] is not None:
        old_alias = plan['existing_alias']
        if (reviewed_result(old_alias) is None or any(old_alias[key] != proof['completed_version'][key]
                                                    for key in ('status', 'reason', 'result'))):
            plan['status'] = 'existing_alias_conflict'
            return plan
    plan.update(status='ready', proof=proof)
    return plan


def summary(plan, mode='dry_run', audit_file=None):
    # Never print the raw URL, article body, tracking strings or stored reason.
    result = {'mode': mode, 'status': plan['status'], 'target_url_sha256': plan['target_url_sha256'],
              'proof_count': plan.get('proof_count', 0)}
    if 'old_job' in plan:
        result['old_status'] = plan['old_job']['status']
        result['old_fingerprint'] = plan['old_job']['fingerprint']
    if 'normalized_fingerprint' in plan:
        result['normalized_fingerprint'] = plan['normalized_fingerprint']
    if 'proof' in plan:
        result['proof_raw_fingerprint'] = plan['proof']['raw_fingerprint']
        result['proof_ack_id'] = plan['proof']['reviewed_ack']['id']
    if audit_file:
        result['audit_file'] = str(audit_file)
    return result


def repair(root, apply=False, target_url_sha256=TARGET_URL_SHA256):
    root = Path(root).resolve()
    if not apply:
        return summary(build_plan(root, target_url_sha256))
    with supervisor_lock(root / 'work/v11/supervisor.lock'):
        plan = build_plan(root, target_url_sha256)
        if plan['status'] != 'ready':
            return summary(plan, 'apply')
        audit_path = root / 'work/v12-fixes-20260929/repairs' / ('kpx-' + uuid.uuid4().hex + '.json')
        audit = {'schema_version': 1, 'status': 'prepared', 'prepared_at': stamp(), 'plan': plan,
                 'new_ack_created': False, 'telegram_called': False}
        con = sqlite3.connect(root / 'work/v11/queue.db', timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('SELECT * FROM jobs WHERE url=?', (plan['old_job']['url'],)).fetchone()
            if current is None or dict(current) != plan['old_job']:
                raise ValueError('Queue changed after proof inspection; no repair applied')
            proof = plan['proof']
            completed = con.execute('SELECT * FROM completed_versions WHERE url=? AND fingerprint=?',
                                    (current['url'], proof['raw_fingerprint'])).fetchone()
            if completed is None or dict(completed) != proof['completed_version']:
                raise ValueError('Stored reviewed proof changed; no repair applied')
            if hashlib.sha256(Path(proof['prompt_file']).read_bytes()).hexdigest() != proof['prompt_sha256']:
                raise ValueError('Saved assignment proof changed; no repair applied')
            alias = con.execute('SELECT * FROM completed_versions WHERE url=? AND fingerprint=?',
                                (current['url'], plan['normalized_fingerprint'])).fetchone()
            if (dict(alias) if alias else None) != plan['existing_alias']:
                raise ValueError('Completion alias changed; no repair applied')
            # Durable complete old-state/proof artifact precedes every mutation.
            save_json(audit_path, audit)
            con.execute('INSERT OR IGNORE INTO completed_versions(url,fingerprint,status,reason,result) VALUES(?,?,?,?,?)',
                        (current['url'], plan['normalized_fingerprint'], completed['status'], completed['reason'], completed['result']))
            con.execute("UPDATE jobs SET fingerprint=?,status='reviewed',reason=?,result=?,not_before=0,updated=? WHERE url=?",
                        (plan['normalized_fingerprint'], completed['reason'], completed['result'], time.time(), current['url']))
            con.execute('INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)',
                        (stamp(), current['url'], 'kpx_review_alias_restored',
                         json.dumps({'audit': str(audit_path), 'proof_raw_fingerprint': proof['raw_fingerprint'],
                                     'reviewed_ack_id': proof['reviewed_ack']['id']}, ensure_ascii=True)))
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
        audit.update(status='applied', applied_at=stamp(), alias_inserted=plan['existing_alias'] is None)
        save_json(audit_path, audit)
        return summary({**plan, 'status': 'applied'}, 'apply', audit_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true', help='Apply the proven one-notice alias while supervisor is stopped')
    args = parser.parse_args()
    print(json.dumps(repair(args.root, args.apply), ensure_ascii=True))


if __name__ == '__main__':
    main()

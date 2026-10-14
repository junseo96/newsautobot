"""Read-only operational audit. Never reads credentials or email bodies."""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
from pathlib import Path
import sqlite3
import statistics


def audit(root, hours=24):
    root = Path(root)
    work = root / 'work/v11'
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - hours * 3600
    report = {'version': 12, 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'hours': hours}
    usages = {}
    for lane in ('reviews', 'gmail'):
        rows = []
        for path in (work / lane).glob('**/execution.json'):
            if path.stat().st_mtime < cutoff:
                continue
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            usage = collections.Counter()
            for item in data.get('usage', []):
                usage.update({k: v for k, v in item.items() if isinstance(v, (int, float))})
            prompt = path.parent / 'prompt.txt'
            row = dict(usage)
            row.update(model=data.get('model'), exit_code=data.get('exit_code'),
                       prompt_bytes=prompt.stat().st_size if prompt.exists() else 0)
            rows.append(row)
        totals = collections.Counter()
        for row in rows:
            totals.update({k: v for k, v in row.items() if k.endswith('tokens') or k == 'prompt_bytes'})
        usages[lane] = {'calls': len(rows), 'failures': sum(r.get('exit_code') != 0 for r in rows),
                       'totals': dict(totals),
                       'median_input_tokens': statistics.median([r.get('input_tokens', 0) for r in rows]) if rows else 0,
                       'uncached_input_tokens': totals['input_tokens'] - totals['cached_input_tokens']}
    report['usage'] = usages
    con = sqlite3.connect((work / 'queue.db').resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        report['queue'] = dict(con.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status'))
        report['pending'] = [dict(r) for r in con.execute("SELECT url,status,attempts,reason FROM jobs WHERE status NOT IN ('reviewed','delivered') ORDER BY queued")]
        report['recent_outcomes'] = dict(con.execute('SELECT action,COUNT(*) FROM events WHERE at>=? GROUP BY action', (dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).isoformat(),)))
        report['repeat_review_urls'] = [dict(r) for r in con.execute("SELECT url,COUNT(*) AS decisions FROM events WHERE action='reviewed' AND at>=? GROUP BY url HAVING COUNT(*)>1 ORDER BY decisions DESC LIMIT 15", (dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).isoformat(),))]
    finally:
        con.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--hours', type=int, default=24)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.root, args.hours)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))

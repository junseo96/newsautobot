"""Small, durable usage counters. No prompts, email bodies or secrets."""
import datetime as dt
from pathlib import Path
import sqlite3


def record_usage(root, directory, model, usages, exit_code):
    path=Path(root)/'work/v11/usage.db'
    path.parent.mkdir(parents=True,exist_ok=True)
    totals={key:sum(int(row.get(key,0)) for row in usages) for key in ('input_tokens','cached_input_tokens','output_tokens')}
    lane='gmail' if 'gmail' in Path(directory).parts else ('novelty' if Path(directory).name.startswith('novelty-') else 'review')
    with sqlite3.connect(path,timeout=30) as con:
        con.execute('CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY,at TEXT,model TEXT,lane TEXT,exit_code INTEGER,input_tokens INTEGER,cached_input_tokens INTEGER,output_tokens INTEGER)')
        con.execute('INSERT OR REPLACE INTO executions VALUES(?,?,?,?,?,?,?,?)',
                    (str(directory),dt.datetime.now(dt.timezone.utc).isoformat(),model,lane,exit_code,totals['input_tokens'],totals['cached_input_tokens'],totals['output_tokens']))


def usage_summary(root):
    path=Path(root)/'work/v11/usage.db'
    if not path.exists():return {'calls':0}
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=24)).isoformat()
    con=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        rows=con.execute('SELECT lane,COUNT(*),SUM(input_tokens),SUM(cached_input_tokens),SUM(output_tokens),SUM(exit_code!=0) FROM executions WHERE at>=? GROUP BY lane',(cutoff,)).fetchall()
        return {r[0]:{'calls':r[1],'input_tokens':r[2],'cached_input_tokens':r[3],'uncached_input_tokens':r[2]-r[3],'output_tokens':r[4],'failed':r[5]} for r in rows}
    finally:con.close()

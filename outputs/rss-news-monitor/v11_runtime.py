"""Small process/queue primitives for V11. No credentials are read here."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from source_normalization import article_title

KST = dt.timezone(dt.timedelta(hours=9))

def stamp():
    return dt.datetime.now(KST).isoformat(timespec='seconds')

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)

def fingerprint(candidate):
    # Collector update/discovery timestamps are not changes to article facts.
    # In particular, the same newsletter arriving again must not reopen a review.
    content = {key:candidate.get(key) for key in ('url','title','summary','published_at')}
    content['title'] = article_title(content['url'],content['title'])
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def _candidate_epoch(candidate):
    # An absent publication timestamp may use first discovery for queueing,
    # never as proof of the article's real publication date.
    # T&D World has an exact original-page timestamp: do not substitute the
    # crawl time when that lookup failed, which would revive an old article.
    if candidate.get('source')=='T&D World' and not candidate.get('published_at'):
        return None
    value=candidate.get('published_at') or candidate.get('first_seen_at')
    if not value:return None
    try:
        parsed=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()

def _fresh_candidate(candidate,now,start,max_age_hours):
    if start is None:return True
    from v12_controls import analysis_candidate
    if analysis_candidate(candidate):max_age_hours=max(max_age_hours,168)
    # A newly received newsletter may reveal a same-day article published just
    # before the live reset. The reviewer must still verify the original date.
    mail_received=candidate.get('newsletter_received_at')
    if mail_received:
        try:
            received=dt.datetime.fromisoformat(str(mail_received).replace('Z','+00:00'))
            if received.tzinfo is not None and float(start)<=received.timestamp()<=now and now-received.timestamp()<=float(max_age_hours)*3600:
                return True
        except (ValueError,TypeError):
            pass
    published=_candidate_epoch(candidate)
    if candidate.get('publication_precision')=='date' and published is not None:
        # A calendar day is an interval, not evidence of midnight publication.
        # Permit review when that day overlaps the live window; the worker must
        # confirm the original date and cannot invent a more precise timestamp.
        first_seen=candidate.get('first_seen_at')
        try: discovered=dt.datetime.fromisoformat(first_seen.replace('Z','+00:00')).timestamp()
        except (AttributeError,ValueError,TypeError): discovered=now
        from v12_controls import publication_day_bounds
        lower,upper=publication_day_bounds(candidate['published_at'])
        return lower<=now and upper>max(float(start),now-float(max_age_hours)*3600) and discovered>=float(start)
    return published is not None and published>=max(float(start),now-float(max_age_hours)*3600)

def normal_window(config, now=None):
    now = now or dt.datetime.now(KST)
    window = config.get('normal_delivery_window_kst', {'start':'06:00','end':'21:00'})
    minute = now.astimezone(KST).hour * 60 + now.astimezone(KST).minute
    start,end = (int(value.split(':')[0])*60+int(value.split(':')[1]) for value in (window['start'],window['end']))
    return start <= minute <= end

def scheduled_brief_slot(config, now=None):
    """Return the current KST standard-brief slot during its bounded grace period."""
    local=(now or dt.datetime.now(KST)).astimezone(KST)
    grace=int(config.get('standard_brief_grace_minutes',90))
    slots=[]
    for value in config.get('standard_brief_times_kst',[]):
        hour,minute=(int(part) for part in value.split(':'))
        candidate=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
        if candidate<=local:slots.append(candidate)
    if not slots:return None
    latest=max(slots)
    if (local-latest).total_seconds()>grace*60:return None
    return latest.isoformat(timespec='minutes')

def may_send(decision, config, now=None):
    if config.get('urgent_delivery_24h') is True and decision.get('urgency') == 'immediate':
        return True
    if config.get('delivery_mode')=='important_realtime_standard_scheduled_briefs':
        return False
    return normal_window(config, now)

def run_process(command, *, timeout=900, stdin=None, cwd=None):
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    environment=os.environ.copy()
    if os.name=='nt' and Path(str(command[0])).name.lower()=='powershell.exe':
        # A PS7 host must not make Windows PowerShell 5 load incompatible PS7 modules.
        environment['PSMODULEPATH']=os.pathsep.join([str(Path(os.environ['ProgramFiles'])/'WindowsPowerShell/Modules'),
            str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/Modules')])
    process = subprocess.Popen([str(x) for x in command], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
        text=True, encoding='utf-8', errors='replace', creationflags=creationflags,env=environment)
    try:
        out,err = process.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=creationflags)
        else:
            process.kill()
        out,err = process.communicate()
        raise TimeoutError('Child process timed out; output retained by caller only when available')
    return process.returncode,out,err

def powershell(root, filename, *arguments, timeout=300):
    code,out,err = run_process(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
        Path(root)/'outputs/rss-news-monitor'/filename,*arguments],timeout=timeout,cwd=root)
    if code:
        raise RuntimeError(f'{filename} exited {code}: {err[-1800:]}')
    try:
        return json.loads(out.lstrip('\ufeff').strip())
    except ValueError as exc:
        raise ValueError(f'{filename} did not return JSON: {out[-600:]}') from exc

def codex(root, config, prompt, directory, *, schema=None, gmail=False):
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    executable = config.get('codex_executable') or shutil.which('codex.exe') or shutil.which('codex')
    if not executable and os.name=='nt':
        installed=Path(os.environ.get('LOCALAPPDATA',''))/'OpenAI/Codex/bin'
        binaries=list(installed.glob('*/codex.exe'))
        if binaries:executable=str(max(binaries,key=lambda p:p.stat().st_mtime))
    if not executable or not Path(executable).exists():
        raise RuntimeError('Codex CLI executable unavailable')
    output = directory/'response.json'
    model = config.get('gmail_model', config.get('model','gpt-6-sol')) if gmail else config.get('model','gpt-6-sol')
    effort = config.get('gmail_reasoning_effort', config.get('reasoning_effort','medium')) if gmail else config.get('reasoning_effort','medium')
    command=[executable,'exec','--skip-git-repo-check','--ephemeral','-C',str(root),'-s','read-only',
        '-m',model,'-c','model_reasoning_effort="'+effort+'"',
        '-c','skills.max_context_tokens=512','-c','web_search="'+config.get('worker_web_search','live')+'"','--json','-o',str(output)]
    if not gmail:
        command.append('--ignore-user-config')
    for setting in config.get('gmail_cli_overrides' if gmail else 'review_cli_overrides',[]):
        command.extend(['-c',setting])
    if schema is not None:
        schema_path=directory/'schema.json'; save_json(schema_path,schema)
        command.extend(['--output-schema',str(schema_path)])
    command.append('-')
    (directory/'prompt.txt').write_text(prompt,encoding='utf-8')
    code,out,err=run_process(command,timeout=config.get('worker_timeout_seconds',900),stdin=prompt,cwd=root)
    (directory/'events.jsonl').write_text(out,encoding='utf-8')
    (directory/'stderr.log').write_text(err,encoding='utf-8')
    events=[]
    for line in out.splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    usage=[x.get('usage',{}) for x in events if x.get('type')=='turn.completed']
    save_json(directory/'execution.json',{'finished_at':stamp(),'exit_code':code,'model':model,
                                          'reasoning_effort':effort,'usage':usage,
                                          'prompt_bytes':len(prompt.encode('utf-8')),
                                          'tool_calls':sum(x.get('type')=='item.completed' and x.get('item',{}).get('type') not in ('agent_message','reasoning') for x in events)})
    from v12_metrics import record_usage
    record_usage(root,directory,model,usage,code)
    if code or not any(x.get('type')=='turn.completed' for x in events):
        raise RuntimeError(f'Codex worker failed: exit {code}; see {directory}/stderr.log')
    result=None
    if output.exists():
        raw=output.read_text(encoding='utf-8-sig').strip()
        try: result=json.loads(raw)
        except ValueError:
            if schema is not None: raise ValueError('Worker output is not valid JSON')
    return result,events

class Queue:
    """Every candidate is durable; backoff is not a completed editorial decision."""
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as con:
            con.execute('CREATE TABLE IF NOT EXISTS jobs(url TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, candidate TEXT NOT NULL, snapshot TEXT NOT NULL, candidate_index INTEGER NOT NULL, status TEXT NOT NULL, queued REAL NOT NULL, updated REAL NOT NULL, not_before REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, reason TEXT, result TEXT)')
            con.execute('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT NOT NULL,url TEXT,action TEXT NOT NULL,detail TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS completed_versions(url TEXT NOT NULL,fingerprint TEXT NOT NULL,status TEXT NOT NULL,reason TEXT,result TEXT,PRIMARY KEY(url,fingerprint))')
    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.path,timeout=30); con.row_factory=sqlite3.Row
        try:
            with con: yield con
        finally: con.close()
    def _realtime_rule(self,con):
        rows=dict(con.execute("SELECT key,value FROM state WHERE key IN ('realtime_start_epoch','realtime_max_age_hours')"))
        return (json.loads(rows['realtime_start_epoch']) if 'realtime_start_epoch' in rows else None,
                json.loads(rows['realtime_max_age_hours']) if 'realtime_max_age_hours' in rows else 12)
    def _scheduled_age(self,con,default):
        row=con.execute("SELECT value FROM state WHERE key='scheduled_brief_max_age_hours'").fetchone()
        return json.loads(row[0]) if row else default
    def _prune_stale(self,con,now,start,max_age_hours):
        if start is None:return 0
        rows=con.execute("SELECT url,candidate,status FROM jobs WHERE status IN ('queued','deferred','ready_day')").fetchall()
        scheduled_age=self._scheduled_age(con,max_age_hours)
        removed=0
        for row in rows:
            allowed_age=scheduled_age if row['status']=='ready_day' else max_age_hours
            if not _fresh_candidate(json.loads(row['candidate']),now,start,allowed_age):
                con.execute("DELETE FROM jobs WHERE url=? AND status IN ('queued','deferred','ready_day')",(row['url'],))
                removed+=1
        if removed:
            con.execute('INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)',
                        (stamp(),None,'realtime_expiry',f'{removed} stale unprocessed candidates removed'))
        return removed
    def enqueue(self,snapshot,path):
        count=0; skipped=0; now=time.time()
        with self.connect() as con:
            start,max_age_hours=self._realtime_rule(con)
            for index,candidate in enumerate(snapshot['candidates']):
                if not _fresh_candidate(candidate,now,start,max_age_hours):
                    skipped+=1;continue
                fp=fingerprint(candidate); old=con.execute('SELECT * FROM jobs WHERE url=?',(candidate['url'],)).fetchone()
                data=json.dumps(candidate,ensure_ascii=False)
                if old is not None and old['status']=='delivery_uncertain':
                    # Even a changed title must not erase an uncertain send.
                    continue
                if old is not None and old['status'] in ('reviewed','delivered'):
                    con.execute('INSERT OR IGNORE INTO completed_versions VALUES(?,?,?,?,?)',
                                (old['url'],fingerprint(json.loads(old['candidate'])),old['status'],old['reason'],old['result']))
                if old is not None and old['fingerprint']!=fp and fingerprint(json.loads(old['candidate']))==fp:
                    con.execute('UPDATE jobs SET fingerprint=? WHERE url=?',(fp,candidate['url']))
                    old=dict(old);old['fingerprint']=fp
                if old is None:
                    con.execute('INSERT INTO jobs(url,fingerprint,candidate,snapshot,candidate_index,status,queued,updated) VALUES(?,?,?,?,?,?,?,?)',
                        (candidate['url'],fp,data,str(path),index,'queued',now,now)); count+=1
                elif old['fingerprint']!=fp:
                    completed=con.execute('SELECT * FROM completed_versions WHERE url=? AND fingerprint=?',(candidate['url'],fp)).fetchone()
                    status=completed['status'] if completed else 'queued'
                    con.execute('UPDATE jobs SET fingerprint=?,candidate=?,snapshot=?,candidate_index=?,status=?,queued=?,updated=?,not_before=0,attempts=0,reason=?,result=? WHERE url=?',
                        (fp,data,str(path),index,status,now,now,completed['reason'] if completed else None,completed['result'] if completed else None,candidate['url']))
                    if not completed:count+=1
                else:
                    con.execute('UPDATE jobs SET candidate=?,snapshot=?,candidate_index=?,updated=? WHERE url=?',(data,str(path),index,now,candidate['url']))
                    if old['status'] in ('queued','deferred'):
                        # A proven completed-version alias can be installed by
                        # a migration. Normalizing an old fingerprint in-place
                        # above must not bypass that identical-content result.
                        completed=con.execute('SELECT * FROM completed_versions WHERE url=? AND fingerprint=?',(candidate['url'],fp)).fetchone()
                        if completed is not None and completed['status'] in ('reviewed','delivered'):
                            con.execute('UPDATE jobs SET status=?,reason=?,result=?,not_before=0 WHERE url=?',
                                        (completed['status'],completed['reason'],completed['result'],candidate['url']))
            expired=self._prune_stale(con,now,start,max_age_hours)
            self._set(con,'latest_snapshot',str(path))
            if start is not None:self._set(con,'last_realtime_filter',{'at':stamp(),'fresh_enqueued':count,
                'old_or_undated_skipped':skipped,'expired_pending_removed':expired})
        return count
    def _set(self,con,key,value):
        con.execute('INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value,ensure_ascii=False)))
    def set(self,key,value):
        with self.connect() as con:self._set(con,key,value)
    def get(self,key,default=None):
        with self.connect() as con: row=con.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def reset_inflight(self):
        with self.connect() as con: con.execute("UPDATE jobs SET status='queued' WHERE status='inflight'")
    def take(self,limit):
        if limit < 1:return []
        now=time.time()
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            start,max_age_hours=self._realtime_rule(con)
            self._prune_stale(con,now,start,max_age_hours)
            # Half for important industrial candidates, a quarter for oldest
            # remaining work, and the rest for newest remaining candidates.
            # These are scheduling hints only: every candidate stays durable.
            available="status IN ('queued','deferred') AND not_before<=?"
            # DART list.json gives a calendar day only. Use discovery order for
            # those filings instead of fabricating a midnight publication time.
            newest="COALESCE(julianday(CASE WHEN json_extract(candidate,'$.publication_precision')='date' THEN datetime(queued,'unixepoch') ELSE json_extract(candidate,'$.published_at') END),0) DESC,queued DESC,url"
            important=con.execute("SELECT * FROM jobs WHERE "+available+" AND (CAST(COALESCE(json_extract(candidate,'$.score'),0) AS REAL)>=50 OR json_extract(candidate,'$.must_review')=1) ORDER BY "+newest+" LIMIT ?",(now,limit)).fetchall()
            old=con.execute("SELECT * FROM jobs WHERE "+available+" ORDER BY queued,url LIMIT ?",(now,limit)).fetchall()
            domestic=con.execute("SELECT * FROM jobs WHERE "+available+" AND json_extract(candidate,'$.source_group') IN ('korea_industry','korea_grid_policy') ORDER BY "+newest+" LIMIT ?",(now,limit)).fetchall()
            recent=con.execute("SELECT * FROM jobs WHERE "+available+" ORDER BY "+newest+" LIMIT ?",(now,limit)).fetchall()
            important_slots=max(1,limit//2); old_slots=max(1,limit//4) if limit>1 else 0
            single_turn=None
            if limit==1:
                previous=con.execute("SELECT value FROM state WHERE key='single_take_turn'").fetchone()
                single_turn=int(json.loads(previous[0])) if previous else 0
                important_slots=int(single_turn%4 in (0,1)); old_slots=int(single_turn%4==2)
            rows=[]; seen=set()
            def append_available(options,count):
                added=0
                for row in options:
                    if added>=count or len(rows)>=limit:break
                    if row['url'] not in seen:
                        rows.append(dict(row));seen.add(row['url']);added+=1
            append_available(important,important_slots)
            append_available(old,old_slots)
            # One residual slot for domestic coverage, without displacing the
            # important half or oldest-work slot. Admission is not send approval.
            if limit>=4:append_available(domestic,1)
            append_available(recent,limit-len(rows))
            if single_turn is not None and rows:self._set(con,'single_take_turn',single_turn+1)
            for row in rows: con.execute("UPDATE jobs SET status='inflight',attempts=attempts+1 WHERE url=?",(row['url'],))
        return rows
    def finish(self,job,status,reason,result=None,delay=0):
        with self.connect() as con:
            changed=con.execute('UPDATE jobs SET status=?,reason=?,result=?,not_before=? WHERE url=? AND fingerprint=?',
                (status,reason,json.dumps(result,ensure_ascii=False) if result is not None else None,time.time()+delay,job['url'],job['fingerprint']))
            if changed.rowcount and status in ('reviewed','delivered'):
                con.execute('INSERT OR REPLACE INTO completed_versions VALUES(?,?,?,?,?)',
                            (job['url'],job['fingerprint'],status,reason,json.dumps(result,ensure_ascii=False) if result is not None else None))
            con.execute('INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)',(stamp(),job['url'],status if changed.rowcount else 'stale_result',reason))
            return bool(changed.rowcount)
    def active_fresh(self,job):
        with self.connect() as con:
            row=con.execute('SELECT fingerprint,candidate,status FROM jobs WHERE url=?',(job['url'],)).fetchone()
            if not row or row['fingerprint']!=job['fingerprint'] or row['status'] not in ('queued','deferred','inflight','ready_day'):
                return False
            start,max_age_hours=self._realtime_rule(con)
            if row['status']=='ready_day':
                max_age_hours=self._scheduled_age(con,max_age_hours)
            return _fresh_candidate(json.loads(row['candidate']),time.time(),start,max_age_hours)
    def drop_pending(self,job,reason='Expired under realtime freshness rule'):
        with self.connect() as con:
            deleted=con.execute("DELETE FROM jobs WHERE url=? AND fingerprint=? AND status IN ('queued','deferred','inflight','ready_day')",
                                (job['url'],job['fingerprint']))
            if deleted.rowcount:
                con.execute('INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)',
                            (stamp(),job['url'],'realtime_expiry',reason))
            return bool(deleted.rowcount)
    def ready(self):
        with self.connect() as con:return [dict(r) for r in con.execute("SELECT * FROM jobs WHERE status='ready_day' ORDER BY queued")]
    def counts(self):
        with self.connect() as con:return dict(con.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status'))

class InstanceLock:
    def __init__(self,path):self.path=Path(path); self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b'); self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            if self.path.stat().st_size==0:self.file.write(b'0');self.file.flush();self.file.seek(0)
            msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return self
    def __exit__(self,*args):
        self.file.close()

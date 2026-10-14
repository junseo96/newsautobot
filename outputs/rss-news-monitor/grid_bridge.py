"""Independent, evidence-only Newsflow -> grid observatory outbox.

No collector, LLM or Telegram invocation. An HTTP failure never rolls back a
news decision. Legacy verified facts are context, not invented project stages.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, sqlite3, urllib.request, re, math
from pathlib import Path
from copy import deepcopy
from contextlib import contextmanager, closing
from v11_decision import DECISION_SCHEMA, _object, _nullable, _shape, _http_url, _date

REGIONS=['CAISO','ERCOT','ISO-NE','MISO','NYISO','PJM','SPP','West','Southeast','US','Unknown']
KINDS=['generation','storage','load','transmission','distribution','policy','unknown']
GATES=['study','contract','permit','equipment','construction','energization','policy','unknown']
STATES=['proposed','pending','conditional','approved','rejected','blocked','withdrawn','under_construction','operating','completed','unknown']
CAPACITY=_object({'mw':{'type':'number'},'basis':{'type':'string','enum':['generation','storage_power','grid_request','contracted_supply','campus_plan','transfer_capacity','unknown']},'qualifier':{'type':'string'}})
GRID_EVENT_SCHEMA=_object({
    'asset_name':{'type':'string'},'asset_kind':{'type':'string','enum':KINDS},
    'region':{'type':'string','enum':REGIONS},'state':_nullable({'type':'string'}),
    'queue_id':_nullable({'type':'string'}),'official_project_id':_nullable({'type':'string'}),
    'utility':_nullable({'type':'string'}),'gate':{'type':'string','enum':GATES},
    'status':{'type':'string','enum':STATES},'certainty':{'type':'string','enum':['confirmed','conditional','proposed']},
    'direction':{'type':'string','enum':['improved','worsened','neutral','unclear']},
    'previous_fact':{'type':'string'},'new_fact':{'type':'string'},
    'effective_date':_nullable({'type':'string'}),'capacity':_nullable(CAPACITY),
    'remaining_requirements':{'type':'array','items':{'type':'string'}},
    'source_urls':{'type':'array','items':{'type':'string'}},
})
WORKER_SCHEMA=deepcopy(DECISION_SCHEMA)
WORKER_SCHEMA['properties']['decisions']['items']['properties']['dashboard_events']={'type':'array','items':GRID_EVENT_SCHEMA}
WORKER_SCHEMA['properties']['decisions']['items']['required'].append('dashboard_events')
PROMPT=('\nDASHBOARD (independent of Telegram action): Return dashboard_events=[] unless an ORIGINAL-reviewed US grid-related fact supports a project/policy change. '
 'Even reviewed/non-send decisions may contain dashboard events. For each generation/storage/load interconnection or T&D permit, study, contract, equipment, construction, energization change, identify asset, explicit region/state/official IDs and gate. State is a two-letter uppercase US code or null. '
 'Use Unknown/null for missing evidence; never infer an ISO from a company headquarters or turn a PPA into interconnection approval. A rejected permit is rejected, not completed. '
 'Keep remaining prerequisites explicit; one approval does not mean every gate cleared. Capacity must state its basis: campus plan, grid request and contracted supply are NOT additive. '
 'Proposals/conditional decisions must retain that certainty. Region-wide policy changes use asset_kind=policy and do not imply any named project approval. '
 'No stock-only news, invented before-states, invented dates or queue IDs. All event source_urls must be reviewed source_urls. Reuse already-read evidence; NO extra research solely for dashboard enrichment.\n')

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Bridge:
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'work/grid-bridge/grid.db'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS observations(
              id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, source_url TEXT NOT NULL,
              observed_at TEXT NOT NULL, payload TEXT NOT NULL, telegram_status TEXT NOT NULL,
              dashboard_status TEXT NOT NULL, synced_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT, provenance TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS grid_outbox ON observations(dashboard_status,observed_at);
              CREATE TABLE IF NOT EXISTS review_audit(id TEXT PRIMARY KEY,checked_at TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS sync_runs(id TEXT PRIMARY KEY,at TEXT NOT NULL,status TEXT NOT NULL,details TEXT NOT NULL);''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def record(self,job,decision,provenance='live_review'):
        events=decision.get('dashboard_events',[])
        audit_id=digest([job['url'],job.get('fingerprint'),decision.get('index')])
        valid=[];errors=[]
        for e in events:
            try:
                _shape(e,GRID_EVENT_SCHEMA)
                if not decision.get('verified') or decision.get('review_basis')!='original':raise ValueError('Original verification required')
                if not isinstance(decision.get('confidence'),(int,float)) or not math.isfinite(decision['confidence']) or not 0.8<=decision['confidence']<=1:raise ValueError('Verified dashboard evidence requires confidence >=0.8')
                if e['state'] and not re.fullmatch(r'[A-Z]{2}',e['state']):raise ValueError('US state code required')
                if len(e['new_fact'].strip())<12 or not e['asset_name'].strip():raise ValueError('Concrete asset/fact required')
                if not e['source_urls'] or any(not _http_url(u) or u not in decision['source_urls'] for u in e['source_urls']):raise ValueError('Reviewed source URLs required')
                _date(e['effective_date']);_date(decision.get('source_published_at'))
                if e['capacity'] and (not math.isfinite(e['capacity']['mw']) or e['capacity']['mw']<0):raise ValueError('Invalid MW')
                valid.append(e)
            except (ValueError,TypeError,KeyError) as exc:errors.append(str(exc))
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO review_audit VALUES(?,?,?,?)',(audit_id,now(),'included' if valid else 'needs_review' if errors else 'not_applicable',json.dumps(errors,ensure_ascii=False)))
            for e in valid:
                identity=[e['region'],e['asset_kind'],e['state'],e['queue_id'] or e['official_project_id'] or e['asset_name'].casefold().strip()]
                asset_id=digest(identity)[:24]
                event_id=digest([asset_id,e['gate'],e['new_fact'].strip(),decision.get('source_published_at'),sorted(e['source_urls'])])
                payload={**e,'id':event_id,'asset_id':asset_id,'published_at':decision.get('source_published_at'),
                         'observed_at':now(),'review_confidence':decision.get('confidence'),'provenance':provenance,
                         'telegram':{'decision':decision['action'],'status':'not_sent','receipt_id':None},
                         'dashboard':{'status':'verified_observation','queue_match':'unresolved'},
                         'candidate_url':job['url']}
                c.execute('INSERT OR IGNORE INTO observations(id,asset_id,source_url,observed_at,payload,telegram_status,dashboard_status,provenance) VALUES(?,?,?,?,?,?,?,?)',
                          (event_id,asset_id,job['url'],payload['observed_at'],json.dumps(payload,ensure_ascii=False),'not_sent','pending',provenance))
        return {'included':len(valid),'invalid':errors}
    def legacy_import(self):
        # Existing send facts are already source-reviewed. Keep them as context;
        # no heuristic permit/milestone inference and no Telegram replay.
        q=self.root/'work/v11/queue.db';count=0
        items=[]
        with closing(sqlite3.connect(q.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            c.row_factory=sqlite3.Row
            for row in c.execute("SELECT * FROM jobs WHERE result IS NOT NULL"):
                items.append((dict(row),row['result']))
        for f in (self.root/'work/v11/publications').glob('*.json'):
            try:
                p=json.loads(f.read_text(encoding='utf-8-sig'))
                if p.get('decision') and p.get('job'):items.append((p['job'],json.dumps(p['decision'])))
            except (ValueError,KeyError):continue
        for row,result in items:
                try:
                    d=json.loads(result);s=d.get('industrial_signal')
                    if d.get('dashboard_events'):count+=self.record(row,d,'stored_review')['included'];continue
                    geography=(s or {}).get('geography','')
                    if not s or not d.get('verified') or d.get('review_basis')!='original' or not re.search(r'미국|united states|\busa?\b',geography,re.I):continue
                    if d.get('sector') not in ('grid','projects'):continue
                    e={'asset_name':s['affected_market_or_entity'],'asset_kind':'unknown','region':'Unknown','state':None,'queue_id':None,'official_project_id':None,'utility':None,'gate':'unknown','status':'unknown','certainty':'confirmed','direction':'unclear','previous_fact':s['previous_fact'],'new_fact':s['new_fact'],'effective_date':None,'capacity':None,'remaining_requirements':['기존 검토자료: 프로젝트·권역·관문 개별 매핑 미완료'],'source_urls':s['evidence_urls']}
                    count+=self.record(row,{**d,'dashboard_events':[e]},'legacy_verified_context')['included']
                except (ValueError,KeyError,TypeError):continue
        return count

    def configure(self,value):
        import ctypes,base64
        from ctypes import wintypes
        from urllib.parse import urlsplit
        endpoint=urlsplit(value['url'])
        if endpoint.scheme!='https' or not endpoint.hostname or not endpoint.hostname.endswith('.chatgpt.site') or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:raise ValueError('Expected private Sites URL')
        raw=value['token'].encode('utf-8')
        if not raw:raise ValueError('Missing platform credential')
        class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]
        buffer=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)));out=Blob()
        if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source),None,None,None,None,0,ctypes.byref(out)):raise RuntimeError('Credential protection failed')
        try:encrypted=base64.b64encode(ctypes.string_at(out.data,out.size)).decode('ascii')
        finally:
            ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p];ctypes.windll.kernel32.LocalFree(out.data)
        from v11_runtime import save_json
        save_json(self.root/'work/grid-bridge/connection.json',{'url':value['url'].rstrip('/'),'protected_token':encrypted,'protection':'Windows-DPAPI-current-user','configured_at':now()})
        return {'configured':True,'credential_protection':'Windows-DPAPI-current-user'}

    def seed_mapping(self):
        mappings=json.loads((Path(__file__).with_name('seed-grid-mapping.json')).read_text(encoding='utf-8'))
        count=0
        with self.connect() as c:
            for event_id,fields in mappings.items():
                row=c.execute('SELECT payload FROM observations WHERE id=?',(event_id,)).fetchone()
                if not row:continue
                original=json.loads(row['payload']);p={'direction':'unclear',**original,**fields}
                _shape({k:p[k] for k in GRID_EVENT_SCHEMA['properties']},GRID_EVENT_SCHEMA)
                # This seed refines existing verified observations only. The
                # publication time and original before/after/source facts stay.
                p['provenance']='stored_review';p['asset_id']=digest([p['region'],p['asset_kind'],p['state'],p['queue_id'] or p['official_project_id'] or p['asset_name'].casefold().strip()])[:24]
                c.execute("UPDATE observations SET asset_id=?,payload=?,dashboard_status='pending',provenance='stored_review' WHERE id=?",(p['asset_id'],json.dumps(p,ensure_ascii=False),event_id));count+=1
        return {'mapped':count,**self.status()}
    def refresh_deliveries(self):
        db=self.root/'work/rss-news-monitor.db'
        with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as d,self.connect() as c:
            columns={r[1] for r in d.execute('PRAGMA table_info(delivery_history)')}
            for row in c.execute('SELECT id,source_url,payload FROM observations').fetchall():
                receipt=d.execute('SELECT * FROM delivery_history WHERE url=? ORDER BY rowid DESC LIMIT 1',(row['source_url'],)).fetchone()
                if not receipt:continue
                # delivery_history is populated only by receipt-verified ACK.
                names=[x[0] for x in d.execute('SELECT * FROM delivery_history LIMIT 0').description]
                proof=dict(zip(names,receipt));receipt_id=proof.get('receipt_id') or proof.get('message_sha256')
                if not receipt_id:continue
                p=json.loads(row['payload']);t={'decision':p['telegram']['decision'],'status':'delivered_ack','receipt_id':receipt_id}
                if p['telegram']!=t:
                    p['telegram']=t;c.execute("UPDATE observations SET payload=?,telegram_status='delivered_ack',dashboard_status='pending' WHERE id=?",(json.dumps(p,ensure_ascii=False),row['id']))
    def status(self):
        with self.connect() as c:
            return {'database':str(self.path),'observations':c.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
                    'outbox':dict(c.execute('SELECT dashboard_status,COUNT(*) FROM observations GROUP BY dashboard_status')),
                    'review_audit':dict(c.execute('SELECT decision,COUNT(*) FROM review_audit GROUP BY decision'))}
    def sync(self):
        self.refresh_deliveries()
        cfg=self.root/'work/grid-bridge/connection.json'
        if not cfg.exists():return {**self.status(),'status':'not_configured'}
        config=json.loads(cfg.read_text(encoding='utf-8-sig'))
        # Windows current-user DPAPI: credential never leaves memory or appears
        # in arguments/logs. Remote endpoint also requires the platform token.
        import ctypes,base64
        from ctypes import wintypes
        class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]
        raw=base64.b64decode(config['protected_token']);buffer=ctypes.create_string_buffer(raw)
        source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)));out=Blob()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,0,ctypes.byref(out)):raise RuntimeError('Bridge credential unlock failed')
        try:token=ctypes.string_at(out.data,out.size).decode('utf-8')
        finally:
            ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p];ctypes.windll.kernel32.LocalFree(out.data)
        with self.connect() as c:rows=c.execute("SELECT * FROM observations WHERE dashboard_status='pending' ORDER BY observed_at LIMIT 20").fetchall()
        if not rows:return {**self.status(),'status':'complete','uploaded':0}
        request=urllib.request.Request(config['url']+'/api/newsflow',data=json.dumps({'events':[json.loads(r['payload']) for r in rows]},ensure_ascii=False).encode(),headers={'Content-Type':'application/json','OAI-Sites-Authorization':'Bearer '+token},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=30) as response:result=json.load(response)
            accepted=set(result.get('accepted_ids',[]))
            if not accepted.issubset({r['id'] for r in rows}):raise ValueError('Unexpected ingestion ACK')
            with self.connect() as c:
                for r in rows:
                    if r['id'] in accepted:c.execute("UPDATE observations SET dashboard_status='synced',synced_at=?,attempts=attempts+1,last_error=NULL WHERE id=?",(now(),r['id']))
            return {**self.status(),'status':'complete' if len(accepted)==len(rows) else 'partial','uploaded':len(accepted)}
        except Exception as exc:
            # Never retain token-bearing HTTP headers or redirect locations.
            safe=type(exc).__name__+(': HTTP '+str(exc.code) if hasattr(exc,'code') else '')
            with self.connect() as c:
                for r in rows:c.execute('UPDATE observations SET attempts=attempts+1,last_error=? WHERE id=?',(safe,r['id']))
            raise RuntimeError('Dashboard sync failed: '+safe) from None

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['status','import-history','sync','configure','seed-mapping']);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);a=p.parse_args();b=Bridge(a.root)
    if a.command=='configure':
        import sys
        result=b.configure(json.load(sys.stdin))
    else:result=b.status() if a.command=='status' else {'imported':b.legacy_import(),**b.status()} if a.command=='import-history' else b.seed_mapping() if a.command=='seed-mapping' else b.sync()
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()

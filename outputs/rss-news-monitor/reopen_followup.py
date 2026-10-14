"""One-off authorized recent analysis reassessment; preserve prior evidence."""
import argparse,datetime as dt,json,sqlite3,time,uuid
from pathlib import Path
from v12_controls import analysis_candidate
from v11_runtime import read_json,save_json,stamp,_fresh_candidate

def run(root,apply=False):
    root=Path(root).resolve();now=time.time();q=sqlite3.connect(root/'work/v11/queue.db');q.row_factory=sqlite3.Row
    a=sqlite3.connect(root/'work/rss-news-monitor.db');a.row_factory=sqlite3.Row
    selected=[]
    for row in q.execute("SELECT * FROM jobs WHERE status='reviewed' AND result IS NOT NULL"):
        job=dict(row);d=json.loads(job['result']);c=json.loads(job['candidate'])
        if d.get('review_category')!='historical' or not analysis_candidate(c):continue
        if not _fresh_candidate(c,now,now-168*3600,168):continue
        if a.execute('SELECT 1 FROM delivery_history WHERE url=?',(job['url'],)).fetchone():continue
        # A different URL's same-event receipt is still checked by the full
        # delivery guard before actual send. Uncertain sends never enter here.
        selected.append(job)
    result={'at':stamp(),'count':len(selected),'urls':[j['url'] for j in selected],'applied':apply}
    if apply:
        audit=root/'work/followup-reassessment'/uuid.uuid4().hex
        save_json(audit/'before.json',{'jobs':selected,'articles':[dict(r) for j in selected for r in a.execute('SELECT * FROM articles WHERE url=?',(j['url'],))]})
        with q,a:
            for job in selected:
                reason='2026-10-08 승인: 최근7일 후속 분석 재검토. 기사일/근거자료일 분리, 기존 성공영수증/신규성 확인 필요.'
                q.execute("UPDATE jobs SET status='queued',result=NULL,not_before=0,reason=? WHERE url=? AND status='reviewed'",(reason,job['url']))
                # Retain old result/reason, remove only its completion-cache authority.
                q.execute("UPDATE completed_versions SET status='superseded_analysis_policy' WHERE url=? AND status='reviewed'",(job['url'],))
                q.execute('INSERT INTO events(at,url,action,detail) VALUES(?,?,?,?)',(stamp(),job['url'],'analysis_policy_reassessment',reason))
                a.execute("UPDATE articles SET status='pending',reviewed_at=NULL,last_presented_at=NULL WHERE url=? AND status='reviewed'",(job['url'],))
        save_json(audit/'result.json',result);result['audit']=str(audit)
    q.close();a.close();return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);args=p.parse_args()
    print(json.dumps(run(args.root,args.apply),ensure_ascii=False))

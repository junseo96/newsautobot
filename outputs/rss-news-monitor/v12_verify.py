"""Read-only model acceptance probe. Synthetic cases never enter the news queue."""
import argparse
import json
from pathlib import Path
from v11_runtime import codex,read_json,save_json


def probe(root):
    scripts=root/'outputs/rss-news-monitor'
    config=read_json(scripts/'runtime-v12.json')
    config={**config,'worker_web_search':'disabled'}
    cases=[
        {'id':'federal_permitting','fact':'Synthetic fixture: At the stated current time, the White House offers approval of 30 wind/solar projects held in a 300-project defense review backlog in exchange for a bipartisan federal permitting reform bill. Senate confirms negotiation framework, no final text or vote. Material transmission/renewable pipeline impact. Verified supplied primary statements; never describe as enacted.'},
        {'id':'oem_order','fact':'Synthetic fixture: US utility signs a new $400m Hitachi Energy transformer supply order today, deliveries 2027-2029. Verified original contract release, new supply commitment, no previous delivery.'},
        {'id':'tariff','fact':'Synthetic fixture: Korean regulator today approves revised large-load connection cost allocation effective next month, quantified 15% cost reallocation. Original decision verified, no previous delivery.'},
        {'id':'minor_update','fact':'Synthetic fixture: A US utility today confirms a modest new substation procurement contract and commissioning month. Verified, current and industrially relevant, explicitly less significant than immediate material changes.'},
        {'id':'architecture','fact':'Synthetic fixture: NVIDIA and a major utility publish a new 800V DC pilot measurement today: verified20% conversion-loss reduction at specified load, first utility pilot, not commercial rollout. Original report supplied, company-led trial and limits clear.'},
        {'id':'old_recap','fact':'Synthetic fixture: A new newsletter contains a July article with no changed industrial facts. Current assessment September28; original date July1.'},
        {'id':'stock_only','fact':'Synthetic fixture: Shares rose3%; analyst raised target price; article contains no new order, production, guidance, project or industrial fact.'}
    ]
    schema={'type':'object','additionalProperties':False,'required':['cases'],'properties':{'cases':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['id','action','urgency','reason'],'properties':{'id':{'type':'string'},'action':{'type':'string','enum':['send','reviewed','defer']},'urgency':{'type':'string','enum':['immediate','standard','none']},'reason':{'type':'string'}}}}}}
    prompt='Offline acceptance test of the supplied policy. All cases are synthetic and fully specified, not actual news. No tools, files, network or publishing. Treat dates stated inside each fixture as verified for that fixture. Return one short Korean classification per case; do not write full briefs.\nPOLICY\n'+(scripts/'V12-POLICY.md').read_text(encoding='utf-8')+'\nCASES\n'+json.dumps(cases,ensure_ascii=False)
    directory=root/'work/v12-upgrade/model-probe'
    result,_=codex(root,config,prompt,directory,schema=schema)
    by_id={r['id']:r for r in result['cases']}
    errors=[]
    if set(by_id)!={c['id'] for c in cases}:errors.append('Incomplete case coverage')
    for key in ('federal_permitting','oem_order','tariff','minor_update','architecture'):
        if by_id.get(key,{}).get('action')!='send':errors.append(key+' missed')
    for key in ('old_recap','stock_only'):
        if by_id.get(key,{}).get('action')!='reviewed':errors.append(key+' not excluded')
    if by_id.get('minor_update',{}).get('urgency')!='standard':errors.append('Lower-tier industrial update lost standard lane')
    report={'passed':not errors,'errors':errors,'cases':result['cases'],'execution':read_json(directory/'execution.json'),'synthetic_only':True,'telegram_sent':False}
    save_json(directory/'acceptance.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2])
    args=parser.parse_args()
    report=probe(args.root)
    print(json.dumps(report,ensure_ascii=True))
    raise SystemExit(0 if report['passed'] else 1)

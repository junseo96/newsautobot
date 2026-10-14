import json,pathlib,re,collections,hashlib,datetime
P=pathlib.Path(__file__).parent;R=P/'raw'
def dump(n,v):(P/n).write_text(json.dumps(v,ensure_ascii=False,indent=2))
rows=json.load(open(P/'spp_all_assessment_rows.json'));old=json.load(open('/workspace/scratch/5efc33d74d8e/sites/us-grid-observatory/data/projects.json'));old={x['queueId']:x for x in old if x.get('operator')=='SPP' and x.get('kind')=='load'}
# Enrichment values refer to modeled LOAD at delivery points, not contract/energization proof.
manual={
 '2350':('Sofidel — Rocky Point',45,{'Rocky Point':[45]},'2026-08-10','2028-06-01','AEP'),
 '2082':('Shale and Mica',1200,{'Shale':[363,500,775],'Mica':[40,391,425]},None,None,'Evergy'),
 '2161':('Expo',17.3,{'Expo':[9.8,12,14.2,17.3]},None,'2025-10-01','Basin Electric Power Cooperative'),
 '2193':('Resilient Tech Park / Blanchard / Bossier',1500,{'Resilient Tech Park':[500],'Blanchard Site':[500],'Bossier Site':[500]},None,'2028-09-01','AEP'),
 '2223':('Cloverleaf',375,{'Cloverleaf':[20,375]},None,'2026-12-01','GRDA'),
 '2207':('Pilot and Astra North',1200,{'Pilot':[100,600],'Astra North':[408,600]},'2026-09-09',None,'Evergy Kansas Central'),
 '2263':('Pittsburg',1600,{'Pittsburg':[600,1600]},'2026-06-04','2031-09-30','AEP'),
 '2233':('Cave 161 kV and Cave 345 kV',975,{'Cave 161 kV':[250],'Cave 345 kV':[514,725]},None,'2028-04-01','Evergy Metro'),
 '2218':('Claremore',250,{'Claremore':[250]},None,'2028-01-01','GRDA'),
 '1924':('Claremore',250,{'Claremore':[250]},None,None,'GRDA'),
 '2044':('477 — Wildwood Ranch',200,{'WWR477':[100,200]},None,'2027-07-01','Liberty Utilities (EMDE)'),
 '2060':('PCA Phase 3 — Lusk 2',70.404,{'Lusk 2':[46.48,70.404]},None,'2025-07-01','SPS'),
 '1762':('Coon Rapids',59,{'Coon Rapids':[59]},None,None,'Corn Belt Power Cooperative'),
 '1790':('Sirius',100,{'Sirius':[5,15,100]},None,None,'AEP'),
 '1856':('Blue Sky',15,{'Blue Sky':[11,12.7,15]},None,None,'Midwest Energy'),
 '1658':('Pacific',236,{'Pacific':[1.6,42.4,113,236]},None,None,'Evergy'),
 '1665':('White Deer',50,{'White Deer':[50]},None,None,'SPS'),
 '1629':('Ashby',None,{},None,'2023-12-15','SPS'),
}
# Reports attach all introduction IDs, never background-case IDs. Each source kept once by file SHA256.
man=json.load(open(R/'spp_dpns_manifest.json'));studies=[];sha={}
for m in man:
 f=pathlib.Path(m['local']);h=hashlib.sha256(f.read_bytes()).hexdigest()
 if h in sha:
  sha[h]['alsoPublishedAt'].append({'url':m['url'],'indexUrl':m['indexUrl']});continue
 s=f.with_suffix('.txt').read_text();starts=[x.start()for x in re.finditer('SECTION 1: INTRODUCTION',s)];intro=s[starts[-1]:] if starts else s
 if 'SECTION 2:' in intro:intro=intro[:intro.index('SECTION 2:')]
 # docx text was written by paragraphs first; limit preliminary intro to purpose sentence.
 if f.suffix=='.docx':intro=s[:s.find('The load flow models')]
 introjoin=re.sub(r'\s+',' ',intro).replace('DPA-2024- March','DPA-2024-March')
 ids=list(dict.fromkeys(re.findall(r'(?:DPA|DPNS)-\d{4}-[A-Za-z]+-\d+',introjoin)))
 titleid=m.get('title','')
 if f.suffix=='.docx':ids=[titleid]
 if not ids:
  hit=re.search(r'(?:DPA|DPNS)-\d{4}-[A-Za-z]+-\d+',f.name)
  if hit:ids=[hit.group()]
 # Preserve published index id when introduction has a source typo (White Deer1655 vs1665).
 if '1665' in f.name:ids=['DPA-2022-October-1665']
 bases=[]
 for q in ids:
  qq=q.replace('DPNS-','DPA-');bases.append(qq)
 key=re.search(r'-(\d+)$',bases[0]).group(1) if bases and re.search(r'-(\d+)$',bases[0]) else None
 obj={'sourceUrl':m['url'],'sourceIndexUrl':m['indexUrl'],'sourceLocalFile':m['local'],'sourceTextFile':str(f.with_suffix('.txt')),'sha256':h,'alsoPublishedAt':[],'queueIds':bases,'rawIntroductionIds':ids,'recordMeaning':'Published network/provisional/high-impact study; does not establish current pending status, executed service contract or energization.','capacityMeaning':'Modeled delivery-point load in study case; preserve case years/seasons and distinguish from net-new contracted customer demand.','sourceDateMeaning':'Original report/version date where explicitly extracted, otherwise unknown; retrieval 2026-10-03 is not event date.','retrievedAt':'2026-10-03'}
 if key in manual:
  name,mw,components,date,target,util=manual[key];obj.update({'name':name,'modeledMaximumStudyCaseLoadMW':mw,'deliveryPointModeledMWValues':components,'publicationOrVersionDate':date,'proposedInServiceDate':target,'utility':util})
 elif f.suffix=='.docx':
  aether='0004' in titleid;obj.update({'name':'Project Aether / Alpha — Clarksville' if aether else 'Quindaro','modeledMaximumStudyCaseLoadMW':816 if aether else 300,'deliveryPointModeledMWValues':{'CLRKSVL2':[18],'Clarksville Bravo':[667,798]} if aether else {'Quindaro':[300]},'publicationOrVersionDate':'2026-07-16' if aether else '2026-07-31','utility':'Clarksville Connected Utilities / Southwestern Power Administration' if aether else 'Kansas City Board of Public Utilities','industry':'data_center' if aether else None})
 else:obj.update({'name':'Multi-request cluster study','modeledMaximumStudyCaseLoadMW':None,'deliveryPointModeledMWValues':{},'publicationOrVersionDate':None,'individualQueueMWMapping':'Not assigned: multiple delivery points and requests; retain full case tables to avoid false allocation.'})
 sha[h]=obj;studies.append(obj)
dump('spp_study_evidence.json',studies)
group=collections.defaultdict(list)
for x in rows:group[x['queueId']].append(x)
normalized=[]
for q,hist in group.items():
 h=hist[0];o=old.get(q);p=dict(o) if o else {'id':'SPP::'+q,'region':'SPP','operator':'SPP','queueId':q,'name':q,'state':None,'county':None,'mw':'n.a.','target':None,'use':'미공개','constraint':'미확보','upgradeCost':'n.a.','kind':'load'}
 p.update({'stage':'GU','low':0,'high':100,'include':0,'recordType':'historical_delivery_point_assessment','asof':o.get('asof','2026-10-02') if o else '2026-10-02','date':h['dateReceived'][:10] if isinstance(h['dateReceived'],str) else None,'status':'unknown_current','rawStage':f"Published preliminary assessment: Study Required? {h['studyRequired']} (historical result; current customer stage unknown)",'source':h['sourceUrl'],'sourcePublishedAt':h['sourcePublicationDate'],'checkedAt':'2026-10-03','sourceDateMeaning':'asof = retained collection snapshot label (2026-10-02); checkedAt = 2026-10-03 retrieval; each history entry preserves source publication and received dates. No new stage/event date inferred.','capacityBasis':p.get('capacityBasis') if o and isinstance(o.get('mw'),(int,float)) else 'MW not disclosed in preliminary assessment results','note':'공개 예비평가 이력의 고유 Request ID. 현재 대기·철회·계약·통전 상태 및 수용가·업종은 미공개. Study Required NO/YES는 통전·확정접속권이나 현재 pending 증거가 아님. 신규 수용가 및 전국 수요 합계에서 제외.','assessmentHistory':[{'dateReceived':x['dateReceived'],'studyRequired':x['studyRequired'],'sourceUrl':x['sourceUrl'],'sourceIndexUrl':x['sourceIndexUrl'],'sourcePublicationDate':x['sourcePublicationDate'],'sourceSheet':x['sourceSheet'],'sourceRow':x['sourceRow'],'rawFields':x['rawFields'],'rawHeaders':x.get('rawHeaders')}for x in hist]})
 ev=[x for x in studies if q in x['queueIds']]
 if ev:
  p['studyEvidence']=ev
  if len(ev)==1 and ev[0].get('modeledMaximumStudyCaseLoadMW') is not None:
   e=ev[0];p['name']=e['name'];p['mw']=e['modeledMaximumStudyCaseLoadMW'];p['capacityBasis']='Maximum modeled delivery-point load in published study case; not confirmed net-new demand or contract MW';p['utility']=e.get('utility');p['target']=e.get('proposedInServiceDate')
 normalized.append(p)
# preserve two PLP-only records; link study evidence; unknown current customer status remains GU/include0.
for q,o in old.items():
 if q in group:continue
 p=dict(o);p.update({'stage':'GU','low':0,'high':100,'include':0,'status':'unknown_current','recordType':'published_load_study','checkedAt':'2026-10-03','sourceDateMeaning':'Retained snapshot asof; source report/version date separately in studyEvidence. Study publication does not prove current pending or energization.','studyEvidence':[x for x in studies if q in x['queueIds']]});normalized.append(p)
dump('spp_normalized_projects.json',normalized)
dump('spp_normalization_summary.json',{'assessmentIDs':len(group),'allRecordsIncludingPLPOnly':len(normalized),'historyRows':len(rows),'assessmentHistoryRowTotal':sum(len(x.get('assessmentHistory',[]))for x in normalized),'newVsExisting':len([x for x in normalized if x['queueId'] not in old]),'currentActiveLoadDenominator':None,'matchedStudyEvidenceRecords':sum(bool(x.get('studyEvidence')) for x in normalized),'numericStudyCapacityRecords':sum(isinstance(x['mw'],(int,float))for x in normalized),'uniqueStudyReports':len(studies),'unmatchedStudyIds':[q for s in studies for q in s['queueIds'] if q not in group and q not in old],'allHistoricalIncludeZero':all(x['include']==0 for x in normalized),'allCurrentStageUnknown':all(x['stage']=='GU' for x in normalized)})
print(json.loads((P/'spp_normalization_summary.json').read_text()))

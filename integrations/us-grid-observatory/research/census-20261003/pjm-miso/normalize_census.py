import json,re,collections,pathlib,datetime
ROOT=pathlib.Path(__file__).parent
PJM_URL='https://www.pjm.com/-/media/DotCom/committees-groups/committees/teac/2026/20261006/20261006-informational-only---m-3-process-needs-status.xlsx'
MISO_EVAL='https://cdn.misoenergy.org/MTEP%20Projects%20Under%20Evaluation368757.xlsx'
MISO_APPROVED='https://cdn.misoenergy.org/Appendix%20A%20Status%20Report575959.xlsx?v=20260514162226'
def norm(v):return re.sub(r'\s+',' ',str(v or '')).strip()
def mentions(text,unit):
 pat=r'(?<![\d.])([\d,]+(?:\.\d+)?)\s*'+unit+r'(?:s)?\b'
 return [dict(value=float(m[1].replace(',','')),unit=unit,excerpt=norm(text[max(0,m.start()-70):m.end()+100])) for m in re.finditer(pat,text,re.I)]
def iso(v):return v if v and re.match(r'^\d{4}-\d{2}-\d{2}$',str(v)) else None
def common(region,operator,id,name,source,asof):
 return dict(id=id,region=region,operator=operator,queueId='',name=name,state=None,county=None,mw=None,stage='GU',rawStage='Transmission planning status; customer interconnection stage unconfirmed',low=0,high=100,include=0,asof=asof,date=None,target=None,source=source,note='Transmission support record; not a unique customer interconnection queue entry. Do not sum across phases or count as pending load.',kind='load',recordType='transmission_support',capacityBasis='No verified customer requested MW',status='unconfirmed_load_status',officialNeedId=None,transmissionProjectId=None,identifierType=None,apparentMva=None,capacityQualifier=None,additive=False,checkedAt='2026-10-03',sourceFields={})
def sector(s):
 # Evidence-only keyword labels; no inferred named customer from location.
 if re.search(r'crypto|mining customer',s,re.I):return 'crypto'
 if re.search(r'data cent(?:er|re)',s,re.I) and re.search(r'ammonia',s,re.I):return 'data center + ammonia (combined)'
 if re.search(r'data cent(?:er|re)',s,re.I):return 'data center'
 if re.search(r'\bLNG\b',s):return 'LNG'
 if re.search(r'subsea cable manufacturing',s,re.I):return 'cable manufacturing'
 if re.search(r'manufacturing|industrial customer|industrial load|industrial facility',s,re.I):return 'industrial (subsector undisclosed)'
 return 'undisclosed / mixed distribution'
pjm=json.load(open(ROOT/'pjm-register-all.json'));out=[]
for ix,d in enumerate(pjm,2):
 if 'customer' not in str(d['Driver']).lower() and d['Total Expected Load (MW)'] is None:continue
 need=norm(d['Need Number']);s=norm(d['Problem Statement']);raw=d['Total Expected Load (MW)']
 x=common('PJM','PJM M-3','PJM_M3_'+re.sub(r'[^A-Za-z0-9_]','_',need),norm(d['Project Name']) or need,PJM_URL,'2026-10-01')
 x.update(officialNeedId=need,transmissionProjectId=norm(d['PJM Upgrade ID']) or None,identifierType='TO Need Number; PJM supplemental upgrade ID separately',date=iso(d['Need Meeting Date']),sector=sector(s))
 x['sourceFields']={**d,'sourceSheet':'Tracking Sheet','sourceExcelRow':ix,'MWmentions':mentions(s,'MW'),'MVAmentions':mentions(s,'MVA')}
 x['rawStage']='; '.join(f'{k}: {d[k]}' for k in ['Need Meeting Date','Solution Meeting Date','Local Plan Posting Date','Withdrawn or Cancellation Date','Status Notes'] if d[k] is not None)
 cancelled=bool(d['Withdrawn or Cancellation Date']) or bool(re.search(r'withdrawn|cancel',norm(d['Status Notes']),re.I))
 if cancelled:x['status']='withdrawn_or_cancelled_support';x['note']+=' Source records a withdrawn/cancelled need or support solution; see scope in status notes.'
 n=None
 if raw is not None and re.fullmatch(r'\d+(?:\.\d+)?',str(raw).strip()):n=float(raw)
 if n and any(abs(m['value']-n)<1e-7 for m in x['sourceFields']['MWmentions']):
  x['mw']=n;x['capacityBasis']='Explicit MW in Problem Statement matches source Total Expected Load cell; may be total, incremental, existing, or area load. This is not remaining pending MW.'
 elif n and any(abs(m['value']-n)<1e-7 for m in x['sourceFields']['MVAmentions']):
  x['apparentMva']=n;x['capacityBasis']='Source total column is labelled MW but underlying Problem Statement uses MVA; no MW conversion made.'
 elif raw is not None:x['capacityBasis']='Raw total expected-load cell retained; numeric MW not confirmed by matching explicit MW statement.'
 if x['mw'] is not None:
  # Keep qualifiers and raw contradictions visible; no aggregate uses these records.
  for m in re.finditer(r'(less than|exceeding|exceeds|at least|over|more than|greater than|in excess of|up to|approximately|approx\.?|[<>~])\s*'+re.escape(str(int(n) if n.is_integer() else n))+r'\s*MW\b',s,re.I):x['capacityQualifier']=m[1].lower()
 out.append(x)
idcounts=collections.Counter(x['id'] for x in out)
for x in out:
 if idcounts[x['id']]>1:
  x['id'] += '_ROW_'+str(x['sourceFields']['sourceExcelRow'])
  x['sourceFields']['identifierCollision']=True
  x['note']+=' Source Need Number collides with another row; row suffix is internal only. Official identifier preserved, no automatic merge.'
json.dump(out,open(ROOT/'pjm-transmission-support.json','w'),indent=2,ensure_ascii=False)
E=json.load(open(ROOT/'miso-under-evaluation-all.json'));A=json.load(open(ROOT/'miso-approved-facilities-all.json'));groups=collections.defaultdict(list)
for d in A:groups[d['MTEP Project ID']].append(d)
loadpat=r'new (?:large )?load|load (?:addition|interconnection)|data cent(?:er|re)|new .{0,50}customer|serve.{0,80}new.{0,30}load|new.{0,50}MW.{0,30}load'
by={}
for ix,d in enumerate(E,3):
 s=norm(d['Project Name'])+' '+norm(d['System Need'])+' '+norm(d['Project Description'])
 if d['Project Type']=='GIP':continue
 if d['Other Type']!='Load Growth' and not re.search(loadpat,s,re.I):continue
 id=d['MTEP Project ID'];x=common('MISO','MISO MTEP',f'MISO_MTEP_{id}',d['Project Name'],MISO_EVAL,'2026-07-31')
 x.update(transmissionProjectId=str(id),identifierType='MTEP transmission project ID; not customer queue ID',state=d['State(s)'],target=d['Expected ISD'],sector=sector(s))
 x['sourceFields']={'evaluationSource':MISO_EVAL,'evaluation':d,'evaluationSourceExcelRow':ix,'evaluationSourceSheet':'MTEP Projects Under Evaluation','MWmentions':mentions(norm(d['System Need'])+' '+norm(d['Project Description']),'MW')}
 x['rawStage']=d['Planning Status'];x['capacityBasis']='Load-support scope from MTEP Project Description/System Need; customer pending MW not confirmed.'
 by[id]=x
for id,ds in groups.items():
 s=' '.join(norm(d['Project'])+' '+norm(d['Facility Description']) for d in ds)
 if ds[0]['Project Type']=='GIP':continue
 if id not in by and not re.search(loadpat,s,re.I):continue
 if id not in by:
  x=common('MISO','MISO MTEP',f'MISO_MTEP_{id}',ds[0]['Project'],MISO_APPROVED,'2026-08-04')
  x.update(transmissionProjectId=str(id),identifierType='MTEP transmission project ID; not customer queue ID',state=ds[0]['State 1'],sector=sector(s))
  x['sourceFields']={'MWmentions':mentions(' '.join(norm(d['Facility Description']) for d in ds),'MW')}
  by[id]=x
 x=by[id];x['sourceFields']['approvedFacilities']=ds;x['sourceFields']['approvedFacilitySource']=MISO_APPROVED;x['sourceFields']['approvedAsOf']='2026-08-04'
 x['rawStage']='; '.join(sorted(set(d['Planning Status'] for d in ds)))
 x['asof']='2026-08-04';x['source']=MISO_APPROVED;x['note']+=' Facility status applies to transmission assets only; M3 Under Construction and M4 Project in Service do not establish customer G7/G8.'
 x['sourceFields']['facilityStatusCounts']=dict(collections.Counter(d['Planning Status'] for d in ds))
# Only assign carefully reviewed capacity for project descriptions where MW is explicitly tied to the load.
manual={50735:(300,'Load addition, Mogul phase 2'),50737:(1000,'Customer load addition at Elkhorn phase 2'),50738:(400,'Customer load addition at Yoshi'),50775:(620,'New requested load; CIPCO/Linn County REC interconnection'),50780:(40,'New customer load at Glencoe'),50885:(90,'Project CADC customer load addition'),51051:(50,'New total estimated load, 95% PF'),51086:(20,'New data center load at HUC Plant 2'),51092:(260,'Customer A load interconnection'),51093:(960,'Additional data center load by 2028, explicitly excludes previously modelled load'),51134:(1383,'DTE new industrial-customer load request; possible overlap with named Saline project, unlinked'),51141:(1500,'New Hobart load addition'),51142:(800,'New Schahfer load addition'),51145:(300,'New Crossroads customer load'),51148:(300,'Trail Creek load support; service status not proven'),51177:(300,'Truett temporary phase 0.5; overlaps final phases'),51178:(1000,'Truett phase 1 customer load; overlaps temporary supply'),51179:(500,'Additional Truett phase 2 customer load; may overlap temporary phase 1.5'),51195:(350,'Diamond Farms temporary customer load; overlaps final connection'),51205:(95,'New customer near Marion, Arkansas'),51207:(150,'Approximate crypto load; transmission project marked in service, customer delivery unconfirmed'),51219:(50,'Wishek NW customer requested service'),51220:(1000,'Project Cannoli DTE request; overlaps existing named Google Cannoli record'),51244:(280,'New power-electronic load at Agassiz'),51259:(370,'Additional requested load at Big Cedar; multiple substations and related support projects'),51293:(430,'Hannover customer requested load'),51300:(103,'Combined new data center and ammonia plant load; sector split unknown'),51303:(365,'Additional Mogul phase 3 load; cross-phase overlap review needed'),51307:(300,'Hackman phase 1 initial new load'),51308:(600,'Additional Hackman phase 2 load'),51312:(800,'AECC member cooperative customer requested load'),51313:(300,'Prairie Link temporary load; overlaps final connection'),51320:(500,'Truett temporary phase 1.5; overlaps final connection'),51323:(600,'Project Point temporary customer load; overlaps final connection'),51364:(300,'IPL Project Atom requested new load'),51425:(300,'Prairie Creek phase 1 new load'),51428:(150,'Pawnee temporary load; overlaps final connection'),51429:(400,'Pawnee final customer load; overlaps temporary connection'),51432:(1825,'Paducah requested new load; same load also referenced in phase 2 project 51433'),51433:(1825,'Paducah requested new load; same load also referenced in phase 1 project 51432'),50280:(27,'Project Neuron new load at Lafayette'),50289:(20,'New Wabash Industrial customer load is 20+ MW, lower-bound only')}
for id,(mw,basis) in manual.items():
 if id not in by:continue
 x=by[id];x['mw']=mw;x['capacityBasis']=basis+'; explicit MW, not pending balance.'
 if id==50289:x['capacityQualifier']='>='
 if id==51207:x['capacityQualifier']='approximately';x['status']='transmission_in_service_load_unconfirmed'
 if id in [51220,51134,51141,51142,51148,51092]:x['note']+=' Existing named-load rows may describe the same campus/customer; do not add to named-load MW.'
for id in [23266]:
 if id in by:by[id]['apparentMva']=115;by[id]['capacityBasis']='Project title states 115 MVA load; no MW conversion.'
M=list(by.values());json.dump(M,open(ROOT/'miso-transmission-support.json','w'),indent=2,ensure_ascii=False)
summary={'checkedAt':'2026-10-03','pjm':{'sourceUrl':PJM_URL,'asOf':'2026-10-01','sourceRegisterRows':len(pjm),'customerServiceDriverRows':sum('customer' in str(x['Driver']).lower() for x in pjm),'nonNullRawExpectedLoadRows':sum(x['Total Expected Load (MW)'] is not None for x in pjm),'selectedSupportRows':len(out),'filter':'Driver contains Customer Service OR non-null Total Expected Load cell. Retain all qualifying rows regardless of sector or value; not all are new large load. No arbitrary minimum-MW cutoff.','explicitMwRows':sum(x['mw'] is not None for x in out),'apparentMvaRows':sum(x['apparentMva'] is not None for x in out),'withdrawnOrCancelledSupportRows':sum(x['status']=='withdrawn_or_cancelled_support' for x in out),'ownerCounts':dict(collections.Counter(x['sourceFields']['Transmission Owner'] for x in out))},'miso':{'evaluationSource':MISO_EVAL,'evaluationAsOf':'2026-07-31','approvedSource':MISO_APPROVED,'approvedAsOf':'2026-08-04','evaluationRegisterRows':len(E),'loadGrowthClassifiedRows':sum(x['Other Type']=='Load Growth' for x in E),'approvedFacilityRows':len(A),'approvedDistinctProjectIds':len(groups),'selectedDistinctSupportProjects':len(M),'explicitMwRows':sum(x['mw'] is not None for x in M),'filter':'All Other Type Load Growth evaluation projects plus explicit load-addition/interconnection/customer-load candidates in either evaluation or approved facility descriptions; exclude GIP. Group by MTEP Project ID; retain separate phase/support projects without summing MW.','ownerCounts':dict(collections.Counter(x['sourceFields'].get('evaluation',{}).get('Submitting TO') or x['sourceFields'].get('approvedFacilities',[{}])[0].get('Submitting TO') for x in M))},'boundaries':['These are exhaustive extractions of stated source filters, not near-complete counts of all requested customer load or remaining pending MW.','PJM M-3 includes historical transmission needs, existing and transferred loads, distribution area growth, duplicate/superseded solutions, cancellations and missing customer MW. It is not a customer interconnection queue.','MISO MTEP source files cover transmission planning projects/facilities and include multiple projects serving one load, programmatic upgrades, study changes, and service states for transmission assets only.','Customer identity, sector, contracts, actual energization, remaining load and link to utility queues often remain unavailable. Missing MW remains null.','PJM source Total Expected Load (MW) label is not reliable evidence of units where Problem Statement states MVA; only exact explicit MW matches are promoted to mw.','All support rows use queueId empty, stage GU, include 0, recordType transmission_support, additive false. No summation into pending load.']}
json.dump(summary,open(ROOT/'coverage-summary.json','w'),indent=2,ensure_ascii=False)
print(json.dumps(summary,indent=2))

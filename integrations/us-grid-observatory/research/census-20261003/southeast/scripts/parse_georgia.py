"""Parse ALL public Georgia Q2 2026 large-load workbook tabs; retain original units/semantics."""
from pathlib import Path
import openpyxl,json,datetime,collections,hashlib
BASE=Path(__file__).resolve().parents[1];raw=BASE/'raw'; book=next((raw/'gpc_q2_2026').rglob('*.xlsx'))
w=openpyxl.load_workbook(book,data_only=True)
url='https://services.psc.ga.gov/api/v1/External/Public/Get/Document/DownloadFile/227753/109137'
def val(v):
 if isinstance(v,(datetime.datetime,datetime.date)):return v.isoformat()[:10]
 return v
full={s.title:[{'row':r[0].row,'values':[val(c.value) for c in r]} for r in s if any(c.value is not None for c in r)] for s in w}
(BASE/'georgia_all_workbook_rows.json').write_text(json.dumps(full,indent=2))
rows=[]
for row in w['Main']:
 a=[val(c.value) for c in row]
 if a[1]!='REDACTED':continue
 rows.append(dict(id=f'GPC_2026Q2_MAIN_R{row[0].row}',sourceRowId=f'GPC_2026Q2_MAIN_R{row[0].row:03d}',existingProjectId=f'Georgia Power::GPC_2026Q2_MAIN_R{row[0].row:03d}',name=None,nameDisclosure='redacted',row=row[0].row,region='Southeast',operator='Georgia Power',state='GA',facilityType=a[5],segment=a[6],territory=a[7],rawStage=a[8],announcedUltimateLoadMW=a[9],gridRequestMW=None,remainingUnenergizedMW=None,mwBasis='Customer-announced ultimate electrical load; includes existing/ramping and prospective loads; not firm capacity or remaining unenergized queue',initialInServiceDate=a[10],announcedAnnualLoadRampMW={str(y):a[11+y-2025] for y in range(2025,2038)},changeFlags=dict(zip(['newProject','announcedLoad','loadRamp','projectStage','initialServiceDate'],a[24:29])),asOf='2026-06-30',publishedAt='2026-08-17',checkedAt='2026-10-03',sourceUrl=url,sourceSheet='Main',officialQueueId=None,additive=False,notes=['Snapshot row ID only; no stable public project identifier.','Inside/outside refers to source territory classification; all rows are in Georgia Power economic development pipeline.','Initial date and annual ramps are customer projections, not actual energization proof.']+(['Workbook footnote: since Q2 this project has CES under Commission review; retain Q2 RFS snapshot status.'] if a[8]=='Request for Service*' else [])))
(BASE/'georgia_projects.json').write_text(json.dumps(rows,indent=2))
changes={}
for sn in w.sheetnames:
 if sn=='Main':continue
 entries=[]
 for row in w[sn]:
  a=[val(c.value) for c in row]
  if len(a)<2 or a[1]!='REDACTED':continue
  rec=dict(id=f'GPC_2026Q2_{sn.upper().replace(" ","_")}_R{row[0].row}',name=None,sourceSheet=sn,row=row[0].row,values=a,asOf='2026-06-30',publishedAt='2026-08-17',sourceUrl=url,matchedMainRow=None,additive=False)
  if sn=='Removed Projects':
   rec.update(previousAnnouncedLoadMW=a[2],rawRemovalReason=a[3],status='below_reporting_threshold' if a[3]=='See Note 1' else 'removed_from_report',reason='Project still active but load now below large-load customer threshold' if a[3]=='See Note 1' else a[3],cancelledConfirmed=False,rawStatus='removed_from_screen',include=False,sourceRowId=f'GPC_2026Q2_REMOVED_PROJECTS_R{row[0].row:03d}',sourceFields={'rawRemovalReason':a[3],'note1':'The project is still active but load is now below the large load customer threshold.' if a[3]=='See Note 1' else None})
  if sn=='Initial Service Change':rec.update(current=a[2],previous=a[3],sourceChangeMonths=a[4],timingDirection='delayed' if a[4]<0 else 'advanced')
  if sn=='Projects Added':rec.update(announcedLoadMW=a[2],createdDate=a[3],alreadyInMain=True)
  if sn=='Load Change':rec.update(currentAnnouncedLoadMW=a[2],previousAnnouncedLoadMW=a[3],deltaMW=a[4])
  if sn=='Stage Change':rec.update(currentStage=a[2],previousStage=a[3])
  entries.append(rec)
 changes[sn]=entries
(BASE/'georgia_changes.json').write_text(json.dumps(changes,indent=2))
prior=json.load(open(BASE.parents[1]/'sites/us-grid-observatory/data/projects.json'))
prior=[r for r in prior if r.get('operator')=='Georgia Power' and r.get('recordType')=='Georgia economic development pipeline']
by_id={r['queueId'].rsplit('_R',1)[0]+'_R'+str(int(r['queueId'].rsplit('_R',1)[1])):r for r in prior}; diffs=[]
for r in rows:
 p=by_id.get(r['id'])
 if not p:diffs.append({'id':r['id'],'difference':'missing prior row'});continue
 for field,new in [('mw',r['announcedUltimateLoadMW']),('use',r['segment']),('target',r['initialInServiceDate'])]:
  if p.get(field)!=new:diffs.append({'id':r['id'],'field':field,'prior':p.get(field),'new':new})
summary=dict(asOf='2026-06-30',publishedAt='2026-08-17',checkedAt='2026-10-03',latestFound=True,latestQualification='Latest report located through web docket searches; no Q3 report located by October 3. Quarterly filing lag means this is not a current-day pipeline.',sourceUrl=url,mainCount=len(rows),announcedUltimateLoadMW=sum(r['announcedUltimateLoadMW'] for r in rows),segmentCounts=dict(collections.Counter(r['segment'] for r in rows)),segmentMW={x:sum(r['announcedUltimateLoadMW'] for r in rows if r['segment']==x) for x in set(r['segment'] for r in rows)},stageCounts=dict(collections.Counter(r['rawStage'].rstrip('*') for r in rows)),stageMW={x:sum(r['announcedUltimateLoadMW'] for r in rows if r['rawStage'].rstrip('*')==x) for x in set(r['rawStage'].rstrip('*') for r in rows)},priorSiteAnonymousRows=len(prior),priorFieldDifferences=diffs,changeCounts={k:len(v) for k,v in changes.items()},removedAnnouncedMW=sum(r['previousAnnouncedLoadMW'] for r in changes['Removed Projects']),removedBelowThresholdMW=sum(r['previousAnnouncedLoadMW'] for r in changes['Removed Projects'] if r['status']=='below_reporting_threshold'),addedAnnouncedMW=sum(r['announcedLoadMW'] for r in changes['Projects Added']),netLoadChangeMW=sum(r['deltaMW'] for r in changes['Load Change']),delayedInitialServiceRows=sum(r['timingDirection']=='delayed' for r in changes['Initial Service Change']),advancedInitialServiceRows=sum(r['timingDirection']=='advanced' for r in changes['Initial Service Change']),coverage='Complete 118-row public Main sheet plus all nonblank rows in all six change tabs; neither an all-Southeast customer census nor a pure connection queue.',nameUnknownFraction=1.0,exactAnnouncedMWUnknownFraction=0,remainingUnenergizedMWUnknownFraction=1.0,largeLoadUniverse='Economic development projects above company organic growth thresholds for commercial and industrial load; threshold values not disclosed in this report. Total economic development pipeline 84,800 MW includes 4,700 MW outside large-load reported rows.',matchingCaution='Anonymous change rows are deliberately not matched to Main by MW alone. Added rows overlap Main; removed rows are historical exits, not all cancellations.',sha256=hashlib.sha256(book.read_bytes()).hexdigest())
(BASE/'georgia_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))

"""Reproduce NYISO load census using only the Python standard library."""
import collections, datetime as dt, json, re, zipfile, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path('/workspace/scratch/5efc33d74d8e/sites/us-grid-observatory/data/projects.json')
URL = 'https://www.nyiso.com/documents/20142/1407078/NYISO-Interconnection-Queue.xlsx'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
z = zipfile.ZipFile(ROOT / 'nyiso-queue.xlsx')
strings = [''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
def rows(file):
    result=[]
    for node in ET.fromstring(z.read(file)).findall('m:sheetData/m:row', NS):
        row={}
        for cell in node.findall('m:c', NS):
            v=cell.find('m:v', NS)
            if v is not None:
                row[re.sub(r'\d','',cell.get('r'))] = strings[int(v.text)] if cell.get('t')=='s' else v.text
        if row: result.append((int(node.get('r')),row))
    return result

data=rows('xl/worksheets/sheet4.xml')
headers=data[0][1]
raw=[{'sourceRow':n,'fields':{h:r.get(col) for col,h in headers.items()}} for n,r in data[1:] if r.get('G')=='Load Interconnection' and r.get('A')]
legend={
 '0':'Withdrawn','1':'Scoping Meeting Pending','2':'FES Pending','3':'FES in Progress','3A':'FES Approved/Performed',
 '4':'SRIS/SIS Pending','5':'SRIS/SIS in Progress','5P':'SRIS Commenced, Stopped and Pending Adoption of IP',
 '6':'SRIS/SIS Approved','7':'FS Pending','8':'Rejected Cost Allocation/Next FS Pending','9':'FS in Progress',
 '10':'Accepted Cost Allocation/IA in Progress','11':'IA Completed','12':'Under Construction',
 '13':'In Service for Test','14':'In Service Commercial','15':'Partial In-Service','P':'Pending Adoption of IP Compliance with Order 2023'
}
enduse={'DAT':'Data Center','DAT-AI':'AI Data center','DAT-CM':'Cryptocurrency mining data center','M':'Manufacturing','M-CH':'Microchip fabrication','M-CG':'Consumable Goods','M-IN':'Industrial Goods','RD':'Research and Development','HP':'Hydrogen Production','O':'Other'}
industry={'DAT':'data_center','DAT-AI':'ai_data_center','DAT-CM':'cryptocurrency_mining','M':'manufacturing','M-CH':'semiconductor','M-CG':'consumer_goods','M-IN':'industrial_goods','RD':'research_and_development','HP':'hydrogen','O':'other'}
stages={'0':'W','1':'G1','2':'G2','3':'G2','3A':'G2','4':'G2','5':'G3','5P':'GS','6':'G4','7':'G4','8':'G4','9':'G4','10':'G5','11':'G6','12':'G7','13':'G8','14':'G8','15':'GU','P':'GU'}
base={str(r['queueId']):r for r in json.loads(BASE.read_text()) if r.get('region')=='NYISO' and r.get('kind')=='load'}
def serial(v):
    # A source error contains status code 14 in date column; retain raw and never turn it into 1900-01-13.
    if not v or not v.replace('.','',1).isdigit() or float(v)<30000 or float(v)>60000: return None
    return (dt.datetime(1899,12,30)+dt.timedelta(days=float(v))).date().isoformat()

normalized=[];changes=[]
for record in raw:
    r=record['fields']; q=r['Queue Number']; old=base.get(q,{})
    code=r['Project Status #']; eu=r['End-Use']; mw=float(r['Peak MW load'])
    obj=dict(old)
    obj.update({'id':'NYISO::'+q,'region':'NYISO','operator':'NYISO','kind':'load','queueId':q,'name':r['Project: Project Name'],
      'mw':mw,'rawStatusCode':code,'rawStage':legend.get(code,'Unknown code '+str(code)),
      'stage':stages.get(code,'GU'),'use':enduse.get(eu,'미공개' if eu is None else eu),'endUseRaw':eu,
      'industry':industry.get(eu,'undisclosed'),'industryBasis':'NYISO published End-Use code; no inference from company/project name',
      'developer':r['Developer Name'],'utility':r['CTO/Utility'],'affectedTransmissionOwner':r['Affected Transmission Owner (ATO)'],
      'pointOfInterconnection':r['Points of Interconnection'],'zone':r['NYISO Zone'],'sisBundle':r['SIS Bundle'],
      'stateRaw':r['State'],'countyRaw':r['County'],'sourceFields':r,'sourceRow':record['sourceRow'],
      'sourceSheet':'Load Projects','source':URL,'checkedAt':'2026-10-03','sourcePublishedAt':None,
      'sourceDateEvidence':{'httpLastModified':'2026-09-11T17:26:02Z','xlsxCoreModified':'2026-09-11T13:13:13Z','rowLastUpdatedRaw':r['Last Updated Date'],'rowLastUpdated':serial(r['Last Updated Date'])},
      'dateMeaning':'Existing asof is preserved as prior collection date. HTTP/XLSX modification metadata says Sep11, but maximum row Last Updated Date is Sep30; metadata is not a reliable single effective date.',
      'date':serial(r['IR Submission Date']),'targetRaw':r['Proposed Initial Backfeed Date'],'iaTenderDate':serial(r['IA Tender Date']),
      'facilitiesStudyCompletionDate':serial(r['FS Completion Date']),'studiesAvailable':r['Availability of Studies'],
      'coverageScope':'Complete published NYISO Load Projects worksheet; no claim to cover all retail/distribution/behind-the-meter customer requests',
      'rawDateQualityFlag':'Invalid Excel date; source preserved' if r['Last Updated Date'] and serial(r['Last Updated Date']) is None else None})
    if code=='4':obj['stageMappingNote']='SRIS/SIS Pending remains G2. A pending study is not a study in progress.'
    normalized.append(obj)
    if old:
        for k in ('name','mw','stage','date'):
            if old.get(k)!=obj.get(k):changes.append({'queueId':q,'field':k,'old':old.get(k),'new':obj.get(k)})

active=[r for r in normalized if r['rawStatusCode'] not in ('0','14')]
def tallies(seq,key):
    d={}
    for r in seq:
        k=r.get(key) or 'undisclosed';x=d.setdefault(k,{'count':0,'mw':0});x['count']+=1;x['mw']=round(x['mw']+r['mw'],8)
    return d
summary={'source':URL,'checkedAt':'2026-10-03','sourceModifiedAt':'2026-09-11','publishedRows':len(raw),'existingRows':len(base),
 'addedQueueIds':sorted(set(r['queueId'] for r in normalized)-set(base)),'removedQueueIds':sorted(set(base)-set(r['queueId'] for r in normalized)),
 'changedCoreFields':changes,'activeRows':len(active),'activeMW':round(sum(r['mw'] for r in active),8),
 'statusTotals':tallies(normalized,'rawStatusCode'),'allEndUseTotals':tallies(normalized,'endUseRaw'),'activeEndUseTotals':tallies(active,'endUseRaw'),
 'sourceRowUpdateMin':min(r['sourceDateEvidence']['rowLastUpdated'] for r in normalized if r['sourceDateEvidence']['rowLastUpdated']),
 'sourceRowUpdateMax':max(r['sourceDateEvidence']['rowLastUpdated'] for r in normalized if r['sourceDateEvidence']['rowLastUpdated']),
 'rawDateAnomalies':[r['queueId'] for r in normalized if r['rawDateQualityFlag']],
 'enrichmentCount':len(normalized),'knownEndUseCount':sum(r['endUseRaw'] is not None for r in normalized),
 'changedUseLabelCount':sum(r.get('use')!=base.get(r['queueId'],{}).get('use') for r in normalized),
 'changedRawStageLabelCount':sum(r.get('rawStage')!=base.get(r['queueId'],{}).get('rawStage') for r in normalized),
 'rawStageLabelChangeMeaning':'46 display labels expanded from tracking-sheet shorthand to the Load Projects official legend; this is metadata normalization, not46 lifecycle transitions. Underlying source codes and normalized G stages unchanged.',
 'coverageDenominator':{'known':74,'definition':'All rows marked Load Interconnection with a Queue Number in the current official Load Projects sheet, including alphanumeric 0290A, all statuses/end uses and no MW cutoff','nationalOrRetailCustomerUniverse':None},
 'dateWarning':'XLSX core modified and HTTP Last-Modified both Sep11, but latest project Last Updated Date is Sep30. Do not downgrade existing Oct2 collection asof or claim Sep11 represents all contents.',
 'trackingWarnings':[{'cell':'Load Project Tracking!O14','sourceCachedMW':14473.1,'rowRecalculatedActiveMW':14232.9}, {'cell':'Load Project Tracking!O53','sourceCachedMW':13611.9,'rowRecalculatedActiveMW':14232.9,'reason':'621 MW of active requests have blank published End-Use: Micron Fab 3 (606 MW), Kilbourne Graphite Concentrator Plant (15 MW)'}]}
notes=[{'sourceRow':n,'fields':r} for n,r in data if n>=77]
for name,obj in [('nyiso-load-raw-rows.json',{'headers':list(headers.values()),'records':raw}),('nyiso-official-legends.json',{'status':legend,'endUse':enduse,'verbatimWorksheetNotes':notes}),('nyiso-normalized-enrichment.json',normalized),('nyiso-comparison-summary.json',summary)]:
    (ROOT/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))

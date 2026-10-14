"""Read public CPUC XLSX without editing it. Keep original columns and cell values.
Selection is a research scope rule, not a legal definition of large load:
requested site capacity >= 10,000 kW OR explicit industrial/large-load class.
Rows with redacted capacity remain capacity-unknown candidates, not >=10 MW.
Original public files preserve all unselected rows and formatting.
"""
import collections, datetime, hashlib, json, pathlib, re, zipfile
import xml.etree.ElementTree as ET

ROOT=pathlib.Path(__file__).parent
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
CHECKED='2026-10-03'
SOURCES={
 'pge-september-2025-biannual-energization-data-report_20250930.xlsx':dict(utility='PG&E',publishedAt='2025-09-30',asOf='2025-06-30',url='https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/infrastructure/energization/pge-september-2025-biannual-energization-data-report_20250930.xlsx'),
 'sdge-march-2026.xlsx':dict(utility='SDG&E',publishedAt='2026-04-01',asOf='2025-12-31',url='https://www.sdge.com/sites/default/files/regulatory/Public%20Attachment%20B%20Energization%20Report%203.31.26.xlsx'),
 'scepubliceet-september-2025-report20250930ver2.xlsx':dict(utility='SCE',publishedAt='2025-09-30',asOf='2025-06-30',url='https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/infrastructure/energization/scepubliceet-september-2025-report20250930ver2.xlsx'),
}

def extract(p):
 z=zipfile.ZipFile(p)
 ss=[]
 if 'xl/sharedStrings.xml' in z.namelist():
  ss=[''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
 rel={r.attrib['Id']:r.attrib['Target'].lstrip('/') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
 styles=ET.fromstring(z.read('xl/styles.xml'))
 custom={int(f.attrib['numFmtId']):f.attrib['formatCode'] for f in styles.findall('s:numFmts/s:numFmt',NS)}
 xfs=styles.findall('s:cellXfs/s:xf',NS)
 for sh in ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',NS):
  path=rel[sh.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
  if not path.startswith('xl/'):path='xl/'+path
  root=ET.fromstring(z.read(path));rows=[]
  for r in root.findall('s:sheetData/s:row',NS):
   cells={}
   for c in r:
    col=re.sub(r'\d','',c.attrib['r']);v=c.find('s:v',NS);t=c.attrib.get('t');raw=v.text if v is not None else None
    if t=='s' and raw is not None:value=ss[int(raw)]
    elif t=='inlineStr':value=''.join(c.find('s:is',NS).itertext())
    else:value=raw
    if value is None:continue
    fmt=int(xfs[int(c.attrib.get('s',0))].attrib.get('numFmtId',0))
    item={'value':value,'cellType':t or 'n','numberFormatId':fmt}
    if fmt in custom:item['numberFormat']=custom[fmt]
    if t not in ('s','inlineStr') and raw:
     try:
      n=float(raw);item['numericValue']=n
      # Dates are decoded only if the source style actually identifies them.
      f=custom.get(fmt,'').lower()
      if fmt in range(14,23) or (('yy' in f or 'dd' in f) and not re.search('[0#].*[ymd]',f)):
       item['isoDate']=(datetime.datetime(1899,12,30)+datetime.timedelta(days=n)).date().isoformat()
     except (ValueError,OverflowError):pass
    formula=c.find('s:f',NS)
    if formula is not None:item['formula']=formula.text
    cells[col]=item
   rows.append({'excelRow':int(r.attrib['r']),'cells':cells})
  yield sh.attrib['name'],rows

def main():
 selected=[];excluded=[];summary=[]
 for filename,source in SOURCES.items():
  p=ROOT/'raw'/filename
  if not p.exists() or not p.stat().st_size:continue
  s={**source,'filename':filename,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'checkedAt':CHECKED,'sheets':[]}
  for name,rows in extract(p):
   header=next((r for r in rows if 'Project Identifier #' in str(r['cells'].get('A',{}).get('value',''))),None)
   if header is None:continue
   headers={k:v['value'] for k,v in header['cells'].items()}
   data=[r for r in rows if r['excelRow']>header['excelRow'] and len(r['cells'])>1]
   stats={'sheet':name,'headerRow':header['excelRow'],'rowCount':len(data),'headers':headers,'selectedCount':0}
   if 'tariff' in name.lower():
    stats['classCounts']=dict(collections.Counter(r['cells'].get('E',{}).get('value') for r in data))
    stats['requestedCapacityBlankCount']=sum(r['cells'].get('J',{}).get('value') in (None,'') for r in data)
    stats['publicProjectIdentifierCount']=sum(r['cells'].get('A',{}).get('value') not in (None,'') for r in data)
    for r in data:
     cells=r['cells'];cls=str(cells.get('E',{}).get('value',''));kw=cells.get('J',{}).get('numericValue')
     if kw is None:
      try:kw=float(str(cells.get('J',{}).get('value','')).replace(',',''))
      except ValueError:pass
     reasons=[]
     if kw is not None and kw>=10000:reasons.append('published_requested_site_capacity_at_least_10000_kW')
     if re.search(r'industrial|large.load',cls,re.I):reasons.append('explicit_industrial_or_large_load_class_capacity_may_be_undisclosed')
     if not reasons:continue
     if 'residential' in cls.lower():
      excluded.append({**source,'sheet':name,**r,'reasons':['Residential end-use excluded from high-load nonresidential census; raw large number alone is not reliable evidence of high load.'],'rawRequestedKW':cells.get('J',{}).get('value')})
      continue
     status='cancelled_or_rejected' if re.search('cancel|reject',name,re.I) else ('ongoing' if re.search('progress|flight|ongoing',name,re.I) else 'energized_or_closed')
     selected.append({**source,'checkedAt':CHECKED,'sourceFilename':filename,'sourceSheet':name,'sourceExcelRow':r['excelRow'],'sourceHeaders':headers,'sourceCells':cells,'utilityProjectId':cells.get('A',{}).get('value'),'endUseClass':cls,'requestedCapacity':{'value':kw,'unit':'kW','basis':'Total Site Capacity Requested; undiversified customer intake figure; not a confirmed utility capacity allocation'} if kw is not None else None,'stageFromSourceTab':status,'selectionReasons':reasons,'qualityFlags':['Public project identifier absent; row identity is workbook/sheet/row only'] if not cells.get('A',{}).get('value') else [],'additive':False})
     if source['utility']=='SDG&E':selected[-1]['qualityFlags'].append('SDG&E March 2026 narrative warns intake kW can be inflated or mistaken amperes and not updated after formal load study. Do not sum or treat as validated load.')
     stats['selectedCount']+=1
   s['sheets'].append(stats)
  summary.append(s)
 (ROOT/'energization-selected-rows.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2))
 (ROOT/'energization-excluded-residential-anomalies.json').write_text(json.dumps(excluded,ensure_ascii=False,indent=2))
 normalized=[]
 for r in selected:
  pge=r['utility']=='PG&E';active=r['stageFromSourceTab']=='ongoing';cancel=r['stageFromSourceTab']=='cancelled_or_rejected'
  official_id=r['utilityProjectId'];synthetic=f"{r['sourceSheet']}::row{r['sourceExcelRow']}"
  stage='W' if cancel else ('G8' if pge and not active else 'GU')
  def source_date(needle):
   col=next((k for k,v in r['sourceHeaders'].items() if needle in v),None);cell=r['sourceCells'].get(col,{})
   if 'isoDate' in cell:return cell['isoDate']
   try:
    n=float(cell.get('value',''))
    return (datetime.date(1899,12,30)+datetime.timedelta(days=n)).isoformat() if 35000<n<60000 else None
   except ValueError:return None
  normalized.append({'id':f"{r['utility']}::energization::{r['asOf']}::{official_id or synthetic}",'region':'CAISO','operator':r['utility'],'queueId':official_id,'name':f"{r['utility']} {r['endUseClass']} service request {official_id or synthetic}",'state':'CA','county':None,'mw':None,'gridRequestMW':None,'rawRequestedKW':r['sourceCells'].get('J',{}).get('value'),'rawStage':r['sourceSheet'],'stage':stage,'low':'n.a.','high':'n.a.','include':1 if active else 0,'recordType':'service_request_capacity_undisclosed' if pge else 'service_request_unvalidated','identifierType':'공식 서비스 신청 ID·송전 큐 ID 아님' if pge else '공시 스냅샷 행번호·공식큐ID미공개','asof':r['asOf'],'publishedAt':r['publishedAt'],'checkedAt':r['checkedAt'],'date':source_date('1) Intake Start Date'),'target':None,'use':'산업용·세부업종 미공개' if pge else '미공개·미분류','industry':'산업용·세부업종 미공개' if pge else '미공개·미분류','source':r['url'],'sourceFile':r['sourceFilename'],'sourceSheet':r['sourceSheet'],'sourceExcelRow':r['sourceExcelRow'],'sourceFields':{label:{**r['sourceCells'].get(k,{'value':None,'cellAbsent':True}),'sourceColumn':k} for k,label in r['sourceHeaders'].items()},'note':'산업용 원문 분류로 선별; 고객명·용량 비공개. 2025-06-30 스냅샷이며 2026 후속 XLSX 미확보.' if pge else 'Commercial은 산업 제조업을 뜻하지 않음. 최초 신청 kW 오기·amperes 혼입 위험을 유틸리티가 명시; 검증된 MW로 표시·합산 금지. Tariff Closed는 서비스 절차 종료이며 전체 부지 상업가동 확인 아님.','status':'active' if active else ('withdrawn' if cancel else ('energized' if pge else 'closed')),'constraint':'미확보','upgradeCost':'n.a.','capacityBasis':'용량 비공개' if pge else '미검증 고객 최초 신청 kW; MW 수치화 금지','kind':'load','additive':False,'recordIsUniqueCustomer':False,'stageEvidenceUrl':'https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/infrastructure/energization/pge-biannual-energization-report-public_20250930.pdf' if pge else 'https://docs.cpuc.ca.gov/PublishedDocs/Efile/G000/M603/K533/603533572.PDF','stageEvidenceLocation':'PDF pages 5–6: energized through 2025-06-30; later completions moved back to in-progress' if pge else 'PDF pages 7–8: reporting parameters; Step 8 may mean transformer set/ready for service or first meter set','serviceEnergizationEndDate':source_date('9) Service Energization End')})
 (ROOT/'normalized-projects.json').write_text(json.dumps(normalized,ensure_ascii=False,indent=2))
 (ROOT/'energization-inventory.json').write_text(json.dumps({'checkedAt':CHECKED,'scopeRule':'Tariff requested site capacity >=10000 kW or explicit industrial/large-load class; not a national regulatory threshold. No MVA-to-MW conversion. Not all selected industrial rows have confirmed >=10 MW. MPU excluded.','sources':summary},ensure_ascii=False,indent=2))
 print(json.dumps({'selectedRows':len(selected),'byUtilityStage':dict(collections.Counter((r['utility']+' | '+r['stageFromSourceTab']) for r in selected)),'numericCapacityRangeKW': [min([r['requestedCapacity']['value'] for r in selected if r['requestedCapacity']] or [0]),max([r['requestedCapacity']['value'] for r in selected if r['requestedCapacity']] or [0])]},indent=2))

if __name__=='__main__':main()

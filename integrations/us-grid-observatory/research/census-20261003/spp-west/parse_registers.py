import json,pathlib,datetime,re,collections,openpyxl,xlrd,hashlib
P=pathlib.Path(__file__).parent
RAW=P/'raw'
def clean(v):
 if isinstance(v,(datetime.datetime,datetime.date)):return v.isoformat()
 return v.strip() if isinstance(v,str) else v
def dump(n,v):(P/n).write_text(json.dumps(v,ensure_ascii=False,indent=2))
def wb_rows(fn):
 if fn.endswith('.xlsx'):
  w=openpyxl.load_workbook(fn,data_only=True)
  return [(s.title,[(i,[clean(v) for v in r]) for i,r in enumerate(s.values,1)]) for s in w]
 w=xlrd.open_workbook(fn);out=[]
 for s in w.sheets():
  rows=[]
  for i in range(s.nrows):
   v=[]
   for c in s.row(i):
    v.append(clean(xlrd.xldate_as_datetime(c.value,w.datemode)) if c.ctype==xlrd.XL_CELL_DATE else clean(c.value))
   rows.append((i+1,v))
  out.append((s.name,rows))
 return out
manifest=json.load(open(RAW/'spp_archive_manifest.json'));spp=[];issues=[];stats=[]
for m in manifest:
 fn=m['local']
 if not fn.endswith(('.xlsx','.xls')):continue
 count=0
 for sheet,rows in wb_rows(fn):
  header=[]
  for n,vals in rows:
   if any(isinstance(v,str) and v.lower()=='request number' for v in vals):header=vals
   # preserve all data rows whose cells contain a DPA request ID (earlier sheets use offset columns)
   hits=[(i,v) for i,v in enumerate(vals) if isinstance(v,str) and re.match(r'^DPA\s*-',v,re.I)]
   if hits:
    c,q=hits[0];datecols=[i for i,h in enumerate(header) if isinstance(h,str) and 'receiv' in h.lower()];studycols=[i for i,h in enumerate(header) if isinstance(h,str) and 'study required' in h.lower()];date=vals[datecols[0]] if datecols else (vals[c+1] if len(vals)>c+1 else None);study=vals[studycols[0]] if studycols else (vals[c+2] if len(vals)>c+2 else None)
    spp.append({'queueId':q,'operator':'SPP','recordType':'historical_delivery_point_assessment_result','assessmentYear':int(m['year']),'sourceUrl':m['url'],'sourceIndexUrl':m['indexUrl'],'sourcePublicationDate':m['indexRow'][3] if len(m['indexRow'])>3 else None,'sourceSheet':sheet,'sourceRow':n,'rawFields':vals,'rawHeaders':header,'dateReceived':date,'studyRequired':study,'mw':None,'customer':None,'industry':None,'currentStatus':'not_disclosed','isActiveLoadStock':False,'retrievedAt':'2026-10-03','localSource':fn});count+=1
 stats.append({'file':fn,'year':m['year'],'rows':count})
 if count==0:issues.append({'file':fn,'rows':wb_rows(fn)})
dump('spp_all_assessment_rows.json',spp);dump('spp_parse_empty_workbooks.json',issues)
by=collections.Counter(x['assessmentYear'] for x in spp);dup={k:v for k,v in collections.Counter(x['queueId'] for x in spp).items() if v>1}
dump('spp_archive_summary.json',{'allRows':len(spp),'distinctRawIds':len(set(x['queueId'] for x in spp)),'countByAssessmentYear':dict(sorted(by.items())),'duplicateRawIds':dup,'files':stats,'scope':'All 199 preliminary-assessment spreadsheets published under SPP 2010–2026 Delivery Point Assessment index; one 2010 example DOC retained separately. Historical results, not an active load queue. Customer, MW and industry generally not columns. Date coverage varies with publication; current 2026 through September.','coverageDenominator':{'publishedFiles':199,'parsedFiles':199,'activeLoadQueueDenominator':None}})
# BPA exact LL slice and conservative description classifications.
w=openpyxl.load_workbook(RAW/'bpa_queue.xlsx',data_only=True).active;rows=list(w.values);headers=rows[5];bpa=[]
industry_patterns=[('data_center',r'data\s*(?:center|server|storage)|server\s*farm|\bPDX1&4\b'),('mining',r'\bmine\b|\bmining\b|Lithium Nevada'),('hydrogen',r'hydrogen|\bH2\b'),('semiconductor',r'semiconductor'),('steel_metals',r'steel|arc furnace|metal recycling'),('paper_packaging',r'corrugated|fiber'),('refining_fuels',r'refinery|biodiesel|ethanol|\bLNG\b|RNG|pipeline'),('crypto_blockchain',r'blockchain|\bBTC\b'),('industrial_unspecified',r'industrial|furnace|mill')]
for rownum,r in enumerate(rows[6:],7):
 if r[4]!='LL':continue
 raw={headers[i] or f'Unnamed_{i+1}':clean(v) for i,v in enumerate(r)};name=r[2] or '';notes=r[11] or '';text=name+' '+notes
 industries=[k for k,pat in industry_patterns if re.search(pat,name,re.I)]
 has_load=bool(re.search(r'\bloads?\b|data\s*(?:center|server|storage)|server\s*farm|semiconductor|hydrogen|\bH2\b|\bmine\b|\bmining\b|refinery|biodiesel|ethanol|\bRNG\b|steel|furnace|blockchain|metal recycling',name,re.I))
 has_line=bool(re.search(r'\bline\b|\btransmission\b|\bHVDC\b|\bloop\b|\bintertie\b|terminal|breaker|reliability|reinforcement',name,re.I))
 if has_load and has_line:cls='explicit_load_and_network_description'
 elif has_load:cls='explicit_load_description'
 elif has_line:cls='network_description_load_purpose_unconfirmed'
 else:cls='unspecified_line_or_load'
 # only call line-only where document explicitly describes a merchant/HVDC transmission project without load language
 line_only=bool(not has_load and re.search(r'merchant.*(?:line|transmission)|HVDC',name,re.I))
 if line_only:cls='explicit_line_only_description'
 bpa.append({'queueId':r[0],'operator':'BPA','sourceUrl':'https://www.bpa.gov/-/media/Aep/transmission-media-documents/InterconnectionQueueOutput.xlsx','sourceTimestamp':clean(rows[0][8]),'sourceSheet':'Sheet1','sourceRow':rownum,'retrievedAt':'2026-10-03','name':name,'requestor':r[3],'sourceConnectionType':r[4],'classification':cls,'classificationBasis':'Literal Project Name and Comments only; network description alone does not prove no customer load. Industry label uses explicit name terms; unidentified projects remain unknown.','industryTags':industries,'rawStatus':r[12],'summerServiceMW':r[15] if isinstance(r[15],(float,int)) else None,'winterServiceMW':r[16] if isinstance(r[16],(float,int)) else None,'requestDate':clean(r[1]),'requestedInServiceDate':clean(r[13]),'agreedToDate':clean(r[14]),'nationalLoadAdditive':False,'rawFields':raw})
dump('bpa_all_ll_rows.json',bpa)
dump('bpa_summary.json',{'rowCount':len(bpa),'rawStatusCounts':dict(collections.Counter(x['rawStatus'] for x in bpa)),'classificationCounts':dict(collections.Counter(x['classification'] for x in bpa)),'industryTagCounts':dict(collections.Counter(k for x in bpa for k in x['industryTags'])),'missingSummerServiceMW':sum(x['summerServiceMW'] is None for x in bpa),'missingWinterServiceMW':sum(x['winterServiceMW'] is None for x in bpa),'sourceTimestamp':clean(rows[0][8]),'coverageDenominator':{'allPublishedLLRows':458,'allNewLargeLoadCustomers':None},'scope':'All BPA Connection Type LL rows including historical energized, withdrawn, line, mixed network/load and unspecified purpose. Summer/Winter Interconnection Service MW are preserved, not recast as net-new requested load.'})
old=json.load(open('/workspace/scratch/5efc33d74d8e/sites/us-grid-observatory/data/projects.json'));oldids={x['queueId'] for x in old if x.get('operator')=='SPP' and x.get('kind')=='load'}
new=[x for x in spp if x['assessmentYear']==2026 and x['queueId'] not in oldids]
dump('spp_2026_new_rows.json',new)
oldb={x['queueId']:x for x in old if x.get('operator')=='BPA' and x.get('kind')=='load'}
changes=[]
for x in bpa:
 o=oldb.get(x['queueId'])
 if not o:changes.append({'queueId':x['queueId'],'change':'new'})
 else:
  for k,ok in [('rawStatus','rawStage'),('summerServiceMW','mw'),('name','name')]:
   ov=o.get(ok);nv=x[k]
   if ov=='n.a.':ov=None
   if ov!=nv:changes.append({'queueId':x['queueId'],'field':k,'old':ov,'new':nv})
dump('bpa_changes_from_site.json',changes)
print('SPP',len(spp),'unique raw IDs',len(set(x['queueId'] for x in spp)),'2026 new',len(new),'year counts',dict(by),'emptyfiles',len(issues),'duplicates',dup)
print('BPA classes',collections.Counter(x['classification'] for x in bpa),'changes',changes)

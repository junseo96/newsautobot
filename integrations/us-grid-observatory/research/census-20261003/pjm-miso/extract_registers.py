import openpyxl,pathlib,json,datetime,collections,re
root=pathlib.Path(__file__).parent;raw=root/'raw'
def clean(v):return v.isoformat()[:10] if isinstance(v,(datetime.date,datetime.datetime)) else v
for filename,headerrow,outname in [('20261006-informational-only---m-3-process-needs-status.xlsx',1,'pjm-register-all'),('MTEP Projects Under Evaluation368757.xlsx',2,'miso-under-evaluation-all'),('Appendix A Status Report575959.xlsx',3,'miso-approved-facilities-all')]:
 s=openpyxl.load_workbook(raw/filename,read_only=True,data_only=True).worksheets[0]
 rows=list(s.values);heads=[str(x).replace('\n',' ').strip() for x in rows[headerrow-1]]
 data=[{k:clean(v) for k,v in zip(heads,row)} for row in rows[headerrow:] if row[0] is not None]
 json.dump(data,open(root/(outname+'.json'),'w'),indent=2)
 print(outname,len(data),heads)
 if outname.startswith('pjm'):
  print('Drivers',collections.Counter(str(d.get('Driver')) for d in data))
  selected=[d for d in data if d.get('Total Expected Load (MW)') is not None]
  print('non-null MW',len(selected));print('owners',collections.Counter(d['Transmission Owner'] for d in selected))
  json.dump(selected,open(root/'pjm-register-load-mw.json','w'),indent=2)
 elif 'evaluation' in outname:
  print('Other Types',collections.Counter(str(d['Other Type']) for d in data))
  selected=[d for d in data if re.search(r'load|customer',str(d['Other Type'])+' '+str(d['System Need'])+' '+str(d['Project Name']),re.I)]
  json.dump(selected,open(root/'miso-under-evaluation-load-candidates.json','w'),indent=2)
  print('Load candidate projects',len(selected))

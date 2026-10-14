"""Read public EIA-930 observations, no credentials; emit ingest-live payloads."""
import datetime,json,sys,urllib.parse,urllib.request
IDS=['US48','ERCO','CISO','PJM','MISO','SWPP','SWPW','ISNE','NYIS','BPAT','SOCO','DUK','TVA','FPL','PACE','PACW','AZPS','NEVP']
now=datetime.datetime.now(datetime.timezone.utc)
def read(fuel):
 q={f'respondent[{i}]':v for i,v in enumerate(IDS)}
 q.update(frequency='hourly',start=(now-datetime.timedelta(days=3)).strftime('%m%d%Y 00:00:00'),end=(now+datetime.timedelta(days=1)).strftime('%m%d%Y 00:00:00'),timezone='UTC',limit='50000')
 q['type[0]']='NG' if fuel else 'D'
 url='https://www.eia.gov/electricity/930-api/'+('region_data_by_fuel_type/data' if fuel else 'region_data/data')+'?'+urllib.parse.urlencode(q)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'USGridResearch/1.0'}),timeout=45) as r:obj=json.load(r)
 data=obj[0]['data']
 if not data:raise ValueError('Empty EIA observations; preserve prior dataset')
 return data

def iso(t):return datetime.datetime.strptime(t,'%m/%d/%Y %H:%M:%S').isoformat()+'Z'
names={'COL':'Coal','NG':'Natural Gas','NUC':'Nuclear','WAT':'Hydro','WND':'Wind','SUN':'Solar','OTH':'Other','OIL':'Petroleum','BAT':'Battery Storage','OES':'Other energy storage','PS':'Pumped storage'}
demand=read(False);fuel=read(True);payloads=[]
for key in IDS:
 d=sorted([r for r in demand if r['RESPONDENT_ID']==key and isinstance(r.get('VAL'),(int,float))],key=lambda r:iso(r['TIMESTAMP_']))
 f=[r for r in fuel if r['RESPONDENT_ID']==key and isinstance(r.get('VAL'),(int,float))]
 if not d or not f:continue
 ft=max(iso(r['TIMESTAMP_']) for r in f);mix=[dict(fuel=names.get(r['FUEL_TYPE_ID'],r['FUEL_TYPE_NAME']),gw=r['VAL']/1000) for r in f if iso(r['TIMESTAMP_'])==ft]
 payloads.append({'action':'ingest-live','data':dict(id=key,name=d[-1]['RESPONDENT_NAME'],source='EIA-930',sourceUrl='https://www.eia.gov/electricity/gridmonitor/',observedAt=iso(d[-1]['TIMESTAMP_']),mixObservedAt=ft,retrievedAt=now.isoformat().replace('+00:00','Z'),timezone='UTC',interval='1시간 평균 · Hour Ending',loadGW=d[-1]['VAL']/1000,generationGW=sum(m['gw'] for m in mix),mix=mix,series=[dict(time=iso(r['TIMESTAMP_']),loadGW=r['VAL']/1000,flag=r.get('FLAG_ID'),imputed=r.get('IMPUTED_VAL')) for r in d[-48:]],warning='부하·믹스 관측시점 별도 · 원천 품질 플래그 보존')})
json.dump({'payloads':payloads,'missing':[key for key in IDS if key not in [p['data']['id'] for p in payloads]]},sys.stdout,ensure_ascii=False)

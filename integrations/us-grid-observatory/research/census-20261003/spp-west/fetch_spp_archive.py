import urllib.request,urllib.parse,pathlib,concurrent.futures,json
from lxml import html
P=pathlib.Path(__file__).parent/'raw'; base='https://opsportal.spp.org'
def get(u):return urllib.request.urlopen(u,timeout=40).read()
def fetch_index(z):
 year,url=z
 try:
  b=get(url);(P/f'spp_{year}_index.html').write_bytes(b);d=html.fromstring(b)
  out=[]
  for tr in d.xpath('//tr'):
   a=tr.xpath('.//a[@href]');vals=[' '.join(x.text_content().split()) for x in tr.xpath('./td')]
   for aa in a:
    h=aa.get('href')
    if '/documents/studies/files/' in h:out.append({'year':year,'url':urllib.parse.urljoin(base,h).replace(' ','%20'),'indexUrl':url,'indexRow':vals})
  return out
 except Exception as e:return [{'year':year,'error':str(e)}]
b=get(base+'/Studies/Delivery');(P/'spp_all_index.html').write_bytes(b);d=html.fromstring(b)
inds=[(' '.join(a.text_content().split()).split()[0],urllib.parse.urljoin(base,a.get('href'))) for a in d.xpath('//a[@href]') if 'DeliveryList?' in a.get('href')]
items=sum(list(concurrent.futures.ThreadPoolExecutor(8).map(fetch_index,inds)),[])
def dl(i):
 if 'url' not in i:return i
 u=i['url'];n='spp_'+i['year']+'_'+urllib.parse.unquote(u.split('/')[-1]).replace(' ','_');i['local']=str(P/n)
 try:
  b=get(u);(P/n).write_bytes(b);i['bytes']=len(b)
 except Exception as e:i['error']=str(e)
 return i
out=list(concurrent.futures.ThreadPoolExecutor(12).map(dl,items));(P/'spp_archive_manifest.json').write_text(json.dumps(out,indent=2));print('indexes',len(inds),'files',len(out),'errors',sum('error' in i for i in out));print([(i.get('year'),i.get('url'),i.get('error')) for i in out if 'error'in i])

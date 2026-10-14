import urllib.request,urllib.parse,pathlib,concurrent.futures,json
from lxml import html
P=pathlib.Path(__file__).parent/'raw';base='https://opsportal.spp.org'
def get(u):return urllib.request.urlopen(u,timeout=45).read()
d=html.fromstring((P/'spp_all_index.html').read_bytes());inds=[(' '.join(a.text_content().split()).split()[0],urllib.parse.urljoin(base,a.get('href'))) for a in d.xpath('//a[@href]') if '/DPNS?' in a.get('href')]
def ind(z):
 y,u=z;b=get(u);(P/f'spp_dpns_{y}_index.html').write_bytes(b);d=html.fromstring(b);out=[]
 for a in d.xpath('//a[@href]'):
  h=a.get('href')
  if any(x in h.lower() for x in ['.pdf','.docx']):out.append({'year':y,'title':' '.join(a.text_content().split()),'url':urllib.parse.urljoin(base,h).replace(' ','%20'),'indexUrl':u})
 return out
items=sum(list(concurrent.futures.ThreadPoolExecutor(5).map(ind,inds)),[])
def dl(i):
 u=i['url'];n='spp_dpns_'+i['year']+'_'+urllib.parse.unquote(u.split('/')[-1]).replace(' ','_');i['local']=str(P/n)
 try:b=get(u);(P/n).write_bytes(b);i['bytes']=len(b)
 except Exception as e:i['error']=str(e)
 return i
out=list(concurrent.futures.ThreadPoolExecutor(10).map(dl,items));(P/'spp_dpns_manifest.json').write_text(json.dumps(out,indent=2));print(out)

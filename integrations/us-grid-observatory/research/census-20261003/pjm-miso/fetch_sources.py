import urllib.request,urllib.parse,re,json,html,pathlib,concurrent.futures,subprocess
root=pathlib.Path(__file__).parent;raw=root/'raw';raw.mkdir(exist_ok=True)
links=json.load(open(raw/'teac-links.json'))
# Include public papers prepared for Oct 6: page lists September 25 publication, before census cutoff.
items=[a for a in links if 'supplemental' in a['url'].lower() and '/2026/' in a['url'] and ('local-plan' in a['url'] or any(z in a['url'] for z in ['/20260908/','/20260804/','/20260707/','/20261006/']))]
items += [a for a in links if 'm-3-process-needs-status' in a['url'] and any(d in a['url'] for d in ['/20260908/','/20261006/'])]
items += [{'text':'MTEP Projects Under Evaluation','url':'https://cdn.misoenergy.org/MTEP%20Projects%20Under%20Evaluation368757.xlsx'},{'text':'MTEP Appendix A Status Report','url':'https://cdn.misoenergy.org/Appendix%20A%20Status%20Report575959.xlsx?v=20260514162226'}]
def f(a):
 u=a['url'];p=raw/urllib.parse.unquote(u.split('/')[-1].split('?')[0]);a['localPath']=str(p)
 try:
  if not p.exists(): p.write_bytes(urllib.request.urlopen(u,timeout=45).read())
  a['bytes']=p.stat().st_size
  if p.suffix.lower()=='.pdf':subprocess.run(['pdftotext','-layout',str(p),str(p.with_suffix('.txt'))],capture_output=True)
  return a
 except Exception as e:a['error']=str(e);return a
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
 results=list(ex.map(f,items))
json.dump(results,open(raw/'source-manifest.json','w'),indent=2)
print('Downloaded',sum('bytes'in a for a in results),'of',len(results));print([a for a in results if 'error'in a])

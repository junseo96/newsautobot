from pathlib import Path
import urllib.request,concurrent.futures,json,hashlib,re,html
b=Path(__file__).resolve().parents[1]/'raw'
urls={
'wolfspeed_2026_10k_full.html':'https://www.sec.gov/Archives/edgar/data/895419/000089541926000054/wolf-20260628.htm',
'century_20260806.html':'https://investors.centuryaluminum.com/news-events/press-releases/press-release-details/2026/Century-Aluminum-Company-Reports-Second-Quarter-2026-Results/default.aspx',
'ford_20240404.html':'https://media.ford.com/content/fordmedia/fna/ca/en/news/2024/04/04/ford-updates-timing-for-next-gen-evs--readies-manufacturing-plan.html',
'southern_q2_2026.pdf':'https://s27.q4cdn.com/273397814/files/doc_financials/2026/q2/SO-2026-Q2-Earnings-Call-Final.pdf',
'fpl_q2_2026.html':'https://www.sec.gov/Archives/edgar/data/753308/000075330826000058/neeq22026exhibit99.htm',
}
def get(t):
 n,u=t
 try:
  data=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=40).read();(b/n).write_bytes(data)
  if n.endswith('.html'):
   s=data.decode(errors='replace');s=re.sub(r'<(script|style)\b[^>]*>.*?</\1>','',s,flags=re.S|re.I);s=html.unescape(re.sub('<[^>]+>',' ',s));s=re.sub(r'\s+',' ',s);(b/n.replace('.html','.txt')).write_text(s)
  return dict(file=n,url=u,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),checkedAt='2026-10-03')
 except Exception as e:return dict(file=n,url=u,error=str(e))
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as e:r=list(e.map(get,urls.items()))
(b/'download_remaining_manifest.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))

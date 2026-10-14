import concurrent.futures,hashlib,json,pathlib,urllib.request
P=pathlib.Path(__file__).parent/'raw'
urls={
 'google-e5455-draft-july2026.pdf':'https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M607/K718/607718746.PDF',
 'cpuc-october8-agenda-published-october2.pdf':'https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M622/K069/622069835.pdf',
 'cpuc-september17-hold-list.pdf':'https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M619/K318/619318894.PDF',
 'avh1-county-applications-november2024.pdf':'https://planning.lacounty.gov/wp-content/uploads/2024/12/DRP_PlanningArea_Countywide_25-11-2024_06-00-14.pdf',
 'donlin-final-eis-executive-summary-2018.pdf':'https://www.donlingoldseis.com/final-eis-2018/Executive%20Summary_FEIS.pdf',
 'donlin-financing-august2026.html':'https://novagold.com/novagold-paulson-announce-the-appointment-of-endeavour-financial-and-macquarie-capital-as-financial-advisors-to-the-donlin-gold-project/',
 'pola-may28-2026-agenda.html':'https://portoflosangeles.org/commission/agenda-archive-and-videos/agendas/2026/05282026-regular-agenda',
 'pier400-case-study.html':'https://portelectrification.com/case-studies/pier-400',
}
def run(item):
 name,url=item
 try:
  data=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30).read()
  (P/name).write_bytes(data)
  return {'filename':name,'url':url,'checkedAt':'2026-10-03','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
 except Exception as e:return {'filename':name,'url':url,'checkedAt':'2026-10-03','error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,urls.items()))
(P.parent/'named-source-downloads.json').write_text(json.dumps(results,indent=2))
for r in results:print(r['filename'],r.get('bytes'),r.get('error',''))

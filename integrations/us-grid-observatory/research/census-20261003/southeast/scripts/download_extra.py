from pathlib import Path
import urllib.request,concurrent.futures,json,hashlib,re,html
base=Path(__file__).resolve().parents[1]/'raw'
urls={
'duke_stillman_20260925.pdf':'https://dms.psc.sc.gov/Attachments/Matter/4975de54-4beb-444e-9ca1-0f0ee7016b3b',
'wolfspeed_2026_10k.html':'https://d18rn0p25nwr6d.cloudfront.net/CIK-0000895419/4d9db5cb-3b28-4dae-a902-f0d4852735b6.html',
'nucor_q2_2026.html':'https://www.sec.gov/Archives/edgar/data/73309/000119312526318190/d468854dex992.htm',
'ford_blueoval_faq.html':'https://corporate.ford.com/operations/blue-oval-city/faqs/',
'santeecooper_century_20251006.html':'https://newsroom.santeecooper.com/news/Santee-Cooper-Century-Sign-Agreement-to-Power-Additional-Potline-Create-Jobs-in-Mt.-Holly/',
'vinfast_ncdoj_20260521.html':'https://ncdoj.gov/north-carolina-sues-vinfast-to-acquire-shovel-ready-manufacturing-site/',
'rivian_20260806.html':'https://rivian.com/stories/atlanta-georgia-east-coast-headquarters-opening',
'novelis_20260805.html':'https://investors.novelis.com/news-events/press-releases/detail/1425/novelis-reports-first-quarter-fiscal-year-2027-results',
'steeldynamics_20260917.html':'https://ir.steeldynamics.com/steel-dynamics-provides-third-quarter-2026-earnings-guidance/',
'cummins_fpl_electrolyzer.html':'https://investor.cummins.com/news/detail/554/fpl-announces-cummins-to-supply-electrolyzer-for',
'fpl_cavendish_20240208.html':'https://newsroom.fpl.com/Florida-Power-Light-Company-announces-completion-of-clean-hydrogen-hub',
'plug_georgia_20240123.html':'https://www.ir.plugpower.com/press-releases/news-details/2024/Plug-Power-Starts-Production-of-Liquid-Green-Hydrogen-at-its-Georgia-Plant/default.aspx',
'plug_operating_20260922.html':'https://www.ir.plugpower.com/press-releases/news-details/2026/Plug-Power-Expands-Hydrogen-Footprint-Across-New-Zealand-and-Australia-with-GenEco-Electrolyzer-Delivery-to-HWR-Hydrogen/default.aspx',
'alabamapower_disclosure_202608.html':'https://www.alabamapower.com/company/media-room/energy-answers/data-center-facts-for-alabama-communities/data-center-agreements-and-redactions.html',
'novelis_alabamapower_20231009.html':'https://investors.novelis.com/news-events/press-releases/detail/18/novelis-partners-with-southern-company-in-pursuit-of-decarbonization-goals',
'hyundai_20250326.html':'https://www.hyundaimotorgroup.com/en/amp/CONT0000000000173041',
'nc_toyota_20251112.html':'https://governor.nc.gov/news/press-releases/2025/11/12/governor-stein-celebrates-grand-opening-toyota-battery-plant-randolph-county'
}
def get(pair):
 f,u=pair
 try:
  b=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=40).read();(base/f).write_bytes(b)
  if f.endswith('.html'):
   s=b.decode(errors='replace');s=re.sub(r'<(script|style)\b[^>]*>.*?</\1>','',s,flags=re.S|re.I);s=html.unescape(re.sub('<[^>]+>',' ',s));s=re.sub(r'\s+',' ',s);(base/f.replace('.html','.txt')).write_text(s)
  return {'file':f,'url':u,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'checkedAt':'2026-10-03'}
 except Exception as e:return {'file':f,'url':u,'error':str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as e:r=list(e.map(get,urls.items()))
(base/'download_extra_manifest.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))

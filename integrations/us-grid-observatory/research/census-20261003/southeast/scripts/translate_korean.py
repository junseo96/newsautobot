from pathlib import Path
import json,copy
B=Path(__file__).resolve().parents[1]
def read(n):return json.loads((B/n).read_text())
def save(n,x):(B/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
N=read('named_industrial_additions.json')
industries={
'Battery manufacturing':'배터리 제조','Automotive and battery manufacturing':'자동차·배터리 제조','Automotive manufacturing':'자동차 제조','Aluminum recycling and rolling':'알루미늄 재활용·압연','Semiconductor silicon-carbide materials':'반도체용 탄화규소 소재','Steel manufacturing':'철강 제조','Steel coating/manufacturing':'철강 도금·제조','Primary aluminum smelting':'1차 알루미늄 제련','Electrolytic hydrogen':'수전해 수소 생산','Aluminum rolling and recycling':'알루미늄 압연·재활용'}
status={
 'toyota-nc':'2025년 11월 12일 주정부 발표에서 공장 개장과 생산 확대 확인. 전력수요 MW와 최신 정상가동 도달 여부는 해당 자료에서 미공개.',
 'hyundai-metaplant':'2025년 3월 26일 준공 발표에서 2024년 10월 3일 첫 차량 생산 및 IONIQ 5·IONIQ 9 생산 확인. 향후 차량 생산능력 확대 수치는 전력수요로 환산 불가.',
 'rivian-georgia':'2026년 8월 6일 Rivian 발표에서 조지아 제조시설 공사 진행 확인. 운영 중인 애틀랜타 본사는 별도 시설.',
 'ford-tennessee':'현재 Ford FAQ의 트럭 조립 개시 목표는 2029년. 2024년 4월 4일 발표의 목표는 2026년이며 당시 설비 설치 진행 명시. 일정 변경 확인, 실제 계통 접속 상태는 미공개.',
 'vinfast-nc':'2026년 5월 21일 노스캐롤라이나주 법무부의 부지 회수를 위한 소송 발표. 계약상 2026년 7월 가동 목표 대비 최소 2028년까지 지연 및 계약 불이행 주장. 주정부의 주장과 지연 사실을 구분하며, 취소 확정 근거는 미확보.',
 'novelis-bay-minette':'2026년 8월 5일 분기 발표에서 주요 설비의 초기 시운전 착수 확인. 공장 시운전과 전력망 접속 완료 여부는 별도 확인 필요.',
 'wolfspeed-siler-city':'2026년 8월 20일 Form 10-K에서 Siler City의 생산 준비 완료와 낮은 가동률 확인. 최소 구매 의무가 있는 장기 전력공급계약도 공시되었으나 MW는 미공개.',
 'nucor-lexington':'2026년 7월 28일 발표에서 Lexington의 2분기 EBITDA 흑자 및 신규 사업의 생산 확대 진행 확인. 전력부하 MW는 미공개.',
 'nucor-berkeley':'2026년 7월 28일 발표에서 설비 시운전 진행 및 2026년 가을 생산 개시 목표 확인. 생산 목표일에 대한 실제 통전 근거는 미확보.',
 'century-mt-holly':'2026년 8월 6일 사업자 발표에서 Mt. Holly의 잔여 전해조 90기 재가동 완료 확인. 2025년 10월 6일 Santee Cooper 발표에서 2031년까지 연장된 계약에 따른 추가 전력공급 확인.',
 'plug-woodbine':'2024년 1월 23일 사업자 발표에서 생산 개시 및 5 MW PEM 수전해 설비 8기 확인. 2026년 9월 22일 발표에서 조지아 수소시설의 운영 지속 확인.',
 'fpl-cavendish':'2024년 2월 8일 FPL 발표에서 태양광 기반 수소 실증시설 준공 확인. 2022년 2월 28일 공급업체 발표에 수전해 설비 5기, 합계 25 MW 명시.',
 'aluminum-dynamics-columbus':'2026년 9월 17일 사업자 실적 전망에서 냉간압연기 3기 전체와 첫 연속 소둔·용체화 열처리 라인의 가동 확인. 출하량 확대 및 고객 승인 절차 진행.'}
common_gaps=[
'인용한 1차 자료에서 시설 전체 전력수요 MW와 미통전 잔여 MW 미확보.',
'Georgia·Duke·TVA·Southern 비공개 행과의 동일 사업 연결 근거 미확보. 해당 집계와 중복 합산 금지.',
'공장 공사·생산 이력만으로 계통심사 완료 또는 특정 접속 단계 도달 여부 판정 불가.'
]
extras={
'hyundai-metaplant':['발표의 주차장 태양광 5.2 MW는 발전용량이므로 전력부하 MW에서 제외.'],
'ford-tennessee':['현재 FAQ의 게시일 미표기. 2029년은 회사 목표이며 실제 통전일은 미확인. 트럭 공장과 별도 배터리 공장의 소유권 변경·용도 전환은 구분 필요.'],
'vinfast-nc':['인용한 주정부 발표만으로 회사 측 이의 제기와 후속 소송 결과 확인 불가. 취소·철회로 분류할 근거 미확보.'],
'novelis-bay-minette':['재생에너지 구독으로 지원하는 80 MW 태양광 발전소 2기는 발전자산. 이를 Novelis 전력수요 160 MW로 해석 불가.'],
'fpl-cavendish':['산업용 전력수요 범위에 포함한 전력회사 소유 시설로, 별도 소매 고객에 해당하지 않음. 확보한 최근 구체적 운영 자료는 2024년 기준.'],
'aluminum-dynamics-columbus':['위치만으로 전력 공급사를 추정하지 않음. 별도로 발표된 신규 재활용 슬래브 시설은 이 압연공장 행에 통합하지 않음.']}
power={
'novelis-bay-minette':'Novelis의 Bay Minette 대상 Alabama Power 재생에너지 구독 참여 확인. 고객 부하의 계약 MW는 미공개.',
'wolfspeed-siler-city':'Form 10-K에 Siler City·Durham 장기 전력공급계약의 구매 의무 공시. 인용 구간의 공급사·MW는 미공개.',
'century-mt-holly':'추가 전해조 라인에 대한 전력회사·고객 간 공급계약 체결 및 2031년까지 연장 확인. 발표의 전력 MW는 미공개.'}
locations={
'North Carolina':'노스캐롤라이나주','South Carolina':'사우스캐롤라이나주','Georgia':'조지아주','Tennessee':'테네시주','Alabama':'앨라배마주','Florida':'플로리다주','Mississippi':'미시시피주'}
titles={
 'toyota-nc':'Stein 주지사, Toyota 배터리 공장 개장 발표',
 'hyundai':'HMGMA 준공 발표',
 'rivian':'Rivian 애틀랜타 동부 본사 개장 발표',
 'ford-current':'BlueOval City FAQ — 2026년 10월 3일 확인',
 'ford-2024':'Ford 차세대 전기차 일정 변경 발표',
 'vinfast':'노스캐롤라이나주, 제조 부지 회수를 위한 VinFast 소송 발표',
 'novelis-2026':'Novelis 2027 회계연도 1분기 실적',
 'novelis-power':'Novelis·Southern Company 협력 발표',
 'wolfspeed':'Wolfspeed 2026 회계연도 Form 10-K',
 'nucor':'Nucor 2026년 2분기 실적 발표, 슬라이드 8',
 'century-current':'Century Aluminum 2026년 2분기 실적',
 'century-power':'Santee Cooper·Century 추가 전해조 전력공급계약 발표',
 'plug-current':'Plug Power 2026년 9월 22일 운영시설 현황',
 'plug-mw':'Plug 조지아 수소 생산 개시 발표',
 'fpl-complete':'FPL 청정수소 허브 준공 발표',
 'fpl-mw':'Cummins의 FPL용 25 MW 수전해 설비 공급 발표',
 'sdi':'Steel Dynamics 2026년 3분기 실적 전망'}
for r in N:
 key=r['id'].removeprefix('southeast-industrial-')
 r['regionBasis']='미국 남동부 비RTO 조사 범위에 속하는 지리적 위치 기준. 별도 출처가 없는 전력 공급사·접속 관계는 미확인.'
 r['industry']=industries[r['industry']]
 r['industryEvidence']='사업자·공급업체·전력회사·주정부의 1차 발표자료에서 산업 활동 확인.'
 for en,ko in locations.items():r['location']=r['location'].replace(en,ko)
 for p in r['participants']:p['role']='사업 소유자·개발사'
 r['statusSummary']=status[key]
 r['milestones'][0]['detail']=status[key]
 r['milestones'][1]['detail']=power.get(key,'사업별 공개 전력공급계약, 계통심사 결과 및 공식 접속 대기열 ID 미확보.')
 r['gaps']=common_gaps+extras.get(key,[])
 for s in r['sources']:s['title']=titles[s['id']]
 for c in r['capacities']:
  c['basis']=('수전해 설비의 정격 전력: 5 MW PEM 설비 8기. 시설 전체 최대수요·접속 신청용량·미통전 잔여용량과 구분.' if key=='plug-woodbine' else '수전해 시스템의 정격 전력. 인접 태양광으로 가동하는 전력회사 소유 실증시설이며, 고객 접속 신청용량과 구분.')
save('named_industrial_additions-korean.json',N)
O=read('load_observations_additions.json')
labels={
'Advanced Development Projects':'개발 진척 프로젝트',
'Electric Service Agreement':'전력서비스계약(ESA)',
'Letter Agreement':'서한합의(Letter Agreement)',
'Late Stage Pipeline':'협의 후기 프로젝트',
'Developing Pipeline (nearly 6 GW)':'개발 검토 프로젝트(6 GW에 근접)'}
for r in O:
 r['metricLabel']=labels[r['metricLabel']]
 r['asOfNote']='2026년 봄 자료 기준. 4월 17일 반기 보고서 2쪽에 2026년 2월 기준으로 명시. 9월 25일 증언서는 봄 집계표를 재인용한 것으로, 9월 신규 현황이 아님.'
 r['sourceTitle']='Phillip O. Stillman 직접 증언서, SCPSC 사건 2026-8-E / 2026-10-E, 10쪽 표 1'
 r['collectionMethod']='공공요금위원회 1차 PDF 열람·보관 및 표 1 전체 행 추출. 4월 17일 봄 보고서와 후속 증언서 수치 대조.'
 r['nextAction']='2026년 가을 반기 보고서 제출 후 확보. 공개 고객 목록과 사건별 사업 ID 추가 확인.'
 r['remainingGap']='개별 사업 ID·명칭·업종별 배분·DEC/DEP 구분·부하 증가 일정·미통전 잔여 MW 미공개. 4월 표의 ESA 4,337 MW·총계 7,946 MW와 같은 보고서 본문 및 9월 표의 4,332 MW·7,941 MW 사이에 5 MW 차이.'
 r['metricBasis']='전망 할인 적용 전 고객 최종 부하용량'
 r['scope']='노스캐롤라이나·사우스캐롤라이나의 DEC·DEP 소매 상업·산업 고객 개발사업. 도매 고객 사업은 별도 집계.'
 counts={'advanced':(43,'7,941'),'esa':(16,'4,332'),'letter':(24,'3,259'),'late':(3,'350')}
 if 'developing' not in r['id']:
  key=r['id'].split('-')[2];n,mw=counts[key]
  r['evidenceText']=f'2026년 봄 표 1: {r["metricLabel"]} {n}건, {mw} MW. 부하 전망 할인 적용 전 최종 부하용량.'
 else:
  r['asOfNote']='2026년 IRP의 개발 검토 사업 집계. 정확한 기준 월은 미공개. 9월 25일 증언서에 6,000 MW에 근접한 규모로 재인용.'
  r['evidenceText']='Stillman 증언서 9·11쪽: 추가 최종 부하 약 6,000 MW. 부지가 정해지고 계통 검토가 시작된 50 MW 초과 개별 사업으로, 부지 권리 확인서·용도지역 확인서·고객 정보서 제출 요구. 개발 진척 프로젝트 43건과 별도 집계.'
  r['scope']='DEC·DEP 개발 검토 목록의 부지 확정 상업·산업 사업. 표시한 최종 부하에는 전망 산정용 50% 할인 미적용.'
  r['remainingGap']='사업 수·명칭·개별 MW·정확한 기준일 미공개. 약 6,000 MW는 원문의 6,000 MW에 근접하되 그보다 작은 규모를 근사치로 표시한 값. 전체 초기 문의를 포괄하는 목록은 아님.'
 for s in r.get('stageBreakdown',[]):
  s['stage']=labels[s['stage']]
  s['criterion']='원문 정의에 따른 개발 진척 단계 구분. 통전 여부는 이 분류만으로 확인 불가.'
save('load_observations_additions-korean.json',O)
# Numeric values, dates, identifiers, enums and source linkage must remain byte-for-byte equivalent as values.
protected={'id','region','lifecycle','powerRoute','gridRequestMW','queueId','matchedProjectId','asOf','checkedAt','additive','sourceId','url','publishedAt','mw','gate','status','operator','publicationDate','sourceUrl','includesEnergized','targetYear','valueQualifier','valueGW','stageClass','parentId','projectCount'}
def check(a,b,path=''):
 if isinstance(a,dict):
  assert set(a)==set(b),(path,'keys')
  for k in a:
   if k in protected:assert a[k]==b[k],(path,k,a[k],b[k])
   else:check(a[k],b[k],path+'/'+k)
 elif isinstance(a,list):
  assert len(a)==len(b),(path,'length')
  for i,(x,y) in enumerate(zip(a,b)):check(x,y,path+'/'+str(i))
 elif not isinstance(a,str):assert a==b,(path,a,b)
for n in ['named_industrial_additions','load_observations_additions']:
 check(read(n+'.json'),read(n+'-korean.json'))
print('Translated 13 named records and 5 observations; protected-field equality checks passed.')

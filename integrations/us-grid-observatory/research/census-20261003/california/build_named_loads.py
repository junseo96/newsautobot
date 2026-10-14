"""Map verified research evidence to the Site's existing NamedLoad contract.
Writes research files only. Does not write or change Site files.
"""
import json,pathlib
P=pathlib.Path(__file__).parent
def src(id,title,url,date=None):return {'id':id,'title':title,'url':url,'publishedAt':date}
def milestone(gate,status,detail,sourceId=None):return {'gate':gate,'status':status,'detail':detail,'sourceId':sourceId}
def base(id,name,region,regionBasis,location,industry,lifecycle,participants,utility,powerRoute):
 return dict(id=id,name=name,aliases=[],region=region,regionBasis=regionBasis,location=location,industry=industry,lifecycle=lifecycle,participants=[{'role':r,'name':n} for r,n in participants],utility=utility,powerRoute=powerRoute,capacities=[],gridRequestMW=None,queueId=None,matchedProjectId=None,checkedAt='2026-10-03',additive=False)
rows=[]

r=base('NAMED_AVH1_CA','Antelope Valley Hydrogen 1','West','현장 태양광 중심 수소 프로젝트의 서부 탐색 분류 · 공식 CAISO 접속원장·전력회사 연결 미확인','Antelope Valley, Los Angeles County, California','화학·수소·연료','planned',[('개발사','Novo Hydrogen'),('계획 심사','Los Angeles County Department of Regional Planning')],None,'onsite')
r.update(aliases=['AVH1','앤털로프 밸리 수소 1'],industryEvidence='카운티 신청서와 개발사 자료가 전기분해 수소 생산설비로 명시',capacities=[{'mw':162,'basis':'2024-11-25 카운티 접수 목록의 전기분해 설비 최대 정격 · 계통 신청·확보 용량 아님','sourceId':'county'},{'mw':182,'basis':'2024-08-06 개발사의 전기분해 설계 발표 · 후속 카운티 신청 162MW와 상충하며 합산 불가','sourceId':'developer_dated'}],statusSummary='토지이용 신청 접수 확인 · 전기분해 설계 162MW와 182MW가 상충하며 최신 승인 설계·계통접속 상태 미확인',milestones=[
 milestone('프로젝트','확인','카운티의 RPAP2024006028·6029·6030은 RPPL2024000110에 연계된 같은 수소 프로젝트의 신청으로 묶어 1건 처리','county'),
 milestone('인허가','조건부','2024-11-22 토지이용 신청이 2024-11-25 목록에 접수된 사실 확인 · 후속 승인·착공 여부 미확보','county'),
 milestone('전력 확보','조건부','개발사는 현장 태양광 235MW로 전기분해를 공급하는 계획을 설명 · 태양광은 발전설비이며 수용가 부하 또는 계통 신청 MW가 아님','developer_dated'),
 milestone('공사','미확보','해당 수소설비의 착공·공정률을 확인할 최신 1차 자료 미확보'),
 milestone('통전','미확보','전기분해 설비 통전·수소 상업생산 또는 전력회사 서비스 개시 확인 미확보')],gaps=[
 '카운티 자료는 최대 162MW, 앞선 개발사 발표는 182MW 전기분해 설계로 차이 존재 · 확정 현재 용량으로 단일화 불가',
 '현재 개발사 페이지에 182MW와 과거 300MW 문구가 함께 남아 있어 최신 설계 판단 근거로 단독 사용 불가',
 '공식 계통 신청 ID·계통 신청 MW·전력회사 및 계통 보완전력 규모 미확보',
 '인허가 단계의 기준일은 2024-11-25이며 2026-10-03 확인일이 최신 승인·진척을 뜻하지 않음',
 '카운티 신청의 태양광 약 240MW와 개발사 발표의 235MW는 발전계획 · 전기분해 부하와 합산 불가'],sources=[
 src('county','LA County — 2024-11-18~25 계획 신청 접수 목록, 17~22쪽','https://planning.lacounty.gov/wp-content/uploads/2024/12/DRP_PlanningArea_Countywide_25-11-2024_06-00-14.pdf'),
 src('developer_dated','Novo Hydrogen — ARCHES 협력 사업과 AVH1 전기분해·태양광 계획','https://novohydrogen.com/news/california-arches-hub-secures-nations-first-federal-funding-for-renewable-clean-hydrogen/','2024-08-06'),
 src('developer_live','Novo Hydrogen — AVH1 프로젝트 페이지, 설계 문구 상충','https://novohydrogen.com/antelope-valley-hydrogen-1/')],asOf='2024-11-25')
rows.append(r)

r=base('NAMED_POLA_ZEPEO_CA','Port of Los Angeles ZEPEO','West','LADWP가 공급하는 로스앤젤레스항 전력시설 사업 · CAISO 수용가 접속원장과 별도인 서부 분류','Port of Los Angeles, Los Angeles, California','항만·물류·운송','planned',[('항만 사업주','City of Los Angeles Harbor Department'),('전력시설 공급·설계','Los Angeles Department of Water and Power')],'LADWP','grid')
r.update(aliases=['ZEPEO','로스앤젤레스항 전기화','Zero-Emission Port Electrification and Operations'],industryEvidence='항만 화물취급장비의 무배출 전환을 지원하는 전력설비 확충 사업',statusSummary='환경심사 채택 확인 · 2030년 추가 213MVA, 2035년 추가 306MVA 전력시설 MOU 계획이며 MW 환산·단일 수용가 집계 불가',milestones=[
 milestone('프로젝트','확인','2026-05-28 항만위원회 안건에 ZEPEO 사업과 LADWP 협력 MOU 범위 제시','agenda'),
 milestone('인허가','확인','LADWP의 IS/MND 인증일은 2026-03-24, 항만 환경문서 목록의 채택일은 2026-05-28 · SCH2025120795','environment'),
 milestone('전력 확보','조건부','MOU 안건은 2030년까지 추가 213MVA, 2035년까지 추가 306MVA의 34.5kV 전력시설 확보를 제시 · 원문 단위 MVA 유지','agenda'),
 milestone('공사','미확보','환경심사 채택과 전체 전력시설 공사 착수·준공은 구분 · 전체 사업 공정률 미확보'),
 milestone('통전','미확보','계획한 추가 전력시설 전체의 통전 또는 항만 수용가 실제 인출 MW 미확보')],gaps=[
 '213MVA·306MVA는 피상전력 전력시설 규모 · 역률 근거가 없어 MW로 환산하지 않으며 capacities 배열은 비워 둠',
 '항만 전체 기반시설 사업으로 개별 터미널의 서비스 요청과 중복 가능 · 하나의 고객·공식 큐 항목으로 집계 불가',
 '2035년 306MVA와 2030년 213MVA의 중복 범위가 명확하지 않아 두 수치를 합산하지 않음',
 '안건에 예정된 2026-07-14 LADWP MOU 표결의 후속 승인 결과 미확보',
 '날짜 없는 사업 개요의 추가 200MVA와 2026-05-28 MOU 안건 수치는 범위·시점이 달라 별도 보존',
 '공식 수용가 큐 ID와 계통 신청 MW 미확보'],sources=[
 src('agenda','Port of Los Angeles — 2026-05-28 항만위원회 안건 7, ZEPEO MOU','https://portoflosangeles.org/commission/agenda-archive-and-videos/agendas/2026/05282026-regular-agenda','2026-05-28'),
 src('environment','Port of Los Angeles — ZEPEO 환경문서 채택 이력','https://portoflosangeles.org/environment/environmental-documents'),
 src('overview','Port of Los Angeles — LADWP 협력 개요, 추가 200MVA 표기','https://portoflosangeles.org/environment/air-quality/cooperative-agreement')],asOf='2026-05-28')
rows.append(r)

r=base('NAMED_APMT_PIER400_CA','APM Terminals Pier 400 전력 증설','West','LADWP가 공급하는 로스앤젤레스항 터미널의 서부 분류 · CAISO 접속원장 미연결','Pier 400, Port of Los Angeles, California','항만·물류·운송','partial-operation',[('터미널 운영','APM Terminals'),('전력 공급','Los Angeles Department of Water and Power'),('항만','Port of Los Angeles')],'LADWP','grid')
r.update(aliases=['Pier 400','피어 400','APMT Pier 400'],industryEvidence='운영사가 참여한 ZEPA 사례 자료가 전기 트랙터·스트래들 캐리어·선박 육상전원을 설명',capacities=[{'mw':18,'basis':'계통 공급능력 7→18MW 증설 목표의 최종 총량 · 18MW 신규 증분이나 완료 통전 MW 아님','sourceId':'zepa'},{'mw':7,'basis':'같은 자료가 제시한 기존 계통 공급능력 · 목표 18MW와 합산 불가','sourceId':'zepa'}],statusSummary='전기 화물취급장비 일부 운영 확인 · 계통 공급능력 7→18MW 증설을 설명하지만 18MW 전체 통전 완료는 미확인',milestones=[
 milestone('프로젝트','확인','APM Terminals·Kalmar·Orange EV가 참여한 자료가 Pier 400의 전기장비 운영과 전력 증설을 설명','zepa'),
 milestone('전력 확보','조건부','LADWP·항만·APMT가 계통 공급능력 7MW를 18MW로 확대 중이라고 명시 · 계약·통전 완료 문서 미확보','zepa'),
 milestone('통전','확인','전기 터미널 트랙터 20대 등 일부 장비 운영과 방문 선박 육상전원 사용 확인 · 이 확인은 18MW 전체 증설의 통전을 뜻하지 않음','zepa'),
 milestone('통전','미확보','증설 목표 18MW 전체 공급 개시일·실제 피크 수요·전력회사 계량 자료 미확보')],gaps=[
 '출처 하단은 수치 기준을 2025년 중반으로 적지만 본문은 2025년 실적과 올해라는 표현을 포함 · 정확한 게시일·전체 수치 기준일 미확정',
 '기존 장비의 운영을 계통 공급능력 18MW 증설 완료로 해석하지 않음',
 '공식 접속 큐 ID·계통 신청 MW 미확보 · 18MW는 목표 총 공급능력',
 'ZEPEO 등 항만 전체 전력시설 계획과 중복 가능하여 합산 불가'],sources=[src('zepa','ZEPA — Pier 400 running to net zero, 참여 기업과 공동 발행한 사례 자료','https://portelectrification.com/case-studies/pier-400')],asOf=None)
rows.append(r)

r=base('NAMED_DONLIN_GOLD_AK','Donlin Gold 광산','West','알래스카 현장 자가발전 광산의 탐색 편의상 West 분류 · 미국 서부 동기계통·Railbelt 유틸리티 연결을 뜻하지 않음','Donlin Gold project, southwest Alaska','철강·금속·광물','planned',[('개발사','NOVAGOLD'),('사업 지분 보유','Donlin Gold Holdings LLC / Paulson')],None,'onsite')
r.update(aliases=['Donlin','돈린 골드'],industryEvidence='USACE 환경영향평가와 개발사 공시가 금광 개발·광물 처리 사업으로 확인',capacities=[{'mw':153,'basis':'2018년 최종 EIS 설계의 평균 운전 전력부하 · 과거 설계값이며 계통 신청·현재 확정 수요 아님','sourceId':'eis'}],statusSummary='2026-08-11 금융조달 준비와 금융조달용 타당성조사 진행 확인 · 153MW는 2018년 자가발전 광산 설계의 평균 운전부하',milestones=[
 milestone('프로젝트','확인','2026-08-11 개발사가 금융자문사 선임과 금융조달용 타당성조사(BFS) 진행을 공시','financing'),
 milestone('전력 확보','조건부','2018년 EIS는 현장 발전으로 평균 운전부하 153MW를 공급하는 설계 · 발전 정격 227MW에는 예비설비가 포함되어 부하와 구별','eis'),
 milestone('인허가','확인','2018년 최종 환경영향평가의 사업·전력 설계 자료 확보 · 이 자료만으로 모든 현재 인허가 완료를 주장하지 않음','eis'),
 milestone('공사','조건부','개발사는 BFS 완료와 관련 업무 이후 최종 투자결정으로 진행하는 단계라고 설명 · 전체 광산 본공사 착수 확인은 아님','financing'),
 milestone('통전','미확보','계획한 광산의 상업 운전 또는 153MW 부하 통전 미확보')],gaps=[
 '153MW는 2018년 환경영향평가의 평균 운전부하 · 현재 진행 중인 타당성조사가 설계·전력수요를 변경할 수 있음',
 '227MW 발전설비 정격을 227MW 수용가 부하나 계통 요청으로 표기하지 않음',
 '현장 발전 계획으로 확인되며 Railbelt 유틸리티의 대기열·계통 신청 MW에 포함하지 않음',
 '최종 투자결정·자금조달 완료·본공사 착수·상업생산 확인 미확보',
 'EIS는 2018년 4월 자료이나 정확한 일자 미확정으로 출처 publishedAt은 null 유지'],sources=[
 src('eis','USACE — Donlin Gold 최종 EIS 요약, 2018년 4월, 16쪽','https://www.donlingoldseis.com/final-eis-2018/Executive%20Summary_FEIS.pdf'),
 src('financing','NOVAGOLD — Donlin 금융자문사 선임·BFS 및 최종 투자결정 전 단계','https://novagold.com/novagold-paulson-announce-the-appointment-of-endeavour-financial-and-macquarie-capital-as-financial-advisors-to-the-donlin-gold-project/','2026-08-11')],asOf='2026-08-11')
rows.append(r)

r=base('NAMED_GOOGLE_DISK_DRIVE_CA','Google 5079 Disk Drive — San Jose','CAISO','CPUC가 PG&E 230kV 송전급 소매서비스 신청으로 명시한 San Jose 부하 · 공식 개별 큐 ID는 미공개','5079 Disk Drive, San Jose, California','데이터센터','planned',[('수용가','Google LLC'),('전력회사','Pacific Gas and Electric Company'),('규제기관','California Public Utilities Commission')],'PG&E','grid')
r.update(aliases=['Google San Jose','구글 산호세','E-5455','PG&E AL 7785-E'],industryEvidence='CPUC 결의안 초안과 2026-10-02 공표 안건이 신규 250MW 데이터센터 부하로 명시',capacities=[{'mw':250,'basis':'CPUC 공식 자료의 전면 개발 시 예상 소매 전력수요 · 230kV 서비스 신청 250MW, 규제승인·통전 대기','sourceId':'draft'}],statusSummary='PG&E의 250MW·230kV 서비스 신청과 예비 엔지니어링 완료 확인 · CPUC 승인안은 2026-10-08 회의로 보류되어 10월 3일 현재 승인·통전으로 표시 불가',milestones=[
 milestone('프로젝트','확인','Google은 2025-03-03 서비스 신청, PG&E는 2025-12-18 Advice Letter 7785-E 제출 · 원문에 5079 Disk Drive와 250MW 명시','draft'),
 milestone('전력 확보','조건부','2025년 12월 최신 예비 엔지니어링 연구(PES) 완료 · 230kV 개폐소와 지중선이 필요하며 최종 전력공급 승인과 구별','draft'),
 milestone('인허가','조건부','2026-10-02 발행한 10월 8일 안건 2는 E-5455를 아직 승인 제안으로 수록 · 7월 16일·8월 13일·9월 3일·9월 17일 보류 이력 명시','october_agenda'),
 milestone('공사','조건부','원문 신청 일정은 2027년 1월 공사 개시 목표 · 착공 확인이 아님','draft'),
 milestone('통전','조건부','원문은 2028년 12월 서비스 개시 목표를 제시 · 승인·시공·실제 통전은 별도 확인 필요','draft')],gaps=[
 '250MW는 공식 서비스 신청의 전면 개발 예상 부하로 확인되지만 공개된 개별 큐 ID는 미확보',
 'Advice Letter 7785-E와 결의안 E-5455는 공시·규제 문서 ID이며 수용가 큐 ID가 아님 · queueId와 gridRequestMW는 null, 확인된 250MW는 용량 근거에 보존',
 '결의안 초안의 승인한다는 문구는 제안 결과 · 2026-10-03 현재 실제 의결·최종승인으로 해석 불가',
 '2027년 1월 착공과 2028년 12월 운영은 신청인의 목표 일정 · 완료된 단계가 아님',
 '확정 공사비·최종 서비스 계약 조건·통전일 및 실제 인출량 미확보'],sources=[
 src('draft','CPUC — 결의안 E-5455 초안, PG&E·Google 250MW 예외 서비스 신청','https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M607/K718/607718746.PDF','2026-07-16'),
 src('october_agenda','CPUC — 2026-10-08 회의 안건, 10월 2일 발행, 3~4쪽','https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M622/K069/622069835.pdf','2026-10-02'),
 src('september_hold','CPUC — 2026-09-17 회의 최종 보류 목록','https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M619/K318/619318894.PDF','2026-09-15')],asOf='2026-10-02')
rows.append(r)
(P/'named-loads.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print('Wrote',len(rows),'named load records')

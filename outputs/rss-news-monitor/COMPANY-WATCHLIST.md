# 기업별 산업 뉴스 추적표

2026-09-23 v10: 운영·일정·산업 판단 요약은 PROTOCOL.md 우선. 이 문서는 기업별 식별자·공식 경로가 필요한 때만 해당 부분 참고. 메이저 주도 연구·실증 포함, 구체적 예외는 INDUSTRIAL-SIGNAL-POLICY.md 참조.

2026-09-15 추가: 미국·한국 주요 송전 프로젝트는 `TRANSMISSION-WATCHLIST.md`의 프로젝트명·노선·허가번호 기준으로 별도 추적. Oncor·LCRA TSC·CenterPoint·AEP Texas 등 텍사스 사업자와 ERCOT STEP/PBRP 포함. 소스 등록/직접 원문 확인/실제 발송을 구분하며 수주 고객이 비공개인 한국 기자재 계약을 특정 미국 노선에 임의 연결하지 않는다.

2026-09-14 사용자 요청 반영, 정책 v8. 한국·미국 전력망 중심과 글로벌 배전 아키텍처 기준 유지. 아래는 기업 추적 경로이며 추천 종목 목록이나 모든 발표의 포착 보증이 아님.

## 핵심 지정 기업과 연결 경로

| 기업 | 추적 식별자 | 등록된 공식 발표 경로 | 회사별 공시 경로 |
| --- | --- | --- | --- |
| GE Vernova | GEV / GE버노바·지이베르노바 | 기존 공식 뉴스룸 HTML | 기존 SEC |
| Siemens Energy | 지멘스 에너지 | 기존 공식 뉴스룸 HTML | 공식 IR·현지 공시로 원문 확인; SEC 전용 피드 미구축 |
| Siemens AG 전력 부문 | 지멘스 / Smart Infrastructure | 공식 보도자료 RSS 신규 | 공식 IR·현지 공시로 원문 확인; Siemens Energy와 별도 |
| Forgent Power Solutions | FPS / 포전트·포젠트 | 공식 보도자료 RSS 신규 | SEC CIK 2080126 신규 |
| Quanta Services | PWR / 콴타·퀀타 | 공식 보도자료 RSS 신규 | 기존 SEC |
| Bloom Energy | BE / 블룸에너지 | 공식 보도자료 RSS 신규 | 기존 SEC |
| Fluence Energy | FLNC / 플루언스 | 공식 Media Room의 IR 기사 링크 연결; 원문 직접 접속 공백은 별도 | 기존 SEC |
| Eaton | ETN / 이튼 | 공식 보도자료 도메인 한정 Google RSS 연결; 직접 접속 공백 유지 | 기존 SEC |
| Vertiv | VRT / 버티브 | 기존 공식 보도자료 RSS | 기존 SEC·IR 공시 RSS |
| NextEra Energy | NEE / 넥스테라 / FPL / NextEra Energy Resources | 공식 뉴스룸 RSS 신규 | SEC CIK 753308 신규 |
| Duke Energy | DUK / 듀크 에너지 | 기존 공식 보도자료 RSS | SEC CIK 1326160 신규 |
| American Electric Power | AEP | 공식 뉴스 도메인 한정 Google RSS 연결; 직접 접속 공백 유지 | SEC CIK 4904 신규 |
| Dominion Energy | D / 도미니언 | 기존 공식 보도자료 RSS | SEC CIK 715957 신규 |
| PG&E Corporation | PCG / PG&E / Pacific Gas and Electric | 공식 보도자료 RSS 신규 | SEC CIK 1004980 신규 |
| Xcel Energy | XEL / 엑셀에너지 / NSP·PSCo·SPS | 공식 뉴스룸 HTML·IR RSS 신규 | SEC CIK 72903 신규 |

Xcel의 규제 자회사 Northern States Power, Public Service Company of Colorado, Southwestern Public Service의 송전망·변전·IRP·비용회수·전력공급 사업 포함. ITC Holdings·American Transmission Company(ATC)·Transource·LS Power Transmission·GridLiance 등도 산업 선별 범위에 포함하되 전용 피드를 모두 등록했다는 뜻은 아님.

기존 한국전력·HD현대일렉트릭·LS ELECTRIC·효성중공업·두산에너빌리티·한전기술·한전KPS·SK가스·포스코인터내셔널·일진전기·대한전선·가온전선의 DART 감시 목록 및 Hubbell·Powell·nVent·EMCOR·MYR·Cummins·Caterpillar·Generac 등 기존 경로 유지. DART 목록 등록은 인증·접속 상태 정상 확인과 다르며 해당 회차의 실제 상태 확인 필요. 여기에 없는 주요 동종업계 산업 사실도 기존 산업 기준에 따라 포함.

## 이번에 실제 읽기 검증한 경로

정규 운영 DB 수집·기사 발송 없이 공개 경로 읽기와 파서 검증 수행. 첫 기업 확장으로 공식 발표 RSS 6개와 SEC 6개 등록한 뒤 Xcel 3개 경로, Fluence 미디어룸, AEP/Eaton 간접 발견 경로 추가. 정적 수집 소스 총 117개, 회사별 SEC 감시 21개. 각각 다음 정규 수집 회차부터 유입. 기사 수는 검증 시 피드의 항목 수이며 이번 텔레그램 발송 수가 아님.

| 공식 발표 RSS | 파싱 항목 수 | 검증 시 최신 항목 날짜 |
| --- | ---: | --- |
| [Forgent](https://ir.forgentpower.com/news-events/press-releases/rss) | 10 | 2026-08-27 |
| [Quanta](https://investors.quantaservices.com/news-events/press-releases/rss) | 10 | 2026-09-09 |
| [Bloom](https://investor.bloomenergy.com/rss/pressrelease.aspx) | 10 | 2026-09-11 |
| [Siemens AG](https://press.siemens.com/global/en/rss.xml) | 10 | 2026-09-09 |
| [NextEra](https://newsroom.nexteraenergy.com/news-releases?pagetemplate=rss) | 5 | 2026-09-09 |
| [PG&E](https://investor.pgecorp.com/rss/pressrelease.aspx) | 10 | 2026-09-03 |

SEC 신규 경로는 `sources.json`의 `SEC FPS/NEE/DUK/AEP/D/PCG Company Filings` 항목. 개별 CIK는 SEC submissions JSON의 회사명·티커와 대조. 파싱 결과 FPS 6건, NEE 33건, DUK 52건, AEP 49건, D 15건, PCG 52건. Forms 8-K/10-Q/10-K/6-K/20-F 기준이며 최신 등록물 전체를 항상 포괄한다는 뜻은 아님. 기존 공식 RSS와 같은 사건이 겹치면 성공 영수증 본문으로 통합 검증.

RSS 파싱 성공은 사이트 최신성·모든 발표 포착을 보증하지 않음. 특히 피드의 항목 수 제한, 실적 안내·배당·홍보의 높은 비중, 별도 IR 프레젠테이션에만 있는 자료에 주의. 원문 발표일과 수신일을 분리하고 산업 사실 없는 기사는 보내지 않음.

## 추가 연결과 남은 직접 접속 공백

- Xcel: [공식 IR RSS](https://investors.xcelenergy.com/rss/pressrelease.aspx) 10건, [공식 뉴스룸](https://newsroom.xcelenergy.com/news) 기사 경로 필터 후 10건, 회사별 SEC 61건 파싱 확인. SEC submissions JSON의 회사명·XEL·CIK 72903 대조. IR 목록에는 없는 9월 8일 South Dakota 송전선 신청이 뉴스룸에 있어 두 경로 병행. 뉴스룸 목록은 날짜만 제공하므로 정확한 시각·미국 시간대는 원문 확인 전 단정 금지.
- AEP: [공식 뉴스룸](https://www.aep.com/news/stories/) 및 기존 `pr.aep.com` TLS 연결 시간초과. 실행 권한 확장 후 동일 요청도 실패, PowerShell 별도 요청도 SSL 연결 실패. `site:aep.com/news/stories/view/`의 Google RSS 100건 파싱 확인, 회사별 SEC와 함께 신규 등록. 옛 `pr.aep.com` 한정 검색 RSS는 0건으로 사용하지 않음. 직접 접속 정상화가 아닌 공식 기사 간접 발견 경로.
- Eaton: [공식 뉴스룸](https://www.eaton.com/us/en-us/company/news-insights.html), 연간 2026 목록, 공개 content 경로 모두 20초 응답 시간초과. 실행 권한 확장 후에도 동일. 공식 보도자료 경로 한정 Google RSS 100건 파싱 및 Arkansas 증설·Trane 협업 포함 확인, 기존 SEC와 병행. `when:30d`를 추가한 검증에서는 최근 주요 기사도 누락되어 날짜 제한 없는 발견 경로 채택. 원문 발표일·중복 검증 필수, 직접 공식 수집 복구로 기록 금지.
- Fluence: [공식 Media Room](https://fluenceenergy.com/about/media-room/) 정상 응답, 공식 IR 도메인의 실제 발표 4건 파싱 확인. 기존 HTML 파서의 동일 호스트 제한으로 기사 링크가 제외되던 구조를 수정하되 이 소스에서 `ir.fluenceenergy.com`만 명시 허용. 메뉴·다른 도메인 링크는 제외. [IR 원문](https://ir.fluenceenergy.com/news-events)의 로컬 직접 요청 시간초과는 권한 확장 후에도 남음. 웹 원문 조회는 가능한 사례 확인. 목록 날짜가 없으면 null 유지하고 원문에서 확인; 목록 4건은 전체 이력 포착을 뜻하지 않음.

세 곳 모두 사용자 로그인·CAPTCHA·유료 결제·동의 부족이 원인이라는 증거 없음. AEP/Eaton은 서버/CDN/네트워크 중 어느 계층이 근본 원인인지는 미확정. 권한 확대로 해결됐다고 보고하거나 사용자의 승인 탓으로 설명하지 않음.

모닝에 AEP·Eaton의 누락 가능 공백과 Fluence 미확인 산업 원문을 공식 사이트 한정 검색으로 묶어서 1회 보완. 실시간은 관련 새 후보·새 장애가 있는 경우 해당 기업만 확인. 접근불가 원문은 공식 고객·규제 문서 대체 출처를 확인하고 불가하면 pending 유지. 간접 RSS가 성공해도 기존 직접 접속 공백은 실행 결과의 `coverage_gaps`에 구분 기록. 동일한 공백 자체는 매회 알림하지 않음.

## 사용자 직접 작업

### 정규 유입 및 후속 접속 검증 (2026-09-14 10:31 KST)

10:23 수집 snapshot `20260914T012318Z-acddb46d10e6`에서 Xcel IR 10건·SEC 61건, AEP 간접 RSS 100건·SEC 49건, Eaton 간접 RSS 99건, Fluence 미디어룸 4건 신규 저장 확인. 이 수치는 수집 결과이며 산업 심사·원문 확인·텔레그램 발송 완료 수가 아님.

같은 회차 Xcel 뉴스룸과 Bloom RSS는 DNS 조회 실패 기록. Xcel 뉴스룸은 10:31의 단일 읽기 전용 재검증에서 정상 응답·10건 파싱 확인. 정규 수집기를 다시 실행하거나 해당 snapshot의 실패 기록을 성공으로 바꾸지 않았으므로 이번 정규 수집의 뉴스룸 공백은 남음. 다음 정규 회차에서 실제 유입 여부 확인 필요. AEP/Eaton/Fluence의 위 직접 접속 공백도 해소된 것으로 간주하지 않음.

현재 등록된 위 수집 경로 작동을 위해 반드시 필요한 사용자 작업 없음. 이메일은 추가 보완 수단이며 연결 필수 조건이 아님. 이번 작업에서 구독을 제출하지 않았으므로 구독 완료로 표현 금지.

- AEP 보완 메일: [공식 Email Alerts](https://www.aep.com/email-alerts/)는 이번 조회에서 시간초과. 사용자 브라우저에서 열릴 경우 공개 뉴스/IR 알림에 기존 Gmail을 등록하고 수신 확인 메일 인증. 실제 선택 항목과 제출 조건은 페이지가 열린 뒤 확인 필요; 선택지를 추정하지 않음.
- Eaton 보완 메일: [공식 미국 구독센터](https://content.eaton.com/unified-preference-center)에서 `hjsnews96@gmail.com`, Junseo/Heo, DS investment&Securities, 실제 국가와 Contact Type 입력, 전력·데이터센터 관련 관심 분야 선택 후 `Save and Submit Preferences`. 필요한 인증 메일 도착 시 인증. 주간·월간 성격의 보완 수단이며 모든 보도자료 실시간 수신을 보장하지 않음.
- Fluence 보완 메일: [Investor Resources](https://ir.fluenceenergy.com/shareholder-services)의 News·SEC Filing·Weekly Summary와 Gmail 입력 후 제출, 확인 메일 인증. 직접 원문 접근 복구나 전 발표 수신을 보증하는 절차는 아님.

## 선별과 운영

실적·IR에서는 수주/잔고·물량·납기·가격·생산능력·CAPEX·사업부 수익성/가이던스의 산업 근거, 유틸리티는 투자·요금기저·부하계약·계통접속·IRP 우선. 본문에 새 산업 사실이 있으면 주가가 제목에 있어도 분리 검토. EPS·주가·목표가·배당·행사만 있는 자료와 기존 사실의 재서술은 미발송. 해외 소규모 프로젝트는 감시기업 이름만으로 통과 금지.

한국시간 06·09·12·15·18·21시 실행(06시 모닝), 텔레그램 서식·명사형·중복 방지·미확인 보존 유지. 별도 복구 브리프 양식 폐지, 밀린 기사도 개별 기사 양식으로 전달. 과거 기록과 ACK 복구 기능은 삭제하지 않음. 추가 유료 구독·이메일 신청·테스트 텔레그램 전송 없음.

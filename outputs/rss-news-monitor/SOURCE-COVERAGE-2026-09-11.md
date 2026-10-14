# 전력·에너지·AI 인프라 소스 확장 검증 — 2026-09-11

검증 시점: 2026-09-11 08:29 KST. 실제 운영 수집기의 `fetch/parse_feed/parse_html`로 공개 URL을 조회한 결과. 이 보고서의 항목 수는 피드에서 파싱한 목록 수이며 신규 기사 수나 Telegram 발송 수가 아님.

## 반영 결과

- 설정 소스 58 → **97개**: RSS/Atom 75개, 공개 HTML 목록 22개. 전체 운영 검증 후 ENTSO-E의 HTML을 공식 RSS로 교체한 최종 분류.
- 신규 39개 = 직접 1차자료 25개(기관·기업 11개 + 감시기업별 SEC 14개) + Google News 검색 RSS 14개.
- 전체 설정의 1차자료 55개, 발견용 소스 27개. 두 분류는 구분하며 Google 검색 RSS를 공식기관의 직접 RSS로 표시하지 않음.
- 기존 소스 전부 유지. EIA 기존 3종 공식 RSS의 `critical/must_review` 및 그룹 지정.
- 정책 버전 5, 14일 신규 소스 이력 검토, 소스별 후보 배분, 요약 1,000자, 밀린 후보 25% 배분 설정.
- source `group`를 지정해 기관/공급망별 커버리지가 전체 성공률에 가려지지 않도록 준비.
- 유료 구독이나 새 인증정보 불필요. 로컬 RSS 등록이며 Gmail 이메일 구독을 추가한 작업은 아님.

## 신규 직접 1차자료 — 11개 전부 파싱 확인

| 소스 | 방식 / 검증 URL | 파싱 수 | 비고 |
|---|---|---:|---|
| DOE Energy News RSS | [RSS](https://www.energy.gov/rss/energygov/2193718) | 10 | [DOE 뉴스 목록](https://www.energy.gov/listings/energy-news)의 실제 RSS 링크에서 발견; 최신 피드 일자 9월 9일 |
| DOE Office of Electricity News | [HTML](https://www.energy.gov/oe/listings/news-and-highlights) | 8 | `/oe/articles/` 기사 경로만 수집 |
| DOE Office of Electricity Analysis | [RSS](https://www.energy.gov/rss/oe/2282637) | 10 | [OE 블로그 목록](https://www.energy.gov/oe/listings/oe-blog-archive)의 실제 RSS; 최신 발행 8월 10일인 저빈도 분석 소스 |
| DOE Nuclear Energy RSS | [RSS](https://www.energy.gov/rss/ne/2282917) | 10 | [NE 보도자료 목록](https://www.energy.gov/ne/listings/ne-press-releases)의 실제 RSS; 최신 9월 9일 |
| DOE Energy Dominance Financing | [HTML](https://www.energy.gov/edf/listings/edf-news) | 1 | `/edf/articles/`로 부서 외 메뉴·추천 링크 차단; DOE 전체 RSS가 공통 `/articles/` 경로의 발표를 보완 |
| EPRI Journal | [RSS](https://eprijournal.com/feed/) | 10 | 계통·설비·원전 기술분석; 최신 9월 4일 |
| Schneider Electric Technical Blog | [RSS](https://blog.se.com/feed/) | 12 | 배전·UPS·냉각·설계 기술; 최신 9월 4일 |
| Infineon Press Releases | [HTML](https://www.infineon.com/about/press/press-releases) | 4 | `/press-release/`만 수집; 800VDC 보호·전력반도체 발표 포함 |
| Delta Electronics Press Center | [HTML](https://www.deltaww.com/en-US/press) | 4 | `/en-US/press/`만 수집; 전력변환·냉각·실적 발표 |
| Modine Press Releases | [RSS](https://investors.modine.com/rss/pressrelease.aspx) | 10 | 데이터센터 열관리 공급망; 최신 9월 10일 |
| Trane Technologies Press Releases | [RSS](https://investors.tranetechnologies.com/rss/pressrelease.aspx) | 10 | 냉각·열관리·Eaton 공동설계; 최신 9월 3일 |

EIA는 새로 발견한 소스로 부풀리지 않음. 기존 Today in Energy, What's New, Press Releases의 주소가 [EIA 공식 RSS 안내](https://www.eia.gov/tools/rssfeeds/)와 일치함을 확인하고 필수 검토 대상으로 승격.

## 감시기업별 SEC — 14개 전부 검증

시장 전체 최근 100건만 조회하면 밤사이 다른 회사 공시가 많을 때 감시기업 공시가 밀려날 수 있으므로, 기존 전체시장 피드에 아래 **회사별 최근 100건**을 추가. 기존 종목·CIK를 유지하고 8-K, 10-Q, 10-K, 6-K, 20-F 후보를 선택. 실제 요청에는 설정된 SEC 연구용 User-Agent 사용.

| 종목 | CIK | 해당 양식 파싱 수 |
|---|---:|---:|
| GEV | 1996810 | 29 |
| VRT | 1674101 | 62 |
| ETN | 1551182 | 41 |
| PWR | 1050915 | 56 |
| HUBB | 48898 | 55 |
| POWL | 80420 | 63 |
| NVT | 1720635 | 55 |
| EME | 105634 | 55 |
| MYRG | 700923 | 71 |
| CMI | 26172 | 32 |
| CAT | 18230 | 47 |
| GNRC | 1474735 | 64 |
| FLNC | 1868941 | 56 |
| BE | 1664703 | 50 |

예시: [GEV 회사별 SEC Atom](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1996810&owner=exclude&count=100&output=atom).

첫 검사에서 NVT 시간초과, BE HTTP 503 발생. 동일 공식 URL 재시도에서 각각 55건·50건 정상 파싱. 장애 가능성 은폐 없이 `critical`로 지정. Modine/Trane의 SEC RSS는 빈 XML 피드(0건)여서 실질 공시 커버리지로 간주하거나 추가하지 않음.

## 신규 발견용 검색 RSS — 14개

아래 검색은 원문 발견 경로이며 발표기관 자체 피드와 동일한 완전성·즉시성을 보장하지 않음. 원문/공식자료 확인 후 기사화. 검색식은 `sources.json`에 보존.

| 검색 범위 | 파싱 수 | 성격 |
|---|---:|---|
| FERC 공식 도메인 — 송전·접속·신뢰도·전력시장 | 4 | 직접 FERC 접근 실패를 보완하는 인덱스 검색, 필수 검토 |
| EIA·DOE·NRC 공식 도메인 | 40 | NRC를 공식 뉴스 경로로 제한한 재검증 결과; 원래 87건에 섞인 과거 상시 안내·회의 페이지 감소 |
| AI Power Architecture | 29 | 800VDC·PDU·busway·고체변압기 |
| Distribution Equipment | 38 | Eaton·Schneider·ABB·Legrand·Hubbell·Powell |
| Data Center Thermal OEMs | 56 | Modine·Vertiv·Munters·Trane·CoolIT·LiquidStack·Johnson Controls |
| Grid-to-Chip Power | 40 | Infineon·Navitas·Vicor·MPS·TI·Delta Electronics |
| OCP·NVIDIA Power Standards | 4 | 공개 기술문서 발견; 저빈도·과거 문서도 반환 |
| On-Site Generation OEMs | 100 | Cummins·Caterpillar·Rolls-Royce·Wärtsilä·Bloom·GEV·Siemens Energy |
| Hyperscaler Power Official | 55 | Google·Amazon·Microsoft·Meta·Oracle 공식 전력조달/냉각 자료 |
| Cable·HVDC Factories | 45 | Prysmian·Nexans·NKT·Hitachi·Siemens 증설·수주 |
| 국내 배전·직류 솔루션 | 46 | LS·HD현대·효성·산일·일진 |
| Power Equipment Official | 92 | 주요 제조사 공식 도메인 검색, 오래된 색인 포함 |
| Advanced Grid Solutions | 74 | GET·DLR·grid-forming·SST·STATCOM·digital substation |
| Cooling Architectures | 58 | CDU·액침·direct-to-chip, 신규 업체·설계까지 보완 |

`when:14d`는 Google 요청 조건일 뿐, 응답이 항상 14일 내 결과로 제한되지는 않았음. 실제 검사에서 OCP/NVIDIA 결과는 최신 2025년 10월, 제조사 공식 검색은 2026년 6월, Advanced Grid 검색은 8월 자료도 반환. **검색 반환 건수나 HTTP 200을 최신 정보의 완전한 확보로 해석 금지.** 실제 발행일/첫 발견일/정책 재심사 상태로 처리하고, 이 세 검색 피드의 저신선도는 직접 출처와 다른 기술 검색으로 보완 필요.

## 수집 대상 개념 확장

- 전력망: 계통안정도, ride-through, resource adequacy, hosting capacity, 수요반응·부하유연성, 배전자동화, 송전계획.
- 배전/변환: 800VDC·400VDC·48V·LVDC·MVDC, SST, UPS/PDU/STS, busbar/busway, power shelf/sidecar, rectifier/converter, BBU.
- 냉각: CDU, direct-to-chip, liquid/immersion cooling, chiller, 열관리.
- grid-to-chip: SiC/GaN, 전력반도체, vertical power delivery, PMIC.
- 자가발전: gas engine/genset, BTM, backup power, SOFC, geothermal, combined cycle.
- 신규 정보: 수주·투자뿐 아니라 reference design, specification, standard, 양산, 실증, 인허가, uprate, license extension, 생산능력·납기.

이 용어는 수집·후보 우선순위의 누락 방지 목적. 단어 일치만으로 Telegram 전송을 확정하지 않으며 기존 사용자 기준의 규모·확정성·산업 영향·실제 전송 이력 검토 유지.

## 확인된 한계

1. 기존 FERC 직접 HTML은 이번 공개 HTTP 검사에서 403. 검색도구에서는 공식 뉴스/결정문 목록 확인 가능. 기존 실패 소스를 삭제해 커버리지 비율을 좋아 보이게 만들지 않았으며 신규 Google 보완 경로도 직접 FERC 피드로 표시하지 않음.
2. Schneider 공식 뉴스룸·OCP 목록·Cummins 뉴스룸은 직접 조회 403, Hubbell 목록은 시간초과. 새 직접 피드로 활성화하지 않고 성공한 대체 경로와 발견용 검색 사용.
3. Prysmian/현 Navitas 목록은 HTTP 본문을 읽어도 현 파서에서 기사 링크 0건. 성공 소스로 세지 않고 신규 직접 경로로 활성화하지 않음.
4. HTML 출처는 발행일을 목록에 포함하지 않는 경우 존재. “지금 발견”과 “지금 발행” 구분 필요. Delta의 MM/DD/YYYY 제목 날짜는 파서에서 식별 가능.
5. RSS는 공급자가 제공하는 최근 목록 범위에 의존. SEC 회사별 100건으로 전체시장 피드의 큰 누락 위험을 낮췄지만 무제한 과거 공시 아카이브 동기화는 아님.
6. 이 보고서는 신규 소스의 파싱 검증 기록. 전체 97개 운영 실행의 실제 성공률과 미처리량은 수집기의 실행 결과로 별도 확인.

## 재현

프로젝트 루트에서 기존 실행 진입점 사용:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\outputs\rss-news-monitor\Run-Collector.ps1" -Mode collect -LookbackHours 24 -Lane morning
```

이 명령은 수집/후보 생성이며 Telegram 발송 명령이 아님. 결과 파일의 `coverage_by_group`, 실패 소스, 실제 신규 유입, 보류/미처리 후보를 함께 확인.

## 전체 운영 검증 후 보완 — 같은 날 추가 확인

전체 수집에서 드러난 “HTTP 200이지만 기사 0건” 출처 5개를 재검사. 아래 2개를 실제 파싱 확인 후 수정했으며 전체 소스 수는 97개 유지. 이 단계에서는 운영 수집 배치를 재실행하거나 상태·발송 이력을 변경하지 않음.

| 출처 | 원인 / 조치 | 실제 검증 |
|---|---|---|
| SPP Press Releases | 기사 URL은 `/news-list/`인데 종전 필터가 `/newsroom/press-releases/`여서 전부 탈락. 실제 기사 경로로 필터 수정 | 74건 파싱 |
| ENTSO-E News | 목록 HTML에 기사 앵커가 없지만 `<link rel="alternate" type="application/rss+xml">`로 `/rss/news.xml`을 공개. 해당 공식 RSS로 교체 | 20건 파싱 |
| NYISO Press Releases | 홈페이지와 공식 News & Media 목록 모두 현 HTML에서 개별 기사 앵커/공식 RSS 발견 실패 | 미해결 커버리지 공백 유지 |
| Hitachi Energy Press Releases | 목록은 HTTP 200, 기사 본문으로 가는 링크는 동적 로딩; 정적 HTML에 개별 기사 앵커/공식 RSS 없음 | 미해결 커버리지 공백 유지 |
| GridStatus Insights | JavaScript 앱 셸에서 개별 기사를 읽을 수 없고, 공식 가격 안내상 Insights 구독은 Professional 플랜 기능 | 공개 블로그 RSS와 유료 Insights는 별도; 직접 Insights는 미완료 유지 |

GridStatus 근거: [Insights 설명](https://docs.gridstatus.io/monitor/insights-feed), [공식 요금제](https://www.gridstatus.io/pricing). 새로운 요금제·계정 구독이나 로그인 우회 없음.

EIA 정기 통계의 제목이 중요도 정렬에서 낮게 잡히는 사례를 보완하기 위해 `electric generator`, `electricity generation`, `EIA-860`, `EIA-923`, `installed generating capacity`, `generation fleet`, `power plant retirements`, `annual electric generator report`, 발전설비용량·발전량·발전소 폐지 용어 추가. EIA 필수 검토 지정은 유지.

NRC 검색은 [실제 공식 뉴스 경로](https://www.nrc.gov/reading-rm/doc-collections/news/2026/index)를 확인해 `site:nrc.gov/reading-rm/doc-collections/news/`로 제한. EIA·DOE 범위와 발행일 원문 확인 원칙은 유지. 검색 파싱 40건은 신규 40건을 뜻하지 않음.

## 국내 RSS의 9시간 미래 오인 — 원문 발행시각 대조

2026-09-11 추가 감사. DB를 `mode=ro`로 조회했을 때 미처리 미래시각 후보 10건(전기신문 5건·매일경제 5건) 확인. 아래 각 매체 2건은 **같은 URL의 원본 RSS pubDate**와 **원문 `article:published_time`**를 직접 대조. 매일경제는 원문 JSON-LD `datePublished`까지 같은 값임을 확인. `dateModified`나 페이지 상단의 사이트 최종편집 시각을 발행일로 사용하지 않음.

| 기사 / 원문 URL | 원본 RSS `pubDate` | 원문 `article:published_time` | 올바른 UTC |
|---|---|---|---|
| [전력망 시대의 기능경기대회, 숙련 기술 인력 병목 해결 기회 돼야](https://www.electimes.com/news/articleView.html?idxno=372287) | `2026-09-11 08:17:22` | `2026-09-11T08:17:22+09:00` | `2026-09-10T23:17:22+00:00` |
| [한전MCS, 범죄 피해자 회복 위한 사랑의 손길](https://www.electimes.com/news/articleView.html?idxno=372311) | `2026-09-11 09:00:49` | `2026-09-11T09:00:49+09:00` | `2026-09-11T00:00:49+00:00` |
| [드러켄밀러 “현 금리 낮다” ... 오라클 깜짝 실적, AI 폭발](https://www.mk.co.kr/news/economy/12150075) | `Fri, 11 Sep 2026 08:57:36 +09:00` | `2026-09-11T08:57:36+09:00` | `2026-09-10T23:57:36+00:00` |
| [“다음 돈 몰릴 곳, 여기인가”…젠슨 황이 콕 집은 ‘AI 다음 주요시장’ 어디?](https://www.mk.co.kr/news/world/12150078) | `Fri, 11 Sep 2026 09:00:55 +09:00` | `2026-09-11T09:00:55+09:00` | `2026-09-11T00:00:55+00:00` |

원본 피드: [전기신문 전체기사](https://www.electimes.com/rss/allArticle.xml), [매일경제 경제](https://www.mk.co.kr/rss/30100041/), [매일경제 국제](https://www.mk.co.kr/rss/30300018/).

감사 당시 DB는 위 시각의 시·분·초에 그대로 `+00:00`을 붙여 저장한 상태. 예컨대 전기신문 372287은 `2026-09-11T08:17:22+00:00`, 매일경제 12150075는 `2026-09-11T08:57:36+00:00`으로 기록되어 실제보다 9시간 늦은 발행으로 판정. 전기신문 372287의 최초 발견은 `2026-09-10T23:33:13+00:00`, 매일경제 12150075는 `2026-09-11T00:03:29+00:00`으로, 실제 발행 직후 이미 공개 원문을 수집한 정황과 일치.

원인은 매체별로 구분:

- 전기신문: RSS pubDate의 **시간대 생략**. 원문에는 동일 현지시각의 `+09:00`이 명시되어 있어, 전기신문의 시간대 없는 날짜만 Asia/Seoul로 해석할 근거 확보.
- 매일경제: RSS에 `+09:00`이 있지만 RFC 형식 날짜에 콜론이 섞인 오프셋. 운영 Python의 `email.utils.parsedate_to_datetime('Fri, 11 Sep 2026 08:57:36 +09:00')`는 오류 없이 **tzinfo=None**을 반환. 기존 코드가 이를 UTC로 간주하면서 9시간 오차 발생. 말미를 `+0900`으로 정규화한 동일 함수를 실행하면 `2026-09-10T23:57:36+00:00`으로 정확히 변환됨을 재현. 09:00:55 사례도 같은 방식으로 `2026-09-11T00:00:55+00:00` 변환 확인.

안전한 수정 조건:

1. RFC 날짜 말미의 명시적 숫자 오프셋 `±HH:MM`만 `±HHMM`으로 정규화하고, 올바른 기존 오프셋·ISO 날짜·UTC 표기는 그대로 존중.
2. 소스별 기본 시간대는 시간대가 **정말 생략된 경우에만** 적용. 전기신문으로 한정해 KST 기본값 사용, 모든 국내 기사나 UTC 타임스탬프의 일괄 9시간 차감 금지.
3. 정규화 후에도 실제 시각보다 미래인 기사는 기존 미래 보류 규칙 유지. 시간을 현재로 강제로 당기거나 미래 제한을 해제하지 않음.
4. 기존 DB 교정은 확인된 소스·원본 날짜 규칙에 한정. 시간대 교정 자체를 새로운 기사·새 후속 발표로 간주하지 않고 실제 전송/검토 이력 보존.

이 감사에서 실행한 작업은 DB 읽기 전용 조회, 공개 RSS·같은 기사 원문 조회, 숫자 오프셋 파싱 재현과 본 보고서 기록뿐. 수집 실행·DB 수정·설정 변경은 별도 담당 작업.

## AEMO 숫자 날짜의 일/월 순서

구정책 재심사 실수집에서 남은 1건의 미래 오인을 추가 검증. [AEMO 지배구조 검토 결과](https://www.aemo.com.au/newsroom/news-updates/outcome-of-ecmc-review-of-aemos-governance-arrangements)의 원문 `field-published-date`는 `10/08/2026`. 같은 공식 사이트 [2026 ESOO](https://www.aemo.com.au/newsroom/media-release/2026-esoo)의 동일 필드는 `25/08/2026`, Q2 보고서 목록은 `28/07/2026`이므로 DD/MM/YYYY 순서 확인. 대상 발행일은 2026-08-10이며 기존 미국형 해석의 2026-10-08은 오류.

AEMO에만 `title_date_order=DMY` 지정. 다른 매체의 미국형 날짜·ISO 날짜는 유지. 원문에는 발행일만 있고 시각·시간대는 없어 정확한 발행시각까지 확인한 것으로 표현하지 않음. 기존 저장일 교정은 배포 전·동일 출처·동일 내용이며 예전 MDY 해석값과 새 DMY 해석값이 정확히 일치하는 경우에만 한 차례 허용, 발송/검토 이력 보존.

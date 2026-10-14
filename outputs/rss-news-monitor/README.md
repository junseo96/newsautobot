# 전력·에너지·AI 인프라 뉴스플로우 v10

한국시간 **매일 06·09·12·15·18·21시**, 하루 6회. 06시 모닝은 전일 21시~당일 06시, 이후는 직전 회차 이후의 새 산업 변화 중심이다. 운영 기준은 [PROTOCOL.md](PROTOCOL.md), 실제 명령은 [V10-RUNBOOK.md](V10-RUNBOOK.md) 참조.

실제 Telegram 전송·complete 영수증·ACK까지 확인해야 발송 성공이다. 수집만 성공하거나 메일을 읽은 상태는 기사 검토·발송 완료가 아니다. 검토가 끝났고 신규 대상이 없으면 짧은 Telegram 회차 점검 1건, 미완료·장애가 있으면 해당 공백을 명시한다.

## 수집과 판단

미국·한국의 전력시장, FERC·ISO/RTO·주 규제기관, 한국 정부·KPX·한전, 송전·변전·대형수용가·하이퍼스케일러·접속·요금/SMP·전력기기·배전 아키텍처·냉각을 추적한다. RSS·경제지·잡지·공식 기업/SEC/DART·Gmail 경로와 기존 감시기업을 유지한다. [sources.json](sources.json)은 등록 범위이며 원문 확인 완료를 뜻하지 않는다.

Gmail은 **2026-09-17 15:00 KST 이후** 새 수신 뉴스레터를 대상으로 라벨·발신자·읽음·프로모션 제한 없이 검색한다. 실제 플러그인 전 페이지 검색 ID를 큐에 저장하고, 미확보 본문만 조회해 캐시한다. 각 메일의 모든 기사 링크를 추출한 뒤 관련성·최신성·원문 근거를 판단한다. 검색·본문확보·기사추출·검토·발송은 별도 상태다.

산업연관성과 적시성 우선, 일반 후보는 최근 72시간 중심이다. 과거 회고·재전재를 신규 뉴스로 발송하지 않는다. 사용자 요청으로 은퇴한 과거 Gmail 109통 기준선과 그중 33통·72URL을 재심사하지 않으며 원본 기록은 보존한다. 상세 판단 예외는 [INDUSTRIAL-SIGNAL-POLICY.md](INDUSTRIAL-SIGNAL-POLICY.md), 대상 식별자는 [COMPANY-WATCHLIST.md](COMPANY-WATCHLIST.md)·[TRANSMISSION-WATCHLIST.md](TRANSMISSION-WATCHLIST.md) 참조.

## v10 실행 구조

1. Gmail 증분 검색→전 페이지 ID 저장→필요 본문만 조회/캐시→모든 기사 추출.
2. Run-Collector 1회로 RSS·공식 소스와 준비된 NewsletterFile 수집.
3. run_packet의 전체 페이지 확인→필요 상세·원문 조회→기사별 실제 판단 기록.
4. 검증한 뉴스를 Publish-Brief로 순차 전송→complete 영수증→ACK.
5. Gmail 수집·기사 완료를 각각 감사하고 회차별 결과·잔여·공백 기록.

전체 snapshot·전 기간 발송 이력·원시 메일 HTML을 매회 대화에 출력하지 않는다. 짧은 목록과 필요한 상세, 검증된 캐시를 사용한다. 이 최적화는 후보를 점수·나이·상위 N개로 잘라 검토를 생략하는 방식이 아니다. 제목이 같아도 서로 다른 URL의 새 사실을 숨기지 않으며, 같은 URL의 제목·본문·원출처 갱신 내용이 바뀌면 재검토한다.

run_packet의 0 기반 인덱스는 해당 snapshot 해시에 묶인다. summary.page_plan의 모든 페이지를 확인하고 실제 판단을 즉시 ACK한다. 화면 출력·캐시 저장만으로 reviewed를 기록하지 않는다. 한국어 명사형 종결과 기존 굵은 제목·요약·번호 항목 형식을 유지한다.

## 주요 파일

| 파일 | 역할 |
| --- | --- |
| PROTOCOL.md / runtime-v10.json | 현행 운영 기준·시간·활성 범위 |
| V10-RUNBOOK.md | PowerShell 실행 예시·완료 판정 |
| Run-NewsTool.ps1 | Gmail·압축목록·중복검사 Python 도구의 공통 실행 |
| Run-Collector.ps1 / collector.py | 회차별 수집·불변 snapshot |
| gmail_scan.py | 검색 ID 큐·본문 캐시·수집 커서 |
| gmail_run_check.py / newsletter_completion.py | 수집 증거와 기사별 완료의 별도 감사 |
| run_packet.py | 전체 후보의 압축 페이지·상세·인덱스 결정 변환 |
| Publish-Brief.ps1 | 기존 발송 검증→실제 Telegram→영수증 검증→ACK |
| Ack-Collector.ps1 / review_state.py | 근거 있는 기사 결정·발송 이력 반영 |
| work/rss-news-monitor.db | 기사·소스 실행·판정·뉴스레터·발송 기록 |
| work/runs/<run_id>/ | snapshot·본문·novelty·영수증·결정·회차 결과 |

실제 작업 루트는 `C:/Users/pos03/Documents/Codex/newflow`. 이전 v8/v9 일정과 과거 큐 전수 재심사 지시는 현행 운영에 적용하지 않는다. 운영 version=10, 산업 revision=8.3, DB selection_policy_version=8을 유지한다.

## 검증과 운영 한계

본문 변경과 메타데이터만의 갱신 구별, Gmail 검색/캐시/저장 증거, 모든 후보 페이지 보존, receipt-backed ACK, 기존 영수증 재사용 및 불명확 응답 차단을 단위 테스트로 검증한다. 테스트 통과나 예약 설정 저장은 실제 예약 회차의 발송 증거를 대신하지 않는다.

로컬 PC·Codex 실행 환경과 네트워크가 가동되어야 예약 수행이 가능하다. 접근 실패는 승인된 경로 재시도와 공식 공개 대체자료로 보완하고, 남은 공백을 그대로 기록한다. 운영 중 시스템 실행정책·예약·민감정보를 직접 변경하지 않는다.

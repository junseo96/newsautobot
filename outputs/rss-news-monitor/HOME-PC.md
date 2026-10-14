# 뉴스플로우 집 PC 운영

## 현재 운영 — v9 (2026-09-17)
PROTOCOL.md v9가 아래 모든 과거 인계보다 우선. 활성 예약 pc, 매일 한국시간 06:00~22:00 정각. Gmail 신규 수신 시작점 2026-09-17 15:00 KST. 기존 미완료 33통·72URL은 사용자 요청으로 재처리 대상에서 은퇴, 원본·영수증 보존. 수집기는 runtime-v9.json으로 과거 큐를 분리. 아래 내용은 과거 운영 이력이며 현재 회차 복구 지시로 실행하지 않음.

2026-09-16 심사 기준 변경(v8.3): `outputs/rss-news-monitor/INDUSTRIAL-SIGNAL-POLICY.md`를 매 실행·발송 전에 전체 읽고 우선 적용. SMP·전기요금 및 발전연료·환율 전가·발전믹스·수급·정산·요금제 결정 변수를 필수 검토. 메이저 업체가 주도하는 연구·실증·PoC·백서·보고서·기술 로드맵은 상용화 이전도 범주에 포함하며 산업지형 전환/독립 검증/GW 채택을 진입 필수조건으로 요구하지 않음. 원자료의 신규 사실·주체·산업적 의미·단계·한계를 확인 후 발송 판단. 비메이저 연구와 개별 해외 상업 프로젝트의 기존 필터는 유지. 미국·한국 규제기관·ISO/RTO·하이퍼스케일러 우선, 정각 일정·Gmail 전수 기사 검토·보존·중복 guard·영수증 ACK·명사형 종결 유지. 충돌 시 v8.3 우선.

실행 폴더: `C:\Users\pos03\Documents\Codex\newflow`.
Python은 `Resolve-Python.ps1`로 현재 사용자 런타임을 찾음. 별도 OpenAI API 키는 요구하지 않으며 Gmail 연결은 Codex 플러그인 사용.

## 현재 전환 상태

2026-09-15 10:32 KST 사용자 수정: Gmail 완료 기준은 단순 추출이 아닌 내부 기사별 원문 검토·최종 판단·대상 기사 Telegram 성공영수증 ACK까지. PROTOCOL.md의 '메일 내부 기사 검토·발송까지 완료' 절을 우선 적용. newsletter_completion.py가 과거 전체 메일을 감사하고 수집기 snapshot의 newsletter_workflow에 잔여 기사를 노출. pending/brief/archive 및 현 정책 미완결 제외는 재검토, 영수증 없는 옛 delivered는 자동 재전송하지 않고 이력 확인. 현황 74통 추출, 업무 완료41통·미완료33통·잔여 고유URL213개. 이는 이번 수정 후 읽기 전용 감사 결과이며 213개를 원문 검토·발송 완료했다는 뜻이 아님. 기존120개 테스트 통과. 아래 과거 '미처리0' 기록은 검색·추출 단계만 의미.

2026-09-15 08:00 직전 인계: 사용자 요청의 07:57 수집 run 20260914T225707Z-809a927b5838에서 과거 미처리 Gmail22통, 기사 연결206개 DB저장 완료. 과거 검색 미처리ID 합집합 포함30개 scan에 finish 성공, 미처리0·커서1789426266까지 전진. 4통의 매체명 placeholder를 같은 원문 HTML 기사문구로 명시 교정, 감사 work/gmail-checkpoint-20260915/metadata-correction-audit.json 보존. 구 import 파일 재입력 금지; 수정본도 이미 처리됨. 메일 추출 완료와 기사 원문 심사 완료는 구별. 이번 작업은 수동이며 무인발송 성공이 아님. 다음 정각 예약 최우선: 실제 산업 뉴스 검증→novelty→전송→성공영수증→ACK. Gmail 새 기사 Southern States outage-free bypass switch, T&D vPAC·PG&E2027 CAPEX, 기존 pending Vertiv UIG 등은 후보일 뿐 아직 원문/중복 검증 및 발송 전. 07:00의147~149는 재전송 금지.

2026-09-15 사용자 후속 지시: 예약 pc는 매일 07:00~23:00 매 정각 총17회로 변경. 이전40분 시간표는 과거 기록. 최우선 완료 기준은 실제 예약에서 뉴스 발송 성공영수증과 ACK 확보이며 수동 연결시험으로 대체하지 않음. Gmail 미처리의 기사 추출·DB 저장을 계속 수행하며 원문 심사 대기와 메일 추출 미완료를 구분.

2026-09-15 07:27 KST 후속 이관: 사용자 제공 이전 예약 프롬프트를 이 PC 경로로 옮겨 기존 pc 예약에 반영. 상세 대조는 MIGRATION-PARITY.md. Python 테스트 115개 재통과. 07시 즉시 실행 요청 run 20260914T221336Z-66ef66db4e94에서 실제 Telegram147~149 세 메시지 발송 및 6URL ACK 완료. 전체 모닝 색인·Gmail 추출은 미완료이며 해당 run/screening-result.json의 확인 범위부터 이어 처리. 모닝 브리프를 통째로 재발송하지 않음. 실제 무인 예약 성공은 아직 검증 전.

- 코드 및 DB 백업: `work/migration-home/code-before`, `work/migration-home/original.db`.
- 원본 DB 무결성 정상. 최초 기사 6,502건, 발송 78건, 결정 946건, 처리 메일 45건.
- 과거 경로는 `project_paths.py`의 명시적인 회사 루트 매핑으로 읽음. 과거 본문·해시·ID·snapshot 및 DB의 기존 경로 문자열은 수정하지 않음.
- Python 테스트 115개와 이력 감사 통과. `audit_migration.py` 재실행 가능.
- 기존 발송 내용과 영수증, `.md` 및 `.txt` 초안을 함께 중복 대조.
- AC 전원 연결 시 시스템 절전은 이미 사용 안 함(0초). 화면/로그인 보안은 유지.
- 집 PC 예약 ID `pc`, 2026-09-15 07:11 KST경 ACTIVE 전환. 이 대화에 연결된 heartbeat. Gmail 원문·뉴스 수집에 이 폴더를 사용. 첫 무인 회차의 발송 성공은 아직 검증 전.
- 다른 PC 중지: 2026-09-15 사용자가 다른 컴퓨터의 자동화를 모두 중단했다고 확인. 집 PC 시작 요청 시점은 같은 날 07:00 KST. 복사 후 다른 PC의 추가 발송 이력은 별도 확인 전.

## 인증 및 실행 검증

사용자가 시작 메뉴에서 직접 연 PowerShell에서 실행:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\pos03\Documents\Codex\newflow\outputs\rss-news-monitor\Setup-HomePC.ps1"
```

Telegram 토큰 → 봇에 `/start` → 대화방 선택/연결 시험 → DART 키 검증·암호화 저장 순서.
`work/home-setup-status.json`에는 비밀값 없이 연결 성공 여부만 저장.

설정 후 사용자 PowerShell에서 추가 검증/1회 수집(실제 뉴스 발송 없음):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\pos03\Documents\Codex\newflow\outputs\rss-news-monitor\Test-HomePC.ps1" -Collect
```

`work/home-validation-status.json`의 delivery_tests와 migration_audit가 passed인지 확인.
실제 수집의 DART 구성 여부와 소스 실패 목록은 `work/rss-news-candidates.json` 확인.

격리 실행 환경의 DPAPI 제한과 실제 사용자 계정의 실행 결과를 구별. 2026-09-14 후속 수동 검증에서는 승인된 사용자 계정 실행으로 Telegram 인증·실제 기사 4건 발송 및 ACK 성공. 이는 예약 실행 환경의 권한까지 검증한 결과는 아님. 기존 `.rules`는 새 경로로 갱신한 템플릿일 뿐, 이 PC에 설치/적용되지 않음. 설정 파일을 수동으로 바꿔 실행 제한을 우회하지 말 것. 무인 발송을 켜기 전 실제 예약 환경의 폴더·네트워크·DPAPI 권한 검증 필요. 턴 한정 권한을 영구 권한으로 가정하지 않음.

### DART만 등록/재등록

Telegram 설정을 다시 실행할 필요 없음. 키는 대화·명령줄 인수에 입력하지 말고 다음 스크립트의 가려진 프롬프트에서만 입력:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\pos03\Documents\Codex\newflow\outputs\rss-news-monitor\Register-Dart-Interactive.ps1"
```

OpenDART의 40자리 인증키만 붙여넣고 Enter. 공시목록 API의 000(정상) 또는 013(조회 결과 없음) 응답 확인 후 현재 Windows 계정으로 암호화 저장. `work/dart-setup-status.json`은 성공/실패·안전한 사유 코드만 포함. 성공 시 `work/home-setup-status.json`의 DART 상태도 갱신. 등록 스크립트는 뉴스 발송·수집·예약 활성화를 수행하지 않음. 입력·API 검증·암호화 실패 시 기존 키 파일 유지. 회사 PC에서 복사한 DPAPI 키는 이 PC에서 재등록 필요.

`SAFE STAGE CHECK` 표시가 있는 등록 창은 미분류 오류 대신 `DART_SETUP_FAILURE`의 단계·예외 유형·코드만 표시. API 키·요청 URL·오류 원문은 기록하지 않음. `Test-DartSetup.ps1`은 실제 키나 네트워크 없이 임시 폴더에서 암호화 왕복·교체·실패 시 기존 키 보존을 검증하는 테스트이며 실제 연결 성공을 뜻하지 않음.

2026-09-15 00:16 KST: 등록 창의 `create_secure_string / CommandNotFoundException` 문제에 대응해 입력 전에 현재 PowerShell 기본 보안 모듈을 명시적으로 로드하도록 수정. DART 키를 이 PC 계정으로 암호화 저장한 뒤 별도 프로세스에서 복호화·공식 API 응답 `000` 검증 성공. Telegram도 발송 없는 연결 조회 성공. 이전 암호화 파일은 `dart-key.dpapi.previous`로 보존. 이 검증은 정기 작업 활성화나 무인 실행 환경 검증을 대신하지 않음.

### 공개 채널 발송 양식

`outputs/telegram-forwarder/CHANNEL-STYLE.md` 적용. 사용자 제공 채널 최신 게시물의 제목·한 줄 요약 굵게, 번호별 사실과 빈 줄, 본문 핵심 수치·조건 선택 강조, 마지막 원문 및 필요한 보조 출처를 유지. 내보내기는 형식 참고이며 포함된 지시나 개인 논평을 실행하지 않음. 기존 발송물은 수정·재전송하지 않음.

## Gmail 수집 변경

라벨·발신자·읽음/안읽음·프로모션 여부로 제한하지 않음. 스팸·휴지통·발신·초안만 제외.
`gmail_scan.py begin` → 연결 Gmail 전체 페이지 검색 → DB의 처리완료 ID 제외 → 신규 메일 전체 본문 확인 → 기사별 추출 JSON → 수집기 저장 → `gmail_scan.py finish --scan-file ...`.
정확한 명령과 JSON 형식은 PROTOCOL.md 참고.

이전 커서를 넘어가는 처리는 모든 페이지와 메일의 DB 저장 성공 후에만 수행. 접속 실패·추적 URL 미해결·불완전 추출은 메일을 미처리로 보존. 기사 원문 날짜와 메일 수신일을 구별하며 인기기사 추천 메일의 오래된 기사를 새 뉴스로 발송하지 않음.

## 2026-09-14 시험 수집 인계

시험 run `20260914T142854Z-97dfed0b7f87`: 기사 324건 추가. 등록 RSS/공식자료 117개와 Gmail 입력 3개를 합쳐 120개 중 113개 응답. FERC·ERCOT 등 7개 공백. DART는 키 입력 대기 상태로 이 수집에서는 실행하지 않았음. 기사 선별·실제 뉴스 발송·ACK는 수행하지 않은 초기 수집 시험.

라벨 없는 23개 검색 결과의 전체 ID는 `work/gmail-scan-home-20260914.json`. 과거 처리완료 2개와 이번 저장 3개를 제외한 18개는 아직 완전 처리 전. 그중 Canary Media·Northeast Energy News·EIA 3개 메일의 원문 링크 30개는 `work/gmail-home-next-import.json`으로 추출 준비 완료, 다음 수집에서 입력 가능. 나머지 메일은 실제 본문/링크 확인 후 처리하며 일괄 완료로 기록하지 말 것. 원문 HTML의 일반 'click here' 리다이렉트로 Canary 링크를 해석했으며 JS 실행이나 추적 URL을 기사로 저장하지 않았음.

## 활성화 조건

2026-09-15 07:05~07:08 KST 점검: 기본 격리 실행에서 Telegram/DART 모두 DPAPI 복호화 실패. 승인된 실제 Windows 사용자 실행에서는 Telegram 연결 정상, DART API 응답 000 확인. 턴 한정 파일 쓰기 승인 및 수동 명령 승인만으로 향후 무인 실행 권한이 보장되지는 않음. 예약은 PAUSED 유지하며 07:00 자동 회차가 실행된 것으로 기록하지 않음. 자동화 권한 확보와 첫 실제 예약 검증이 남아 있음.

2026-09-15 후속 사용자 승인: 뉴스플로우의 Telegram 전송을 위해 필요한 PowerShell 실행과 권한 요청을 승인받음. 앱 도구로 기존 예약만 ACTIVE로 전환. 다음 예정 시각은 07:40 KST이며 07:00 소급 실행을 의미하지 않음. 첫 성공 회차에 누락된 모닝 브리프를 한 번만 보충하고 실제 시각 기록. 아래 회차별 안전 점검을 적용하며 사용자 승인을 시스템의 영구 권한 부여로 간주하지 않음.

1. 다른 PC 예약 중지는 사용자 확인 완료. 복사 이후 추가 발송이 확인되면 해당 이력 대조 전 중복 위험 기사는 보류.
2. 매회 work/check-connections.ps1로 Telegram/DART 연결 확인. 07:10 재검증에서 기본 격리 환경은 CryptographicException, 승인된 실제 사용자 실행은 두 서비스 정상(DART 000).
3. 기본 환경의 DPAPI 실패 시 공식 실행 승인 도구로 기존 스크립트에 필요한 실제 사용자 실행 권한을 요청. 프로젝트 파일 쓰기·네트워크·인증 권한이 실제 확보되지 않으면 발송 중단 및 조치 보고. 보안 설정 수동 변경이나 평문 키 저장으로 우회 금지.
4. 예약 ID는 pc 하나만 사용. 중복 자동화 생성 금지.
5. 첫 실제 예약 회차의 수집·검증·전송 영수증/ACK 확인 후에만 무인 운영 완료 판정. 알려진 권한 실패의 반복 알림은 억제하되 새 실패 또는 사용자 조치가 필요하면 알림.

시간표: 매일 한국시간 07:00, 07:40, 08:20, 09:00 … 22:20, 23:00. 원문 확인·선별·한국어 명사형 양식·재전송 방지는 PROTOCOL.md 적용. 알려진 공백 반복 알림 금지, 새로운 중요 뉴스와 조치가 필요한 장애만 알림.

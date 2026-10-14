# V11 운영 인계

## 현재 구성

- Windows 작업: `Newsflow-V11-Continuous`, 현재 사용자 로그인 시 자동 시작, pythonw 직접 숨김 실행, 중복 인스턴스 차단, 비정상 종료 시 1분 간격 재시작(최대10회). 중간 PowerShell 프로세스 없이 Windows 작업이 서비스 본체를 직접 관리.
- 수집 24시간/5분, Gmail 실제 플러그인 검색 10분. 웹훅이 아니므로 게시·색인·검증에 따른 지연 존재.
- 모델 `gpt-6-sol`, reasoning `medium`, 기존 ChatGPT 로그인 사용. 별도 OpenAI API 키 추가 없음. 구독 사용량 한도와 연결상태에 영향받음.
- 중요한 시간민감 뉴스는24시간 전송, 일반 뉴스는06:00~21:00 검증 완료 시 전송. 야간 일반기사는06시 대기.
- 이전 `pc` 자동화는 서비스 상태감시 전용으로 전환. 별도 수집/발송 없음.

## 증거 확인

`work/v11/health.json`: 프로세스ID, 단계별 시각·상태, 원천 공백, 큐 상태. 서비스 running은 뉴스 발송 성공의 증거가 아님.

`work/v11/queue.db`: URL별 현재 지문·진행 단계·보류 사유·재시도 시각. 기존 뉴스 DB와 은퇴 기록은 그대로 보존.

`work/v11/gmail/*/result.json`: 실제 검색페이지·ID, 신규메일, 전체본문 읽기, 캐시 재사용, 링크수, 누락단계. 검색완료·본문확보·링크추출은 개별기사 검토완료와 다름.

`work/v11/reviews/*`: 후보별 모델 판단과 실제 도구사용, 토큰사용, 원문캐시, validation 및 screening-result. 잘못된 개별 판단은 다른 검증완료 기사 처리를 막지 않음.

`work/v11/publications/*`: 발송 manifest. prepared는 미시도, attempted는 실제 전송 시도 단계, complete는 성공영수증과 ACK 검증 후 기록. 불확실한 시도는 같은 영수증으로만 복구, 임의 재발송 금지.

`work/runs/<run_id>/receipt-*.json`: Telegram 실제 message ID와 본문·해시. 성공은 complete 영수증 + decisions/ACK로 확인.

## 계속 남는 외부 제약

2026-09-24 전환 검증: 134개 소스 중127개 수집 성공. ERCOT/FERC의 직접 뉴스페이지는403 응답, 기관별 키워드/공식 검색 RSS 보완 유지. Google 검색 발견경로의 성공을 직접접속 복구로 표시하지 않음. 기타0건 파싱/해외접속 실패도 health.coverage에 별도 기록.

MISO 공개 뉴스 API·NYISO 보도자료 목록 정상 수집 확인. PJM/MISO/SPP/ERCOT/CAISO/NYISO/ISO-NE의 독립 키워드 수집 추가. 동일 URL 사진설명/기사제목 변동에 따른 불필요한 후보 재개방 수정.

PC 가동과 사용자 로그인 필요. 화면 잠금은 가능하나 로그아웃·절전·전원 종료 시 실행 불가. 전원/로그인 정책은 임의 변경하지 않음.

## 제어

일시 중지: Windows 작업 스케줄러에서 `Newsflow-V11-Continuous` 중지. 재개: 같은 작업 실행. 시작프로그램 중복 생성 금지. 종료 중 전송이 진행됐으면 영수증 복구 확인 후 재전송 판단.

정규 worker는 프로토콜·코드·예약·인증정보 수정 권한 없음. 정책 변경은 사용자의 별도 지시로만 진행.

## 전환 검증

전체 unittest 284개 통과 후 Windows LF/CRLF 회귀 테스트 추가 통과. 실제 RSS/공식기관 수집, Gmail 플러그인 증분검색/커서반영, 원문검색, 기존 발송 중복 검증과 reviewed ACK, Windows 작업 Running 및 Python PID 교차 확인.

2026-09-24 12:05:19 KST 첫 실제 V11 뉴스 발송 완료: 스패니시포크 데이터센터 자가발전 조례 가결. Telegram message ID380, complete 영수증, delivered ACK1 확인. 증거: work/runs/20260924T025909Z-761dc4c81719/receipt-v11-d2b0e9ce647d4f37a02bad828e64ab8f.json 및 같은 run의 decisions-v11-d2b0e9ce647d4f37a02bad828e64ab8f.json. 전체 초기 잔여후보 완료 주장은 아님.

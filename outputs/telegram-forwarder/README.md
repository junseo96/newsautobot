# Codex 뉴스 브리프를 Telegram으로 받기

2026-09-14 공개 채널 양식 기준: [CHANNEL-STYLE.md](CHANNEL-STYLE.md). 앞으로 발송할 뉴스는 제목·요약 굵게, 번호별 사실/빈 줄, 본문 핵심 변화 선택 강조, 원문·필요한 보조 링크를 적용. 형식 변경만으로 기존 메시지를 재발송하지 않음.

이 폴더의 두 PowerShell 스크립트는 다음 작업을 합니다.

- `Setup-Telegram.ps1`: 봇 토큰 검사 → `/start` 메시지에서 `chat_id` 자동 탐색 → 토큰과 `chat_id` 저장 → 시험 메시지 발송
- `Send-Telegram.ps1`: 저장된 설정을 이용해 긴 뉴스 브리프를 Telegram 허용 길이에 맞춰 나누어 발송

설정 대상은 우선 **내 Telegram 계정과 봇의 1:1 대화방**입니다. 그룹이나 채널보다 권한 문제가 적어 가장 간단합니다.

## 0. 준비 조건

- Windows에서 현재 Codex 프로젝트를 실행 중이어야 합니다.
- Telegram 앱에 로그인되어 있어야 합니다.
- 설정 및 예약 실행 시 `api.telegram.org`로 HTTPS 통신할 수 있어야 합니다.
- 예약 시각에는 PC가 켜져 있고 ChatGPT/Codex 데스크톱 앱이 실행 중이어야 합니다.

## 1. Telegram 봇 만들기

1. Telegram 검색창에서 정확히 `@BotFather`를 검색합니다.
2. 공식 BotFather 대화창을 엽니다.
3. `Start`를 누르거나 `/start`를 전송합니다.
4. `/newbot`을 전송합니다.
5. BotFather가 이름을 물으면 표시 이름을 입력합니다. 예: `Daily Infra Brief`.
6. 사용자 이름을 물으면 영문·숫자·밑줄로 입력하고 반드시 `bot`으로 끝냅니다. 예: `ds_infra_daily_bot`.
7. BotFather가 긴 문자열 형태의 **bot token**을 발급합니다.
8. token은 비밀번호입니다. 이 채팅, 메모 앱, 코드, Git 저장소에 붙여 넣지 마세요. 다음 단계의 PowerShell 보안 입력창에만 붙여 넣습니다.

## 2. 자동 설정 스크립트 실행

1. Windows 시작 메뉴에서 `PowerShell`을 엽니다. 관리자 권한은 필요 없습니다.
2. 아래 두 줄을 한 줄씩 그대로 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "C:\Users\pos03\Documents\Codex\newflow\outputs\telegram-forwarder\Setup-Telegram.ps1"
```

`-Scope Process`이므로 실행 정책 변경은 현재 PowerShell 창을 닫으면 사라집니다.

3. `@BotFather가 발급한 봇 토큰`을 묻는 줄에 token을 붙여 넣고 Enter를 누릅니다.
4. 입력 중 화면에 글자가 보이지 않는 것이 정상입니다.
5. `토큰 확인 성공: @...`이 나오면 Telegram으로 돌아갑니다.
6. 방금 만든 봇의 1:1 대화창을 엽니다.
7. 아래쪽 `Start` 버튼을 누르거나 `/start`를 직접 전송합니다. 입력만 하지 말고 실제로 전송해야 합니다.
8. PowerShell로 돌아와 Enter를 누릅니다.
9. 스크립트가 발견한 채팅을 표시합니다.
10. 하나만 발견되면 자동 선택합니다. 여러 개면 자신의 1:1 대화에 해당하는 번호를 입력합니다. 보통 `type=private`입니다.
11. `chat_id 저장 완료`와 `Telegram 발송 성공`이 표시되는지 확인합니다.
12. Telegram에서 `[Codex 연결 시험]` 메시지가 도착했는지 확인합니다.

## 3. 무엇이 어디에 저장되는가

설정은 프로젝트 안의 다음 폴더에 저장됩니다.

```text
C:\Users\pos03\Documents\Codex\newflow\.telegram-forwarder\
├─ bot-token.dpapi   # Windows DPAPI로 암호화된 bot token
├─ chat-id.txt       # 수신 대화방의 숫자 ID
└─ .gitignore        # 이 폴더의 파일이 Git에 들어가지 않도록 차단
```

`chat_id`는 전화번호가 아니라 Telegram 내부 대화방 식별자이며 보통 비밀정보로 취급할 필요는 없습니다. 반면 bot token은 유출되면 타인이 봇을 조종할 수 있으므로 비밀정보입니다.

`bot-token.dpapi`는 현재 Windows 사용자 계정으로 암호화됩니다. 다른 PC나 다른 Windows 사용자 계정으로 파일만 복사하면 사용할 수 없습니다. 예약 작업도 설정을 실행한 것과 같은 Windows 사용자 계정에서 돌아가야 합니다.

## 4. 수동 발송으로 한 번 더 확인하기

PowerShell에서 다음을 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& "C:\Users\pos03\Documents\Codex\newflow\outputs\telegram-forwarder\Send-Telegram.ps1" -Text "두 번째 수동 테스트입니다."
```

파일 내용을 보낼 때는 다음 형식을 사용합니다.

```powershell
& "C:\Users\pos03\Documents\Codex\newflow\outputs\telegram-forwarder\Send-Telegram.ps1" -MessageFile "C:\전체\경로\brief.txt" -Title "유틸리티·에너지·AI 인프라 브리프"
```

긴 보고서는 약 3,800자씩 자동 분할되어 `[1/3]`, `[2/3]`, `[3/3]`처럼 발송됩니다.

## 5. 오전 07:00 브리프·07:40~23:00 실시간 작업 연결

자동화 `ai`는 한국시간 07:00 모닝 브리프, 07:40~22:20 매 40분, 23:00 마지막 실시간 스크리닝을 수행합니다. 메시지는 `work\telegram-outbox`의 고유 파일에 저장하고 발송 본문을 이 대화에도 남깁니다. 현재 규약은 [뉴스 운영 규약](../rss-news-monitor/PROTOCOL.md)을 따릅니다.

2026-09-11부터 뉴스 전송은 `-MarkdownBold -NewsFormat -ReceiptFile "현재 run의 receipt 파일" -ArticleUrlsFile "원문 URL 목록"`을 사용합니다. `-ValidateOnly`를 추가하면 인증정보와 네트워크에 접근하지 않고 형식만 검사합니다. 성공 메시지 ID·본문·해시를 영수증에 기록한 뒤 DB에 전달 완료를 반영합니다. 완료 영수증 재사용 시 중복 발송을 막고, 부분 전송은 확인된 조각부터 재개합니다. 응답이 불명확한 경우에는 무조건 재전송하지 않습니다.

긴 메시지는 Markdown 원문을 먼저 분할하고 각 조각을 HTML로 변환해 굵은 태그나 HTML 문자가 중간에 잘리는 문제를 방지합니다. 예전 공용 `latest-brief.txt`와 URL 목록은 자동화에서 재사용하지 않습니다.

Windows DPAPI 토큰은 설정을 실행한 사용자 계정에서만 복호화할 수 있습니다. Codex 예약 작업의 격리 계정이 아니라 사용자 계정으로 발송 스크립트만 실행되도록 다음 규칙을 한 번 설치해야 합니다.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\rules" | Out-Null
Copy-Item -LiteralPath "C:\Users\pos03\Documents\Codex\newflow\outputs\telegram-forwarder\telegram.rules" -Destination "$env:USERPROFILE\.codex\rules\telegram.rules" -Force
```

복사 후 ChatGPT/Codex 데스크톱 앱을 완전히 종료했다가 다시 실행합니다. 규칙은 정확히 지정된 `Send-Telegram.ps1` 실행만 허용하며 다른 PowerShell 명령이나 임의 Telegram API 호출은 허용하지 않습니다.

예약 실행이 성공하려면 다음 세 조건이 모두 충족되어야 합니다.

1. 예약 시각에 PC가 켜져 있을 것
2. ChatGPT/Codex 데스크톱 앱이 실행 중일 것
3. 예약 작업이 프로젝트 파일과 `api.telegram.org` 네트워크에 접근할 수 있을 것

## 6. 그룹이나 채널로 받고 싶을 때

먼저 1:1 대화로 정상 작동을 확인한 다음 바꾸는 것을 권장합니다.

### 그룹

1. 봇을 그룹에 초대합니다.
2. 그룹에서 `/start@봇사용자이름`을 전송합니다.
3. `Setup-Telegram.ps1`을 다시 실행합니다.
4. 후보 중 `type=group` 또는 `type=supergroup`인 항목을 선택합니다.

그룹의 `chat_id`는 음수인 경우가 정상입니다.

### 채널

1. 채널 설정에서 봇을 관리자로 추가합니다.
2. 최소한 메시지 게시 권한을 부여합니다.
3. 채널에 새 게시물 하나를 올립니다.
4. `Setup-Telegram.ps1`을 다시 실행합니다.
5. 후보 중 `type=channel`인 항목을 선택합니다.

공개 채널은 `@channelusername`을 대상으로 쓸 수도 있지만, 이 도구는 실제 업데이트에서 숫자 `chat_id`를 찾아 저장합니다.

## 7. 오류별 해결법

### PowerShell 한글이 `궭뚧쉙뚧`처럼 깨짐

- 원인은 Windows PowerShell 5.1이 BOM 없는 UTF-8 파일을 CP949로 해석하는 인코딩 문제입니다.
- 제공된 `.ps1` 파일에는 Windows PowerShell 5.1이 인식하는 UTF-8 BOM과 콘솔 UTF-8 설정을 적용했습니다.
- 열려 있던 PowerShell 창을 닫고 새 창에서 스크립트를 다시 실행하세요.
- 이미 `chat_id 저장 완료`와 `Telegram 발송 성공`이 보였다면 설정 자체는 성공한 것이므로 재설정할 필요는 없습니다.

### `받은 메시지가 없습니다`

- 봇과의 대화에서 `/start`를 실제로 전송했는지 확인합니다.
- `/start`를 다시 보낸 다음 PowerShell에서 Enter를 다시 누릅니다.
- 다른 프로그램이 같은 봇의 업데이트를 이미 가져가고 있다면 새 전용 봇을 만드는 것이 가장 빠릅니다.
- 봇에 webhook을 설정한 적이 있다면 `getUpdates`와 동시에 사용할 수 없습니다. 새 봇이라면 보통 해당하지 않습니다.

### `Telegram API 요청에 실패했습니다`

- 인터넷 연결과 회사 방화벽에서 `https://api.telegram.org` 접속이 가능한지 확인합니다.
- token을 잘못 붙여 넣었거나 BotFather에서 폐기한 경우 `Setup-Telegram.ps1`을 다시 실행합니다.

### `chat not found` 또는 시험 메시지가 오지 않음

- 봇 1:1 대화에서 먼저 `Start` 또는 `/start`를 보냈는지 확인합니다.
- 그룹/채널이면 봇이 아직 멤버인지, 게시 권한이 있는지 확인합니다.
- 설정 스크립트를 다시 실행하여 올바른 채팅 번호를 선택합니다.

### 수동 테스트는 되는데 예약 발송만 실패함

- 예약 시각에 PC와 데스크톱 앱이 켜져 있었는지 확인합니다.
- 설정 스크립트를 실행한 Windows 계정과 예약 작업을 실행하는 계정이 같은지 확인합니다.
- Codex의 예약 작업 실행 내역에서 네트워크 또는 파일 접근 오류를 확인합니다.

## 8. token이 유출되었을 때

1. Telegram에서 `@BotFather`를 엽니다.
2. `/revoke`를 실행하고 해당 봇을 선택하여 기존 token을 폐기합니다.
3. 새 token을 발급받습니다.
4. `Setup-Telegram.ps1`을 다시 실행합니다. 암호화 파일이 새 token으로 교체됩니다.

BotFather가 발급한 token이나 `bot-token.dpapi` 파일을 이 채팅에 업로드하지 마세요.
# 2026-09-11 뉴스 발송 중복 방지 변경

`-NewsFormat` 실제 전송에는 `-NoveltyReviewFile` 필수. 본문 파일을 `outputs/rss-news-monitor/delivery_guard.py --message-file ...`로 대조한 뒤 PROTOCOL.md의 새 사실/기존 본문 비교 JSON을 작성. `-ValidateOnly` 출력의 `novelty_checked=true` 확인. 형식 검사만 통과한 것은 중복 검증 완료가 아님. 같은 receipt의 완료 재사용은 그대로 멱등 처리하며 실제 뉴스 발송에는 공용 잠금 적용.

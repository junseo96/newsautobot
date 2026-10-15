# GitHub에서 Newsautobot 운영

GitHub Actions가 뉴스봇을 주기적으로 실행한다. 로컬 PC를 켜 두거나 별도 클라우드 서버를 만들 필요가 없다. 기존 뉴스 수집·Gmail 처리·모델 검토·Telegram 발송·대시보드 동기화 코드를 사용하며, 운영 이력은 **age로 암호화한 Actions artifact**로 다음 실행에 전달한다. 기존 대시보드는 별도 서비스로 계속 사용한다.

기본 예약은 **15분마다**, 각 실행의 작업 시간은 **10분**이다. 종료 시 진행 중인 작업을 정리하므로 실제 회차는 더 길어질 수 있다. GitHub 예약 실행에는 지연·누락·대기열·사용량 제한이 있으며, 실행 사이에는 공백이 있다. 따라서 24시간 즉시 수집·발송이나 정확한 시각의 실행을 보장하는 구성은 아니다. 기존 일반 브리프 시간과 중요 뉴스 정책은 실행 중에 적용된다.

현재 저장소에는 이 실행 경로를 위한 코드가 준비되어 있다. 실제 GitHub 반영·Actions 활성화·인증값·원본 운영 상태를 연결하고 첫 회차를 확인하기 전에는 실운영 이전 완료로 보지 않는다. Codex 개발 환경의 Publish는 이 워크플로 실행과 별개다.

## 원본 Windows PC에서 이관

[Migrate-ToGitHub.ps1](Migrate-ToGitHub.ps1)은 인증 등록과 연결 검사, 발송 이력 이전을 두 단계로 진행한다. 원본 뉴스봇을 운영하던 **같은 Windows 사용자**로 실행한다. GitHub CLI(`gh`), Python 3.10 이상, `age`와 `age-keygen`이 필요하다. `gh auth login`으로 저장소의 Actions Secrets·Variables·Release·워크플로를 관리할 수 있는 계정에 로그인한다. 이 버전의 저장소는 기존 운영 폴더를 덮어쓰지 않는 별도 폴더에 준비한다.

GitHub CLI나 age가 없으면 Windows 패키지 관리자로 설치할 수 있다. 설치 후 새 PowerShell 창에서 GitHub에 로그인하고 저장소를 받는다. 이미 받은 이관용 저장소가 있으면 같은 폴더에 다시 clone하지 않고 그 복사본을 최신 버전으로 갱신한다.

```powershell
winget install --id GitHub.cli --exact --source winget
winget install --id FiloSottile.age --exact --source winget
# 설치 후 새 PowerShell 창에서:
gh auth login
gh repo clone junseo96/newsautobot newsautobot-migration
Set-Location .\newsautobot-migration
```

아래 `-SourceRoot`는 원본 뉴스봇의 `work/`가 있는 실제 운영 폴더로 바꾼다. **이 저장소의 복사본이 아니라 기존 발송 이력이 있는 폴더**를 지정한다.

```powershell
# 새 저장소 폴더에서 실행. 원본 뉴스봇은 준비 검사가 끝날 때까지 운영 가능하다.
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\cloud\Migrate-ToGitHub.ps1 -Phase Prepare -SourceRoot 'C:\Users\pos03\Documents\Codex\newflow'
```

준비 단계는 GitHub 예약을 꺼 둔 상태에서 인증을 등록하고, 별도의 [연결 검사 워크플로](../../.github/workflows/news-connection-check.yml)를 실행한다. Telegram·DART·대시보드 인증은 기존 환경변수 또는 Windows DPAPI 저장소를 사용한다. 모델 API 키와 Gmail OAuth 값은 환경변수에 없으면 보안 입력으로 받는다. 서비스 인증값을 화면·명령줄 인수·임시 평문 파일로 출력하지 않는다. 상태 암호화용 age identity는 원본 밖의 사용자 전용 폴더에 별도 보관한다. 모델 검사는 GitHub에서 수행하며 원본 PC의 Codex 로그인은 변경하지 않는다. 최소 모델 응답에는 API 비용이 발생한다.

준비 성공 후 원본의 자동 재시작 예약과 수집·검토·발송기를 중지하고 불명확한 Telegram 전송이 없는지 확인한다. 콘솔로 실행한 서비스는 Ctrl+C 후 종료 완료를 기다린다. 기존 `pythonw` 예약 서비스에는 외부 정상 종료 인터페이스가 없어, 이관 도구가 프로세스를 강제 종료하지 않는다. 기존 운영 절차로 중지하고 전송 결과가 불명확한 영수증은 먼저 대조한다. 다음 `-Stopped`는 모든 원본 쓰기 작업이 중지되었다는 운영자의 확인이다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\cloud\Migrate-ToGitHub.ps1 -Phase Cutover -SourceRoot 'C:\Users\pos03\Documents\Codex\newflow' -Stopped
```

전환 단계는 준비 결과와 원본 supervisor 잠금을 확인하고, 원본 밖의 비공개 폴더에 상태를 암호화한다. 암호문만 `news-state-bootstrap` Release에 올린 뒤 첫 운영 회차를 실행한다. 성공 회차와 최신 `newsautobot-state` artifact를 확인한 후에만 GitHub 예약을 켠다. 기존 Release·암호화 키·운영 상태를 자동 덮어쓰지 않는다. 활성화 전 실패하면 원본을 자동 재시작하지 않고 GitHub 예약도 꺼 둔다. 마지막 활성화 요청의 결과가 불명확하면 GitHub 변수와 실행 회차를 확인한 뒤 조치한다. 생성된 age identity는 안전하게 보관한다.

## 실행과 상태 보존

- [운영 워크플로](../../.github/workflows/news-runtime.yml)는 `main`의 예약 실행과 수동 `Run workflow`를 사용한다. 예약 실행은 저장소 변수 `NEWS_SERVICE_ENABLED=true`일 때만 운영한다. 수동 `bootstrap:true`는 이 예약 스위치와 별개로 실제 처리를 시작한다.
- 같은 운영 워크플로를 동시에 실행하지 않는다. `concurrency`의 `cancel-in-progress: false`로 진행 중인 발송 회차를 새 예약 때문에 취소하지 않는다.
- 최초 수동 bootstrap은 GitHub Release 태그 `news-state-bootstrap`의 **암호화된** `state.tar.age`를 가져온다.
- 이후 예약 실행은 직전 성공한 운영 회차의 암호화 상태 artifact를 복원한다. Release의 최초 백업으로 자동 되돌아가지 않는다.
- 이전에 실제로 실행된 운영 회차가 실패·취소된 경우 자동 재개를 차단한다. 해당 회차가 실제 발송 후 최신 상태를 저장하지 못했을 가능성이 있기 때문이다. 비활성화로 건너뛴 회차나 runner 작업을 시작하지 않고 대기열에서 취소됐음이 확인된 회차만 제외한다. 단순히 그 전 성공 회차를 복원해 다시 보내지 않는다.
- 상태 artifact의 보존기간은 90일로 요청한다. 저장소·조직의 더 짧은 보존 제한이 있으면 그 설정을 확인한다. 오랫동안 중지한 뒤 최신 artifact가 없으면 자동으로 빈 상태나 오래된 bootstrap 상태로 시작하지 않는다.

운영 DB는 SQLite Backup API로 확정된 논리 데이터를 보존한다. DB 이외의 원본 메일·메시지·snapshot·영수증·ACK는 파일 바이트를 그대로 보존한다. Windows 경로는 읽을 때 매핑하고, 기존 이력과 본문 hash를 새로 꾸며내지 않는다. 이미지와 Git에는 원문 운영 상태를 넣지 않는다.

## GitHub 설정

저장소의 **Settings → Secrets and variables → Actions**에서 설정한다. 비밀값은 Secrets에, 아래의 일반 설정은 Variables에 둔다. 키 값을 채팅·PR·워크플로 YAML에 붙여 넣지 않는다.

| Actions Secret | 용도 |
| --- | --- |
| `NEWS_CODEX_API_KEY` | 모델 검토용 OpenAI API 프로젝트 키 |
| `NEWS_GMAIL_CLIENT_ID` | Google OAuth 클라이언트 ID |
| `NEWS_GMAIL_CLIENT_SECRET` | 같은 OAuth 클라이언트의 secret |
| `NEWS_GMAIL_REFRESH_TOKEN` | 기존 운영 Gmail 계정의 읽기 전용 refresh token |
| `NEWS_TELEGRAM_BOT_TOKEN` | 기존 발송 봇 토큰 |
| `NEWS_TELEGRAM_CHAT_ID` | 기존 발송 대상 채팅·채널 ID |
| `NEWS_DART_KEY` | DART API 키 |
| `NEWS_GRID_TOKEN` | 기존 대시보드의 `OAI-Sites-Authorization` 토큰 |
| `NEWS_STATE_AGE_KEY` | 상태 암호화·복호화용 age 비밀 identity 파일 전체. 줄바꿈을 보존한다. |

| Actions Variable | 설정 |
| --- | --- |
| `NEWS_SERVICE_ENABLED` | 준비 중 `false`, 운영 전환 시 `true` |
| `NEWS_GRID_URL` | 기존 대시보드의 기본 HTTPS URL. 미설정 시 워크플로의 기존 대시보드 주소를 사용한다. |
| `NEWS_MODEL` | 선택 사항. 미설정 시 `runtime-v12.json`의 모델을 사용하며, 해당 API 프로젝트에서 실제 사용 가능한지 probe로 확인한다. |

워커 내부의 `NEWS_GMAIL_TRANSPORT=gmail_api`와 임시 실행 상태 경로는 워크플로가 설정한다. 사용자가 runner에 데이터를 수동으로 상주시키는 방식은 아니다.

OpenAI API 사용료는 ChatGPT 구독과 별개다. GitHub Actions의 실행 시간·artifact 저장 공간에도 저장소 유형, 플랜, 사용량에 따른 한도나 비용이 적용된다. 이 예약을 지속하면 실행 시간이 누적되므로 저장소의 Actions 사용량과 API 프로젝트 예산을 함께 확인한다.

Gmail은 Google Cloud에서 Gmail API를 켜고, 기존 운영 계정에 `https://www.googleapis.com/auth/gmail.readonly` 범위로 OAuth 동의를 받아 offline access용 refresh token을 발급한다. 웹 클라이언트의 redirect URI는 발급 도구와 일치해야 한다. 외부 동의 화면이 **Testing**인 앱은 Gmail 범위의 refresh token이 보통 7일 만에 만료되므로 상시 예약 운영에는 운영용 게시 상태와 필요한 Google 검증을 갖춘 클라이언트를 사용한다. 로컬 Codex 앱의 Gmail 연결은 GitHub runner에 자동 전달되지 않는다.

Gmail transport는 모든 검색 페이지와 필요한 전체 MIME 본문을 읽고, 텍스트 첨부 본문도 확보한다. 메일을 보내거나 삭제하거나 라벨을 변경하지 않는다. 검색·수집·검토·Telegram 발송 완료는 서로 별도 상태다.

## 최초 이전: 원본 상태를 암호화해 연결

먼저 원본 Windows의 수집·검토·발송 프로세스와 자동 재시작 예약을 중지한다. 저장소 설치 스크립트의 작업 이름은 `Newsflow-V12-Continuous`, `Newsflow-V11-Continuous`다. 해당 작업을 사용 안 함으로 바꾸고 중지하며, 수동 실행한 서비스·발송기도 확인한다. 중단 당시 Telegram 결과가 불명확한 요청은 영수증을 보존하고 먼저 대조한다. 이후 첫 GitHub 운영 회차가 끝날 때까지 원본을 다시 켜지 않는다.

이 버전의 `deploy/cloud/artifact_state.py`와 `state.py`를 원본 PC에서 실행할 수 있게 준비한다. 다음 PowerShell 예시의 경로는 실제 운영 프로젝트와 별도의 비공개 백업 경로로 바꾼다. 암호화 파일 목적지는 원본 프로젝트 밖이어야 하며 기존 파일을 덮어쓰지 않는다.

`--stopped`는 모든 쓰기 작업을 중지했다는 운영자의 명시다. 도구는 추가로 기존 supervisor의 OS 잠금을 획득해 실행 중인 supervisor와의 충돌을 막는다. 수동 발송기까지 자동 종료하는 옵션은 아니다. 잠금 검사를 우회하려고 원본 `work/v11/supervisor.lock`을 삭제하지 않는다.

전체 `work/`와 SQLite Backup API를 이용해 뉴스 DB, 큐, 사용량, Gmail 상태·본문, 대시보드 상태와 모든 발송 증거를 함께 옮긴다. checksum과 SQLite 무결성을 확인하고 credential 파일·잠금·WAL/SHM 임시 파일은 별도 취급한다. Windows DPAPI 인증은 Actions Secrets로 새로 연결한다.

암호화에는 공식 [age](https://github.com/FiloSottile/age#installation)의 `age`와 `age-keygen`을 사용한다. 비밀 identity 파일은 checkout 밖에 보관하고 별도로 안전하게 백업한다. 이미 이 서비스용 identity가 있다면 새 키를 생성하지 않고 같은 키를 사용한다. 아래는 **최초 키 생성**과 GitHub Secret 등록 예시다. GitHub CLI `gh`는 해당 저장소를 관리할 수 있도록 인증되어 있어야 한다.

```powershell
age-keygen -o 'D:\Private Backups\news-state-age.key'
Get-Content -Raw -LiteralPath 'D:\Private Backups\news-state-age.key' | gh secret set NEWS_STATE_AGE_KEY --repo junseo96/newsautobot
```

비밀키 내용은 출력하거나 Release에 올리지 않는다. 암호화 helper는 같은 `NEWS_STATE_AGE_KEY`를 환경에서 읽고 내부에서 상태 내보내기와 검증을 수행한다. `--root`에는 중지된 **실제 운영 프로젝트**를 지정한다. 이미 내보낸 평문 아카이브를 `--root`로 넣지 않는다.

```powershell
$env:NEWS_STATE_AGE_KEY = Get-Content -Raw -LiteralPath 'D:\Private Backups\news-state-age.key'
python deploy/cloud/artifact_state.py encrypt --root 'D:\News Bot' --destination 'D:\Private Backups\state.tar.age' --stopped
Remove-Item Env:\NEWS_STATE_AGE_KEY
```

평문 아카이브와 비밀키는 업로드하지 않고, 생성된 `state.tar.age`만 최초 Release asset으로 올린다. 다음은 아직 해당 태그가 없는 최초 등록 명령이다.

```powershell
gh release create news-state-bootstrap 'D:\Private Backups\state.tar.age' --repo junseo96/newsautobot --title 'Encrypted Newsautobot bootstrap state' --notes 'Encrypted operational state for the initial GitHub Actions migration.'
```

키가 맞지 않거나 ciphertext·manifest·DB 검증이 실패하면 운영을 시작하지 않는다. 기존 Release가 있다면 오래된 백업인지 확인 없이 덮어쓰거나 재사용하지 않는다.

## 첫 회차와 이후 운영

위 Secrets·Variables와 암호화 bootstrap 상태가 준비되면 다음 순서로 전환한다.

1. 원본 발송자와 예약이 계속 중지되어 있는지 확인한다.
2. GitHub 변수 `NEWS_SERVICE_ENABLED`는 아직 `false`로 유지한다.
3. Actions의 운영 워크플로에서 **Run workflow → bootstrap: true**로 최초 회차를 수동 실행한다. 이 옵션은 예약 스위치가 꺼져 있어도 실제 수집·검토·발송을 시작한다. CLI로는 다음과 같다.

```bash
gh workflow run news-runtime.yml --repo junseo96/newsautobot --ref main -f bootstrap=true
```

최초 회차는 복호화·복원·이력 audit·제공자 probe 후 뉴스봇의 제한된 작업 회차를 수행하고 최신 상태를 다시 암호화해 저장한다. 회차 성공과 `newsautobot-state` artifact 생성을 확인한 다음 `NEWS_SERVICE_ENABLED=true`로 바꾼다. 이후 예약 회차는 최신 성공 상태를 이어받는다. `bootstrap:true`는 일반 재시작 옵션이 아니며, 최초 이전 또는 운영자가 최신 상태를 확보한 복구에만 사용한다.

probe는 Gmail 검색 ID, Telegram `getMe`·`getChat`, DART 읽기, 기존 대시보드 읽기를 확인한다. 모델 probe는 최소 응답을 실제로 생성하므로 소액의 API 비용이 발생한다. probe 자체는 메일 본문·Telegram 발송·대시보드 이벤트 생성을 수행하지 않는다. Telegram 접근 확인은 실제 발송 권한·성공 영수증까지 증명하지 않으며, 최소 모델 응답도 전체 기사 검색·편집 성공을 대신하지 않는다.

첫 실제 적격 기사 처리에서 Telegram 영수증의 `complete`, message ID, ACK와 기존 대시보드 반영을 확인한다. 적격 기사가 없는 동안 검증용 가짜 뉴스를 보내지 않는다. Actions가 성공했다는 사실과 각 수집 출처·기사 검토·발송의 결과는 구분해서 확인한다.

## Python 상시 실행

복원된 운영 이력, `work/` 경로와 위 인증 설정이 준비된 Linux 실행 환경에서 다음 진입점을 사용한다.

```bash
NEWS_SERVICE_ENABLED=true NEWS_GMAIL_TRANSPORT=gmail_api python3 deploy/cloud/run_forever.py
```

`run_forever.py`는 시간 제한 없이 기존 수집·Gmail·기사 검토·발송·대시보드 동기화 루프를 실행한다. 기존 supervisor 잠금으로 중복 실행을 막고, Ctrl+C 또는 SIGTERM을 받으면 새 작업을 멈춘 뒤 진행 중인 처리와 영수증·ACK 기록을 정리한다. 인증·이력 검증 실패 시 시작하지 않으며, `NEWS_SERVICE_ENABLED`가 꺼져 있으면 발송 없이 대기한다.

이 프로세스가 실행되는 머신이 유지되는 동안 계속 동작한다. GitHub Actions에서 실행하면 runner의 작업 시간 제한이 적용된다. 예약 워크플로는 기존 `cycle --seconds 600`을 사용한다.

## 실패·중지·복구

중지는 먼저 `NEWS_SERVICE_ENABLED=false`로 바꿔 이후 실행을 막고 현재 회차가 종료·상태 저장될 때까지 기다리는 방식으로 한다. 실행 도중 Cancel을 누르면 발송 이후 상태 저장이 끊길 수 있다. 작업 시간 제한은 새 작업을 멈추고 진행 중인 처리를 정리하는 기준이며, 발송 도중 프로세스를 즉시 강제 종료하는 타이머가 아니다. runner 강제 종료·전체 job timeout은 여전히 발생할 수 있다.

이전에 실제로 실행된 운영 회차가 실패·취소되면 자동 재개가 막힌다. 실패 회차가 남긴 최신 암호화 artifact, 로그와 실제 Telegram 결과를 확인한다. 가장 최근 확정된 발송 이력과 불명확한 영수증을 보존하고, 최신 일관된 상태를 확보해 검증한 뒤에만 운영자 복구 bootstrap을 수행한다. 같은 실패 run의 `Re-run jobs`도 차단하므로, 복구는 검증된 최신 상태를 준비한 새 수동 회차로 진행한다. 과거 성공 회차나 최초 Release를 무조건 다시 불러오면 최근 발송 이력이 사라져 중복 발송할 수 있다.

코드 롤백도 **최신 운영 상태**를 유지한 채 호환 코드를 선택한다. DB 형식 호환성을 확인하고, 오래된 백업을 덮어쓰지 않는다. age identity를 교체할 때에는 최신 상태의 재암호화와 새 Secret을 함께 전환해야 한다. 비밀키를 잃으면 기존 artifact를 복호화할 수 없다.

## 개발 검사와 구현 범위

[Dockerfile](Dockerfile)은 Linux amd64, digest가 고정된 Node 24 Bookworm 기반이며 PowerShell **7.4.21** checksum과 Codex CLI **0.159.2**를 고정한다. Debian Python 3, `age`, TLS 인증서와 `tini`를 설치한다. Python 워커는 표준 라이브러리를 사용한다. [검사 워크플로](../../.github/workflows/cloud-worker.yml)는 실제 PowerShell을 포함한 합성 회귀 검사와 활성화 차단을 확인한다.

운영 키 없이 로컬 Docker에서 같은 검사를 실행할 수 있다.

```bash
docker build -f deploy/cloud/Dockerfile -t newsautobot:test .
docker run --rm --entrypoint python3 newsautobot:test -X utf8 -m unittest discover -s outputs/rss-news-monitor -p 'test_*.py' -v
docker run --rm --entrypoint python3 newsautobot:test -m unittest discover -s deploy/cloud -p 'test_*.py' -v
docker run --rm -e NEWS_SERVICE_ENABLED=true newsautobot:test cycle --seconds 1
```

마지막 명령은 상태·키 없는 활성화를 **종료 코드 2로 차단해야 성공**인 검사다. Python만 있는 호스트에서는 PowerShell 통합 검사가 건너뛰어질 수 있으므로 배포 검사는 이미지 안에서 수행한다. 로컬의 `worker.py check`, `worker.py audit`, `probe.py`는 각각 환경·상태 기본 조건, 역사적 증거, 실제 제공자 인증을 별도로 검사한다.

빌드에는 Debian 패키지 저장소, GitHub PowerShell 릴리스와 npm이 필요하다. 운영에는 Google OAuth/Gmail, OpenAI API, Telegram, DART, 기존 대시보드와 등록 뉴스·기사 출처의 HTTPS 접근이 필요하다. TLS·artifact checksum 검증은 유지한다. 저장소 테스트가 통과했다는 결과만으로 실제 GitHub 운영 회차나 인증 연결이 수행됐다고 간주하지 않는다.

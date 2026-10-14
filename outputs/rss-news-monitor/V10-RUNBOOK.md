# 뉴스플로우 v10 실행 안내

운영 기준은 [PROTOCOL.md](PROTOCOL.md). 한국시간 **06·09·12·15·18·21시**, 06시 모닝은 전일 21시~당일 06시. 이 문서는 필요한 절만 참조하는 명령 안내이며 매회 전체 재독하지 않는다. 명령 예시는 실행 증거가 아니다. `<회차>`, `<run_id>`, `<실제ID>`는 실제 값으로 교체한다.

## 1. 시작과 경로

실제 시작시각을 기록하고 해당 예약 회차의 기존 결과·영수증을 확인한다. 이미 성공한 동일 회차를 새 영수증으로 재발송하지 않는다.

```powershell
$newsRoot = 'C:\Users\pos03\Documents\Codex\newflow'
$newsTools = Join-Path $newsRoot 'outputs\rss-news-monitor'
$runStartEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$scanFile = Join-Path $newsRoot 'work\gmail-scans\<회차>\scan.json'
$newsletterFile = Join-Path $newsRoot 'work\gmail-scans\<회차>\newsletter.json'
```

아래 `-ExecutionPolicy Bypass`는 해당 PowerShell 프로세스의 호출 옵션이다. 시스템 실행정책 변경 명령을 사용하지 않는다. 래퍼가 등록된 Python을 선택하므로 매회 런타임 경로 탐색을 반복하지 않는다. 정상 회차에 연결검사·테스트 발송을 추가하지 않는다.

## 2. Gmail 검색·본문 캐시·기사 추출

```powershell
$scanBegin = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" gmail_scan begin --compact | ConvertFrom-Json
$scanBegin
```

`scanBegin.query` 그대로 **실제 Gmail 플러그인 `gmail_search_email_ids`** 호출, 다음 페이지가 없을 때까지 검색한다. 검색 응답을 변수에 보존하고 전체 ID를 합친다. 메일 수신일 경계는 2026-09-17 15:00 KST이며 라벨·읽음·발신자·프로모션 필터를 추가하지 않는다. 시작점 이전이면 `scan_deferred_until_start`를 기록한다.

실제 검색 결과로 `scan.json`을 작성한다. 다음 값은 형식 예시로, 시각·ID·query를 실제 결과로 채운다.

```json
{
  "scan_started_epoch": 0,
  "scope_start_epoch": 1789624800,
  "query": "<begin의 query>",
  "pagination_complete": true,
  "search_tool": "gmail_search_email_ids",
  "message_ids": ["<전 페이지 실제 ID>"],
  "new_message_ids": [],
  "queued_message_ids": [],
  "read_message_ids": [],
  "cached_message_ids": []
}
```

```powershell
$mailQueue = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" gmail_scan record-search --scan-file $scanFile | ConvertFrom-Json
$mailQueue | Select-Object searched_message_count, already_ingested_count, new_message_ids, queued_message_ids, body_read_needed_ids, cached_bodies
```

`record-search`는 모든 검색 ID를 내구성 큐에 저장한 뒤 검색 커서를 전진시킨다. **검색 커서 전진은 메일 수집·기사 검토·발송 완료가 아니다.** `body_read_needed_ids`만 `gmail_batch_read_email`로 전체 본문 조회한다. 이전 미처리 메일의 검증된 캐시는 `cached_bodies`의 경로와 해시를 사용한다.

신규 본문은 프로젝트 `work` 아래 고유 파일에 플러그인 응답을 그대로 담아 보존한다. 캐시의 형식은 `{"message_id":"실제ID","body_complete":true,"message":<해당 메일의 전체 플러그인 객체>}`. `message.id`와 전체 Gmail MIME `payload`가 필요하며 snippet·요약·추출 결과만 저장하면 거부된다. 도구 응답은 출력하지 않고 프로그램 변수에서 파일로 직렬화한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" gmail_scan cache-body --message-id '<실제ID>' --body-file "$newsRoot\work\gmail-scans\<회차>\body-<실제ID>.json"
$cachedMail = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" gmail_scan read-cache --message-id '<실제ID>' | ConvertFrom-Json
```

`$cachedMail`과 원시 HTML/MIME는 대화로 출력하지 않는다. 로컬 파서에서 MIME 본문을 해독해 제목·본문·모든 기사 링크를 추출하고, 모델에는 판단에 필요한 기사 목록과 본문 부분만 전달한다. 메뉴·구독해지·계정변경 링크를 제외하며, 기사 전용 추적 링크는 승인된 범위에서 최종 공개 원문으로 해소한다. 광고 형태의 메이저 업체 기술자료도 내용에 따라 검토한다.

각 메일의 **전체 기사 추출이 끝난 뒤** NewsletterFile에 넣는다. 특정 기사 몇 개만 넣고 메일 전체를 수집 완료로 처리하지 않는다. 기사 URL을 아직 해소하지 못한 메일은 캐시·큐에 보존하고 남은 단계를 기록한다. 기사 없는 메일은 본문 검토 후 `articles:[]`와 구체적 `non_article_reason`을 사용한다.

```json
{
  "schema_version": 1,
  "messages": [{
    "message_id": "<실제ID>",
    "received_at": "<실제 수신시각 ISO+시간대>",
    "source": "<매체>",
    "source_url": "https://publisher.example/",
    "must_review": true,
    "articles": [{
      "url": "https://publisher.example/article",
      "title": "<기사 제목>",
      "summary": "<메일 본문에 실제 있는 근거>",
      "published_at": null
    }]
  }]
}
```

`published_at`은 원문 발표일이며 수신일로 대체하지 않는다. `scan.json`의 new/queued/read/cached ID도 실제 `record-search`·본문조회·캐시 재사용 결과로 갱신한다. 플러그인 검색 없이 신규 0통을 기록하지 않는다.

## 3. 회차당 수집 1회

```powershell
$collection = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-Collector.ps1" -Mode collect -LookbackHours 72 -Lane realtime -MaxCandidates 40 -NewsletterFile $newsletterFile | ConvertFrom-Json
$runId = $collection.run_id
$runDir = Join-Path $newsRoot ("work\runs\" + $runId)
$snapshot = Join-Path $runDir 'snapshot.json'
$collection
```

06시만 `-Lane morning`. 준비된 신규 메일 입력이 없으면 `-NewsletterFile` 인수만 생략한다. Gmail 실패나 미추출 메일은 확인 공백으로 기록하면서 수집을 진행한다. 추가 페이지를 보기 위해 collect를 다시 실행하지 않는다. `MaxCandidates 40`은 최초 화면 출력량이며 전체 모집단 제한이 아니다.

## 4. 전체 후보 확인과 판단 기록

```powershell
$packet = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" run_packet --snapshot $snapshot summary | ConvertFrom-Json
$packet
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" run_packet --snapshot $snapshot screen --offset 0 --limit 100
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" run_packet --snapshot $snapshot detail --indices 0,7,18
```

`summary.page_plan`의 **모든 offset/limit**을 순서대로 읽는다. 각 페이지의 실제 확인 인덱스 범위를 기록하고 `next_offset=null`까지 진행한다. 인덱스는 0부터 시작하며 snapshot 해시에 종속된다. score와 나이로 후보를 숨기지 않는다. `historical_reference_only_count`는 사용자 요청으로 보존한 이력이며 현재 검토 누락 건수와 구분한다.

screen은 제목·240자 이내 요약·출처·날짜를 제공하며 원본 URL과 전체 필드는 detail에 있다. `summary_truncated=true`이거나 내용이 모호한 후보는 필요한 상세와 원문을 확인한다. 화면에 표시했다는 이유로 기사 검토완료를 기록하지 않는다. 동일 원문의 검증된 캐시를 재사용하고 독립 원문 조회는 묶어서 수행한다.

페이지별로 실제 판단한 제외·중복만 고유 `decisions-page-000-input.json`에 작성한다. 다음 예시의 reason을 그대로 사용하지 말고 실제 판단 근거를 적는다.

```json
{
  "run_id": "<현재 run_id>",
  "snapshot_sha256": "<summary의 해시>",
  "decisions": [
    {"index": 7, "status": "reviewed", "reason": "<실제 확인한 범위·최신성·산업 근거에 따른 제외 사유>"}
  ]
}
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" run_packet --snapshot $snapshot decisions --input "$runDir\decisions-page-000-input.json" --output "$runDir\decisions-page-000.json"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Ack-Collector.ps1" -BatchFile $snapshot -DecisionFile "$runDir\decisions-page-000.json"
```

변환기는 URL만 정확히 확장하며 ACK를 수행하지 않는다. 새 output 파일만 허용한다. 중복 제외는 실제 영수증이 있는 과거 후보 URL을 `duplicate_of`에 넣고 새 산업 사실 부재를 설명한다. 미검토·원문 접근실패는 결정 목록에서 제외하고 남은 단계로 보존한다. `brief`는 최종 검토완료가 아니다. 실발송 후보의 delivered ACK는 다음 Publish 절차에 맡긴다.

## 5. 검증한 기사 순차 발송

현재 `$runDir`에 서로 다른 고유 message/urls/novelty 파일을 작성한다. URLs 파일에는 해당 snapshot 후보 URL을 한 줄씩, 메시지에는 검증된 공개 원문 링크를 사용한다. 제목 아래에는 `**- 핵심 변화·검증 수치/일정·산업 영향을 압축한 실제 한 문장**`을 작성한다. `**- 요약**`·TODO 등 항목명/자리표시자만 입력하면 발송 검사에서 거부된다. 예: `**- 한전, 나주 56MW ESS 약 324억원 EPC 입찰 착수…2027년 말 준공 목표**`. 굵은 [제목]·요약·번호 항목 사이 빈 줄, 한국어 명사형 종결, 마지막 `링크: 원문 URL` 유지. 검증되지 않은 수치를 요약에 추가하거나 제목만 복사하지 않는다.

```powershell
$messageFile = Join-Path $runDir 'message-001.txt'
$urlsFile = Join-Path $runDir 'urls-001.txt'
$noveltyFile = Join-Path $runDir 'novelty-001.json'
$guard = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" delivery_guard --message-file $messageFile | ConvertFrom-Json
$guard | Select-Object message_sha256, history_count
```

`$guard.matches`의 유사 건 **전부**에서 실제 기존 본문·증거 유형을 확인한다. 전 기간 전체 본문을 다시 출력하지 않는다. 옛 outbox 단독으로 중복을 확정하지 않는다. novelty에는 해시, 구체적 new_facts, 각 일치 ID의 classification/reason/material_delta와 industrial_signal을 기록한다. 상세 예외 필드는 INDUSTRIAL-SIGNAL-POLICY.md의 '발송 전 증거' 절 참조.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Publish-Brief.ps1" -BatchFile $snapshot -MessageFile $messageFile -ArticleUrlsFile $urlsFile -NoveltyReviewFile $noveltyFile -ReceiptFile "$runDir\receipt-001.json" -DecisionFile "$runDir\decisions-001.json" -Reason '<검증된 신규 산업 변화의 구체적 근거>'
```

Publish는 사전검증→기존 발송기의 ValidateOnly/novelty 검사→잠금하 실제 전송→complete 영수증·메시지ID 확인→ACK를 수행한다. 정상 운영은 이 명령 1회면 되며 같은 ValidateOnly를 앞에서 중복 실행할 필요가 없다. 구축 검증만 할 때는 `-ValidateOnly`를 추가하고 발송·ACK 성공으로 보고하지 않는다.

발송 성공 후 ACK만 누락됐다면 **같은 입력·같은 영수증·같은 Reason**으로 Publish를 재실행한다. complete 영수증을 검증해 발송 없이 ACK 복구한다. incomplete/uncertain 영수증은 실제 전송 상태 확인 전 새 영수증으로 재시도하지 않는다. 이미 발송된 기사의 본문·영수증을 고쳐 재사용하지 않는다.

## 6. 잔여·회차 완료 증거

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" gmail_scan finish --scan-file $scanFile
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" gmail_run_check --scan-file $scanFile --run-start-epoch $runStartEpoch
$newsletterAudit = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsTools\Run-NewsTool.ps1" newsletter_completion | ConvertFrom-Json
$newsletterAudit | Select-Object ingested_messages, retired_historical_messages, workflow_complete_messages, workflow_incomplete_messages, unresolved_article_count, legacy_delivery_recovery_needed_count, workflow_complete
```

finish의 `advanced`는 수집 커서의 결과, gmail_run_check는 검색·본문·저장 증거, newsletter_completion은 기사별 결정·발송 이력 집계이다. 서로 대체하지 않는다. 감사 결과의 미완료 목록은 로컬 변수에서 해당 대상만 조회한다. 본문 읽기·캐시 저장·목록 표시만으로 완료 건수를 늘리지 않는다.

`$runDir/screening-result.json`에 다음 실제 증거를 저장한다.

- 예약 회차·시작·종료·실제 발송시각, operational_version=10, delivery_policy_revision="8.3".
- snapshot 해시·전체 후보수·실제 screen 인덱스 범위·원문 확인수·실제 판단/ACK수·미검토수 및 남은 단계.
- Gmail 검색/신규/본문조회/캐시 재사용/수집/기사검토/잔여 건수와 scan·cache 파일 경로.
- 소스별 실패·기사0건·공식 대체조회 결과·남은 공백.
- 실제 Telegram message_id·본문·complete 영수증·ACK 파일, 결과 sent/no_qualifying_news/partial/failed.
- 모델에 출력한 후보/상세 수·반복조회·캐시 재사용 등 실제 측정 가능한 효율 지표. 측정하지 않은 토큰 절감량 추정 기입 금지.

원문 직접 검토가 필요한 미확인 후보나 Gmail 잔여가 있으면 partial이다. 검토를 모두 마쳤고 새 대상이 없을 때만 no_qualifying_news를 사용한다. 검증된 뉴스는 잔여 때문에 대기시키지 않고 먼저 전송한다.

## 7. 뉴스 없는 회차·장애의 상태 메시지

실기사용 Publish는 빈 URLs를 허용하지 않는다. 뉴스 전송이 0건이면 실제 확인 범위를 담은 운영 본문을 현재 run 폴더에 작성하고 기존 상태 인터페이스로 한 번 전송한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$newsRoot\outputs\telegram-forwarder\Send-Telegram.ps1" -MessageFile "$runDir\status-message.txt" -MarkdownBold -ReceiptFile "$runDir\receipt-status.json"
$statusReceipt = Get-Content -Raw -LiteralPath "$runDir\receipt-status.json" | ConvertFrom-Json
$statusReceipt | Select-Object status, telegram_message_ids
```

완료된 경우 '[날짜 HH:00 뉴스 점검] 신규 발송 대상 없음', 미완료이면 '확인 공백: 기관/메일/남은 단계'를 명시한다. 뉴스 없음으로 장애를 위장하지 않는다. 상태 전송에는 NewsFormat·기사URL·기사 delivered ACK를 사용하지 않는다. complete 영수증과 실제 ID 확인 후 결과에 기록한다. 이미 뉴스가 발송된 회차에는 불필요한 완료 메시지를 추가하지 않는다.

대화에는 발송수·핵심제목·본문/영수증 링크·새 공백만 보고한다. 원시 메일, 전체 snapshot, Telegram 본문 전체를 반복 출력하지 않는다.

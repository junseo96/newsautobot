param([switch]$FormatOnly)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Telegram-Format.ps1')
$sender = Join-Path $PSScriptRoot 'Send-Telegram.ps1'
function Assert($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $thrown=$false
    try { & $Action | Out-Null } catch { $thrown=$true; $script:lastFailure=$_.Exception.Message }
    Assert $thrown $Message
}
$oneDetail="**[간결한 전력 뉴스]**`n`n**- 신규 발전설비 승인**`n`n1. 500MW 발전설비 건설 승인`n`n링크: https://example.com/article"
Assert-NewsFormat $oneDetail
$oneValidation=& $sender -Text $oneDetail -MarkdownBold -NewsFormat -ValidateOnly -ConfigDir 'Z:\does-not-exist' | ConvertFrom-Json
Assert $oneValidation.valid 'One numbered detail must pass without credentials or transport.'
$noDetails="**[간결한 전력 뉴스]**`n`n**- 신규 발전설비 승인**`n`n링크: https://example.com/article"
Assert-Throws { Assert-NewsFormat $noDetails } 'A news article with no numbered detail must fail.'
Assert-Throws { Assert-NewsFormat ($oneDetail.Replace('1. 500MW 발전설비 건설 승인',"1. 500MW 발전설비 건설 승인`n2. 2028년 준공 목표")) } 'Numbered details must retain blank lines.'
Assert-Throws { Assert-NewsFormat ($oneDetail.Replace('건설 승인','건설 승인입니다')) } 'One-detail articles must retain Korean noun endings.'
$channelNews="**[공개 채널 형식 검증]**`n`n**- 전력망 증설의 승인 단계와 규모 구분**`n`n1. 9월 14일 발표. **500MW 계통접속 승인**, 실제 가동과는 구분`n`n2. A&B의 설비 검토 범위. **800V DC 전력변환**과 <제어> 검증 계획`n`n3. 최종 발주 확정은 아님.`n`n링크: https://example.com/news`n공식 공고: https://example.com/order"
Assert-NewsFormat $channelNews
$channelHtml=ConvertTo-TelegramHtml $channelNews
Assert ($channelHtml.Contains('<b>500MW 계통접속 승인</b>')) 'Inline material-fact bold must survive Telegram HTML conversion.'
Assert ($channelHtml.Contains('<b>800V DC 전력변환</b>')) 'Multiple inline emphasis spans must render independently.'
Assert ($channelHtml.Contains('A&amp;B') -and $channelHtml.Contains('&lt;제어&gt;')) 'Non-format HTML must remain escaped.'
Assert ($channelHtml.Contains("`n`n2. ") -and $channelHtml.Contains("`n공식 공고: https://example.com/order")) 'Paragraph spacing and labeled secondary sources must be preserved.'
Assert (([regex]::Matches($channelHtml,'<b>').Count) -eq 4 -and ([regex]::Matches($channelHtml,'</b>').Count) -eq 4) 'Headline, summary and selective inline bold must remain balanced.'
$channelValidation=& $sender -Text $channelNews -MarkdownBold -NewsFormat -ValidateOnly -ConfigDir 'Z:\does-not-exist' | ConvertFrom-Json
Assert ($channelValidation.valid -and $channelValidation.parts -eq 1) 'Channel-style preview must pass without credentials or transport.'
if ($FormatOnly) {
    Write-Output 'PASS: public-channel format, selective inline bold, labeled secondary link, HTML escaping, concise details, numbered spacing, noun endings (no credentials or transport).'
    return
}
$testDir = Join-Path ([IO.Path]::GetTempPath()) ('news-delivery-tests-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($testDir) | Out-Null
# Test configuration is generated locally; mock transport below never reaches Telegram.
$dummy=ConvertTo-SecureString 'local-test-token-not-a-credential' -AsPlainText -Force
[IO.File]::WriteAllText((Join-Path $testDir 'bot-token.dpapi'),(ConvertFrom-SecureString $dummy))
[IO.File]::WriteAllText((Join-Path $testDir 'chat-id.txt'),'1')
$dummy.Dispose()
$global:NewsDeliveryTestState=@{calls=0;mode='success';payloads=@()}
$global:NewsDeliveryTestState.mode='success'
$global:NewsDeliveryTestState.payloads=@()
function Invoke-RestMethod {
    param($Method,$Uri,$Body,$TimeoutSec)
    $global:NewsDeliveryTestState.calls++
    $global:NewsDeliveryTestState.payloads+=@($Body.text)
    if ($global:NewsDeliveryTestState.mode -eq 'uncertain') { throw 'mock timeout' }
    if ($global:NewsDeliveryTestState.mode -eq 'reject-second' -and $global:NewsDeliveryTestState.calls -eq 2) { return @{ok=$false} }
    return @{ok=$true;result=@{message_id=100+$global:NewsDeliveryTestState.calls}}
}
$news="**[검증용 제목]**`n`n**- 전력망 투자 확대**`n`n1. 800V DC 설계 공개`n`n2. 배전기기 공급 확대`n`n링크: https://example.com/article"
$validation=& $sender -Text $news -MarkdownBold -NewsFormat -ValidateOnly -ConfigDir 'Z:\does-not-exist' | ConvertFrom-Json
Assert ($validation.valid -and $global:NewsDeliveryTestState.calls -eq 0) 'Validation must not read credentials or send.'
Assert (-not $validation.novelty_checked) 'Format-only validation must not claim novelty review.'
$guardMessage=Join-Path $testDir 'guard-message.txt'
[IO.File]::WriteAllText($guardMessage,$news,[Text.Encoding]::UTF8)
Assert-Throws { & $sender -MessageFile $guardMessage -NewsFormat -MarkdownBold -ReceiptFile (Join-Path $testDir 'guard-receipt.json') -ConfigDir 'Z:\missing' } 'News delivery without novelty review must stop before transport.'
Assert ($script:lastFailure -match 'NoveltyReviewFile') 'Missing novelty review must be the blocking reason.'
Assert ($global:NewsDeliveryTestState.calls -eq 0) 'Novelty guard failure must never call Telegram.'
Assert-Throws { & $sender -Text ($news.Replace('투자 확대','투자합니다')) -NewsFormat -ValidateOnly } 'Polite endings must fail.'
$long=(('Text & <tag> ' * 240)+"`n`n**[제목]**`n`n"+('Additional content ' * 260))
$chunks=@(Split-NewsMessage $long $true)
Assert ($chunks.Count -ge 2) 'Long content must split.'
foreach ($chunk in $chunks) {
    $html=ConvertTo-TelegramHtml $chunk
    Assert (([regex]::Matches($html,'<b>').Count) -eq ([regex]::Matches($html,'</b>').Count)) 'Bold tags must balance in each chunk.'
    Assert ($html -notmatch '<tag>') 'User text must be HTML escaped.'
}
$receipt=Join-Path $testDir 'resume.json'
$global:NewsDeliveryTestState.calls=0;$global:NewsDeliveryTestState.mode='reject-second'
Assert-Throws { & $sender -Text $long -MarkdownBold -ReceiptFile $receipt -ArticleUrl 'https://example.com/article' -ConfigDir $testDir } 'Rejected second chunk must fail.'
$partial=Get-Content -Raw $receipt | ConvertFrom-Json
Assert ($partial.status -eq 'partial' -and $partial.completed_parts.Count -eq 1) ('Only confirmed first chunk may be recorded. Last failure: '+$script:lastFailure)
$global:NewsDeliveryTestState.mode='success'
& $sender -Text $long -MarkdownBold -ReceiptFile $receipt -ArticleUrl 'https://example.com/article' -ConfigDir $testDir
$complete=Get-Content -Raw $receipt | ConvertFrom-Json
Assert ($complete.status -eq 'complete' -and $complete.telegram_message_ids.Count -eq $chunks.Count) 'Resume must complete all chunks.'
Assert ($global:NewsDeliveryTestState.calls -eq ($chunks.Count+1)) 'Resume must not resend confirmed first chunk.'
$callsBefore=$global:NewsDeliveryTestState.calls
& $sender -Text $long -MarkdownBold -ReceiptFile $receipt -ArticleUrl 'https://example.com/article' -ConfigDir 'Z:\missing'
Assert ($global:NewsDeliveryTestState.calls -eq $callsBefore) 'A complete receipt must prevent resending.'
Assert-Throws { & $sender -Text ($long+' changed') -MarkdownBold -ReceiptFile $receipt -ArticleUrl 'https://example.com/article' -ConfigDir $testDir } 'Receipt cannot be reused for different content.'
$global:NewsDeliveryTestState.mode='uncertain'
$uncertain=Join-Path $testDir 'uncertain.json'
Assert-Throws { & $sender -Text $news -MarkdownBold -ReceiptFile $uncertain -ArticleUrl 'https://example.com/article' -ConfigDir $testDir } 'Timeout must fail.'
$callsBefore=$global:NewsDeliveryTestState.calls
Assert-Throws { & $sender -Text $news -MarkdownBold -ReceiptFile $uncertain -ArticleUrl 'https://example.com/article' -ConfigDir $testDir } 'Uncertain send must not be blindly retried.'
Assert ($global:NewsDeliveryTestState.calls -eq $callsBefore) 'Uncertain send retry must not call transport.'
Write-Output 'PASS: validation, tone, HTML/chunk boundaries, partial resume, duplicate prevention, content binding, uncertain-send protection (mock transport only).'
# Keep synthetic test artifacts in the unique temp directory for diagnostic inspection.

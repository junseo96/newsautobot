[CmdletBinding(DefaultParameterSetName="Text")]
param(
 [Parameter(Mandatory=$true,ParameterSetName="Text")][string]$Text,
 [Parameter(Mandatory=$true,ParameterSetName="File")][string]$MessageFile,
 [string]$Title,[switch]$MarkdownBold,[string]$ConfigDir,[string]$ReceiptFile,
 [string[]]$ArticleUrl=@(),[string]$ArticleUrlsFile,[switch]$NewsFormat,[string]$NoveltyReviewFile,[switch]$ValidateOnly
)
$ErrorActionPreference="Stop"
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
. (Join-Path $PSScriptRoot "Telegram-Format.ps1")
. (Join-Path $PSScriptRoot "Telegram-Auth.ps1")
$messagePath=$null
if ($PSCmdlet.ParameterSetName -eq "File") {
 $messagePath=(Resolve-Path -LiteralPath $MessageFile).Path
 $message=[IO.File]::ReadAllText($messagePath,[Text.Encoding]::UTF8)
} else { $message=$Text }
if (-not [string]::IsNullOrWhiteSpace($Title)) { $message="{0}`r`n`r`n{1}" -f $Title.Trim(),$message }
$message=$message.Trim()
if ([string]::IsNullOrWhiteSpace($message)) { throw "Empty Telegram message." }
if ($NewsFormat) { Assert-NewsFormat $message }
if ($MarkdownBold -and ([regex]::Matches($message,'\*\*').Count % 2) -ne 0) { throw "Unbalanced bold markers." }
$parts=@(Split-NewsMessage -Value $message -Bold ([bool]$MarkdownBold))
$messageHash=Get-MessageHash $message
if ($ArticleUrlsFile) { $ArticleUrl=@($ArticleUrl)+@([IO.File]::ReadAllLines((Resolve-Path -LiteralPath $ArticleUrlsFile).Path,[Text.Encoding]::UTF8)) }
$urls=@($ArticleUrl | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim() } | Sort-Object -Unique)
foreach ($url in $urls) {
 $parsedUrl=$null
 if (-not [Uri]::TryCreate($url,[UriKind]::Absolute,[ref]$parsedUrl) -or $parsedUrl.Scheme -notin @("http","https")) { throw "Invalid article URL." }
}
if ($urls.Count -gt 0 -and [string]::IsNullOrWhiteSpace($ReceiptFile)) { throw "ArticleUrl requires ReceiptFile." }
function Assert-NoveltyReview {
 if (-not $messagePath -or $Title) { throw "News delivery requires MessageFile with the entire message (no Title override)." }
 if (-not $NoveltyReviewFile) { throw "News delivery requires NoveltyReviewFile; compare prior messages with delivery_guard.py first." }
 $guard=Join-Path $PSScriptRoot '..\rss-news-monitor\delivery_guard.py'
 . (Join-Path $PSScriptRoot '..\rss-news-monitor\Resolve-Python.ps1')
 $python=Resolve-NewsPython
 $guardArgs=@($guard,'--message-file',$messagePath,'--review-file',$NoveltyReviewFile)
 if ($ReceiptFile) { $guardArgs+=@('--current-receipt',$ReceiptFile) }
 & $python @guardArgs | Out-Null
 if ($LASTEXITCODE -ne 0) { throw "Novelty review failed; no Telegram send attempted." }
}
if ($ValidateOnly) {
 if ($NewsFormat -and $NoveltyReviewFile) { Assert-NoveltyReview }
 [pscustomobject]@{valid=$true;novelty_checked=[bool]$NoveltyReviewFile;parts=$parts.Count;characters=$message.Length;message_sha256=$messageHash;article_count=$urls.Count} | ConvertTo-Json -Compress
 return
}
if ([string]::IsNullOrWhiteSpace($ReceiptFile)) { throw "Verified delivery requires ReceiptFile." }
$receiptPath=[IO.Path]::GetFullPath($ReceiptFile)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($receiptPath)) | Out-Null
$receiptLock=[IO.File]::Open($receiptPath+".lock",[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$newsLock=$null
$legacyRendering=$false
try {
 if ($NewsFormat) {
  $root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
  $newsLock=[IO.File]::Open((Join-Path $root 'work\news-send.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 }
 if ([IO.File]::Exists($receiptPath)) {
  $receipt=[IO.File]::ReadAllText($receiptPath,[Text.Encoding]::UTF8) | ConvertFrom-Json
  if ($receipt.message_sha256 -ne $messageHash -or $receipt.markdown_bold -ne [bool]$MarkdownBold -or (@($receipt.article_urls | Sort-Object -Unique) -join "`n") -ne ($urls -join "`n")) { throw "Receipt content or article URL mismatch." }
  if ($receipt.status -eq "complete") { Write-Host "Telegram already sent; complete receipt reused."; return }
  if ($receipt.status -eq "uncertain" -or $null -ne $receipt.in_flight_part) { throw "Previous send result uncertain. Delivery verification required before retry." }
  $priorParts=@($receipt.completed_parts | Where-Object { $null -ne $_ } | Sort-Object index)
  if ($MarkdownBold -and $priorParts.Count -gt 0) {
   $first=$priorParts[0]
   $priorChunk=$parts[[int]$first.index]
   if ($parts.Count -gt 1) { $priorChunk="[{0}/{1}]`r`n{2}" -f ([int]$first.index+1),$parts.Count,$priorChunk }
   $currentHash=Get-MessageHash (ConvertTo-TelegramHtml $priorChunk)
   $oldHash=Get-MessageHash (ConvertTo-TelegramHtmlLegacy $priorChunk)
   if ($first.sha256 -eq $oldHash -and $first.sha256 -ne $currentHash) { $legacyRendering=$true }
   elseif ($first.sha256 -ne $currentHash) { throw "Completed chunk content mismatch." }
  }
 } else {
  $stamp=[DateTimeOffset]::UtcNow.ToString("o")
  $receipt=[pscustomobject]@{
   schema_version=1;status="partial";message_file=$messagePath;title=$Title
   message_text=$message;message_sha256=$messageHash;markdown_bold=[bool]$MarkdownBold
   article_urls=$urls;sent_at=$null;telegram_message_ids=@();completed_parts=@()
   total_parts=$parts.Count;in_flight_part=$null;created_at=$stamp;updated_at=$stamp
  }
  Save-TelegramReceipt $receiptPath $receipt
 }
 if ($NewsFormat) { Assert-NoveltyReview }
 $credential=$null
 $pointer=[IntPtr]::Zero
 $plainToken=$null
 try {
  $credential=Get-NewsTelegramCredential -ConfigDir $ConfigDir
  $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.SecureToken)
  $plainToken=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  $chatId=$credential.ChatId
  for ($index=0; $index -lt $parts.Count; $index++) {
   $chunk=$parts[$index]
   if ($parts.Count -gt 1) { $chunk="[{0}/{1}]`r`n{2}" -f ($index+1),$parts.Count,$chunk }
   if ($MarkdownBold) {
    if ($legacyRendering) { $chunk=ConvertTo-TelegramHtmlLegacy $chunk }
    else { $chunk=ConvertTo-TelegramHtml $chunk }
   }
   $chunkHash=Get-MessageHash $chunk
   $completed=@($receipt.completed_parts | Where-Object { $_.index -eq $index })
   if ($completed.Count -gt 0) {
    if ($completed[0].sha256 -ne $chunkHash) { throw "Completed chunk content mismatch." }
    continue
   }
   $receipt.in_flight_part=$index
   $receipt.updated_at=[DateTimeOffset]::UtcNow.ToString("o")
   Save-TelegramReceipt $receiptPath $receipt
   $body=@{chat_id=$chatId;text=$chunk;disable_web_page_preview=$true}
   if ($MarkdownBold) { $body.parse_mode="HTML" }
   try { $response=Invoke-RestMethod -Method Post -Uri ("https://api.telegram.org/bot{0}/sendMessage" -f $plainToken) -Body $body -TimeoutSec 30 }
   catch {
    $receipt.status="uncertain";$receipt.updated_at=[DateTimeOffset]::UtcNow.ToString("o")
    Save-TelegramReceipt $receiptPath $receipt
    throw "Telegram result uncertain (part $($index+1)/$($parts.Count)); credential-bearing errors suppressed."
   }
   if (-not $response.ok -or $null -eq $response.result.message_id) {
    $receipt.status="partial";$receipt.in_flight_part=$null
    Save-TelegramReceipt $receiptPath $receipt
    throw "Telegram rejected part $($index+1)/$($parts.Count)."
   }
   $receipt.completed_parts=@($receipt.completed_parts)+@([pscustomobject]@{index=$index;message_id=[long]$response.result.message_id;sha256=$chunkHash})
   $receipt.telegram_message_ids=@($receipt.telegram_message_ids)+@([long]$response.result.message_id)
   $receipt.in_flight_part=$null;$receipt.updated_at=[DateTimeOffset]::UtcNow.ToString("o")
   Save-TelegramReceipt $receiptPath $receipt
   if ($index -lt $parts.Count-1) { Start-Sleep -Milliseconds 400 }
  }
  $receipt.status="complete";$receipt.sent_at=[DateTimeOffset]::UtcNow.ToString("o");$receipt.updated_at=$receipt.sent_at
  Save-TelegramReceipt $receiptPath $receipt
  Write-Host ("Telegram sent successfully: {0} message(s)" -f $parts.Count) -ForegroundColor Green
 } finally {
  $plainToken=$null
  if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
  if ($null -ne $credential) { $credential.SecureToken.Dispose(); $credential=$null }
 }
} finally { if ($newsLock) { $newsLock.Dispose() }; $receiptLock.Dispose() }

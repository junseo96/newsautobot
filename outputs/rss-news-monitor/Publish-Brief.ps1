[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BatchFile,
    [Parameter(Mandatory=$true)][string]$MessageFile,
    [Parameter(Mandatory=$true)][string]$ArticleUrlsFile,
    [Parameter(Mandatory=$true)][string]$NoveltyReviewFile,
    [string]$ReceiptFile,
    [string]$DecisionFile,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Reason,
    [switch]$ValidateOnly
)

# One invocation retains the existing sender's novelty check/locks and the
# collector's receipt-backed ACK. This script never reads Telegram credentials.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
. (Join-Path $PSScriptRoot '..\telegram-forwarder\Telegram-Format.ps1')
$python = Resolve-NewsPython
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$BatchFile = (Resolve-Path -LiteralPath $BatchFile).Path
$MessageFile = (Resolve-Path -LiteralPath $MessageFile).Path
$ArticleUrlsFile = (Resolve-Path -LiteralPath $ArticleUrlsFile).Path
$NoveltyReviewFile = (Resolve-Path -LiteralPath $NoveltyReviewFile).Path
$runDirectory = [IO.Path]::GetDirectoryName($BatchFile)
$message = [IO.File]::ReadAllText($MessageFile, [Text.Encoding]::UTF8).Trim()
if (([regex]::Matches($message, '\*\*').Count % 2) -ne 0) { throw 'Unbalanced bold markers.' }
$messageHash = Get-MessageHash $message
$parts = @(Split-NewsMessage -Value $message -Bold $true)
$urls = @([IO.File]::ReadAllLines($ArticleUrlsFile, [Text.Encoding]::UTF8) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    ForEach-Object { $_.Trim() } | Sort-Object -Unique)
if (-not $ReceiptFile) { $ReceiptFile = Join-Path $runDirectory ('receipt-publish-' + $messageHash.Substring(0,16) + '.json') }
if (-not $DecisionFile) { $DecisionFile = Join-Path $runDirectory ('decisions-publish-' + $messageHash.Substring(0,16) + '.json') }
$ReceiptFile = [IO.Path]::GetFullPath($ReceiptFile)
$DecisionFile = [IO.Path]::GetFullPath($DecisionFile)

# Reuse the same canonicalization and receipt rules as ACK. The DB is opened
# read-only; invalid/stale inputs cannot send first and fail at ACK afterward.
$preflightCode = @'
import datetime as dt, hashlib, json, sqlite3, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'outputs/rss-news-monitor'))
from collector import canonical
from review_state import read_json, timestamp, validate_receipt
from project_paths import same_evidence_path
batch_path, message_path, urls_path, novelty_path, receipt_path, decision_path = [Path(x).resolve() for x in sys.argv[2:8]]
reason = sys.argv[8].strip()
if not reason:
    raise ValueError('A specific editorial Reason is required')
batch = read_json(batch_path)
run_id = batch.get('run_id')
if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
    raise ValueError('Invalid run_id')
run_dir = (root / 'work/runs' / run_id).resolve()
if run_dir.parent != (root / 'work/runs').resolve():
    raise ValueError('Invalid run directory')
paths = [batch_path, message_path, urls_path, novelty_path, receipt_path, decision_path]
if len(set(paths)) != len(paths) or any(p.parent != run_dir for p in paths):
    raise ValueError('Every artifact must be a distinct file in this immutable run directory')
if batch_path.name != 'snapshot.json' or not same_evidence_path((batch.get('run_files') or {}).get('snapshot'), batch_path):
    raise ValueError('BatchFile must be the immutable run snapshot')
if not receipt_path.name.startswith('receipt-') or receipt_path.suffix != '.json':
    raise ValueError('ReceiptFile must be a same-run receipt-*.json for recovery discovery')
if not decision_path.name.startswith('decisions-') or decision_path.suffix != '.json':
    raise ValueError('DecisionFile must be a same-run decisions-*.json')
generated = timestamp(batch.get('generated_at_kst'), 'Batch generated_at_kst')
if generated > dt.datetime.now(dt.timezone.utc):
    raise ValueError('Run generation timestamp is in the future')
message = message_path.read_bytes().decode('utf-8-sig').strip()
digest = hashlib.sha256(message.encode('utf-8')).hexdigest()
raw_urls = sorted(set(x.strip() for x in urls_path.read_text(encoding='utf-8-sig').splitlines() if x.strip()))
from urllib.parse import urlsplit
if not raw_urls or any(urlsplit(x).scheme not in {'http', 'https'} or not urlsplit(x).netloc for x in raw_urls):
    raise ValueError('ArticleUrlsFile must contain nonempty HTTP(S) article URLs')
urls = [canonical(x) for x in raw_urls]
if len(set(urls)) != len(urls):
    raise ValueError('ArticleUrlsFile repeats a canonical candidate URL')
candidates = {canonical(x['url']) for x in batch.get('candidates', [])}
if any(x not in candidates for x in urls):
    raise ValueError('An article URL is not a candidate in this run snapshot')
novelty = read_json(novelty_path)
facts, comparisons = novelty.get('new_facts'), novelty.get('comparisons')
if novelty.get('message_sha256') != digest:
    raise ValueError('Novelty review is bound to different message text')
if not isinstance(facts, list) or not facts or any(not isinstance(x, str) or len(x.strip()) < 12 for x in facts):
    raise ValueError('Novelty review requires concrete new industrial facts')
if not isinstance(comparisons, list) or any(not isinstance(x, dict) or not isinstance(x.get('id'), str) for x in comparisons):
    raise ValueError('Novelty comparisons must be an array of identified review objects')
if len({x['id'] for x in comparisons}) != len(comparisons):
    raise ValueError('Novelty review repeats a comparison ID')
reused = receipt_path.exists()
if reused:
    receipt = read_json(receipt_path)
    if receipt.get('status') != 'complete' or receipt.get('in_flight_part') is not None:
        raise ValueError('Existing receipt is incomplete or uncertain; verify delivery before retry, no send attempted')
    if receipt.get('message_text') != message or receipt.get('message_sha256') != digest or receipt.get('markdown_bold') is not True:
        raise ValueError('Existing receipt does not match this exact message')
    if sorted(set(receipt.get('article_urls', []))) != raw_urls:
        raise ValueError('Existing receipt article URL mismatch')
    if not same_evidence_path(receipt.get('message_file'), message_path):
        raise ValueError('Existing receipt references a different message file')
    for url in urls:
        validate_receipt(receipt_path, url, canonical, generated)
expected = {'run_id': run_id, 'decisions': [{'url': u, 'status': 'delivered', 'reason': reason, 'receipt_file': str(receipt_path)} for u in urls]}
if decision_path.exists() and read_json(decision_path) != expected:
    raise ValueError('DecisionFile already contains different decisions; no overwrite permitted')
db = root / 'work/rss-news-monitor.db'
with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=30) as con:
    if not reused:
        latest = con.execute('SELECT run_id FROM source_runs ORDER BY id DESC LIMIT 1').fetchone()
        if not latest or latest[0] != run_id:
            raise ValueError('Stale batch: collect a current run before new delivery')
        policy = int(read_json(root / 'outputs/rss-news-monitor/sources.json').get('selection_policy_version', 1))
        if int(batch.get('policy_version', policy)) != policy:
            raise ValueError('Selection policy changed; collect a current batch')
    for url in urls:
        if con.execute('SELECT 1 FROM articles WHERE url=?', (url,)).fetchone() is None:
            raise ValueError('Candidate is absent from the article database')
        previous = con.execute('SELECT status,reason,receipt_file FROM decision_history WHERE run_id=? AND url=?', (run_id, url)).fetchone()
        if previous and (not reused or previous[0] != 'delivered' or previous[1] != reason or not same_evidence_path(previous[2], receipt_path)):
            raise ValueError('Candidate already has a conflicting decision in this run')
print(json.dumps({'run_id':run_id, 'reused_receipt':reused, 'message_sha256':digest, 'article_count':len(urls), 'decision':expected}, ensure_ascii=True))
'@

function Invoke-PublishPreflight {
    $result = & $python -X utf8 -c $preflightCode $projectRoot $BatchFile $MessageFile $ArticleUrlsFile $NoveltyReviewFile $ReceiptFile $DecisionFile $Reason
    if ($LASTEXITCODE -ne 0) { throw 'Publish preflight failed; no new send authorized.' }
    return (($result -join "`n") | ConvertFrom-Json)
}

function Assert-CompleteReceipt([bool]$AllowLegacy = $false) {
    $receipt = [IO.File]::ReadAllText($ReceiptFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($receipt.status -ne 'complete' -or $null -ne $receipt.in_flight_part -or $receipt.total_parts -ne $parts.Count) {
        throw 'Telegram receipt is incomplete or uncertain; ACK withheld.'
    }
    $completed = @($receipt.completed_parts)
    $ids = @($receipt.telegram_message_ids)
    if ($completed.Count -ne $parts.Count -or $ids.Count -ne $parts.Count -or @($ids | Sort-Object -Unique).Count -ne $ids.Count) {
        throw 'Telegram receipt part/message ID counts are inconsistent; ACK withheld.'
    }
    for ($index=0; $index -lt $parts.Count; $index++) {
        $entry = @($completed | Where-Object { $_.index -eq $index })
        $chunk = $parts[$index]
        if ($parts.Count -gt 1) { $chunk = "[{0}/{1}]`r`n{2}" -f ($index+1), $parts.Count, $chunk }
        $currentHash = Get-MessageHash (ConvertTo-TelegramHtml $chunk)
        $legacyHash = if ($AllowLegacy) { Get-MessageHash (ConvertTo-TelegramHtmlLegacy $chunk) } else { $null }
        if ($entry.Count -ne 1 -or ($entry[0].sha256 -ne $currentHash -and $entry[0].sha256 -ne $legacyHash) -or
            $entry[0].message_id -ne $ids[$index] -or $ids[$index] -isnot [ValueType] -or [long]$ids[$index] -le 0) {
            throw 'Telegram receipt has an invalid chunk hash or message ID; ACK withheld.'
        }
    }
    return $receipt
}

try { $preflight = Invoke-PublishPreflight }
catch { throw ('PREFLIGHT_FAILED_NO_SEND: ' + $_.Exception.Message) }
$reused = [bool]$preflight.reused_receipt
$sendArguments = @{
    MessageFile=$MessageFile; ArticleUrlsFile=$ArticleUrlsFile; NoveltyReviewFile=$NoveltyReviewFile
    ReceiptFile=$ReceiptFile; NewsFormat=$true; MarkdownBold=$true
}
if ($reused) {
    $receipt = Assert-CompleteReceipt -AllowLegacy $true
} else {
    # New sends must meet the current editorial format. A verified, complete
    # historical receipt above is immutable and may recover ACK without resend.
    Assert-NewsFormat $message
    $inputPaths = @($BatchFile, $MessageFile, $ArticleUrlsFile, $NoveltyReviewFile)
    $inputHashes = @($inputPaths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash })
    $validationOutput = & (Join-Path $PSScriptRoot '..\telegram-forwarder\Send-Telegram.ps1') @sendArguments -ValidateOnly 6>$null
    $validation = ($validationOutput -join "`n") | ConvertFrom-Json
    if ($validation.valid -ne $true -or $validation.novelty_checked -ne $true -or
        $validation.message_sha256 -ne $messageHash -or $validation.article_count -ne $urls.Count -or $validation.parts -ne $parts.Count) {
        throw 'Sender validation/novelty evidence mismatch; no send attempted.'
    }
    for ($index=0; $index -lt $inputPaths.Count; $index++) {
        if ((Get-FileHash -LiteralPath $inputPaths[$index] -Algorithm SHA256).Hash -ne $inputHashes[$index]) {
            throw 'An input changed during validation; no send attempted.'
        }
    }
    if (-not $ValidateOnly) {
        $null = & (Join-Path $PSScriptRoot '..\telegram-forwarder\Send-Telegram.ps1') @sendArguments 6>$null
        # A successful process alone is not delivery proof.
        $preflight = Invoke-PublishPreflight
        $receipt = Assert-CompleteReceipt
    }
}
if ($ValidateOnly) {
    [pscustomobject]@{status='validated'; valid=$true; novelty_checked=(-not $reused); reused_receipt=$reused; run_id=$preflight.run_id; article_count=$urls.Count; parts=$parts.Count; receipt_file=$ReceiptFile; decision_file=$DecisionFile} | ConvertTo-Json -Compress
    return
}

if (-not [IO.File]::Exists($DecisionFile)) {
    $decisionBytes = [Text.Encoding]::UTF8.GetBytes(($preflight.decision | ConvertTo-Json -Depth 8))
    $decisionStream = [IO.File]::Open($DecisionFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $decisionStream.Write($decisionBytes, 0, $decisionBytes.Length) }
    finally { $decisionStream.Dispose() }
}
$ackArguments = @{BatchFile=$BatchFile; DecisionFile=$DecisionFile}
if ($reused) { $ackArguments.RecoverDeliveries = $true }
$ackOutput = & (Join-Path $PSScriptRoot 'Ack-Collector.ps1') @ackArguments
$ack = ($ackOutput -join "`n") | ConvertFrom-Json
if ($ack.run_id -ne $preflight.run_id -or ([int]$ack.delivered + [int]$ack.already_recorded + [int]$ack.current_revision_preserved) -ne $urls.Count) {
    throw 'ACK confirmation mismatch. Complete receipt retained; reuse this invocation for recovery, do not create a new receipt.'
}
[pscustomobject]@{status='delivered'; run_id=$preflight.run_id; article_count=$urls.Count; telegram_message_ids=@($receipt.telegram_message_ids); receipt_file=$ReceiptFile; decision_file=$DecisionFile; reused_receipt=$reused; ack=$ack} | ConvertTo-Json -Depth 5 -Compress

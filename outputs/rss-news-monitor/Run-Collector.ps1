[CmdletBinding()]
param(
    [ValidateSet("collect", "status", "export")][string]$Mode = "collect",
    [int]$LookbackHours = 12,
    [ValidateSet("realtime", "morning")][string]$Lane = "realtime",
    [ValidateRange(1, 500)][int]$MaxCandidates = 40,
    [ValidateRange(0, 1000000)][int]$Offset = 0,
    [string]$BatchFile,
    [string]$OutputFile,
    [string]$NewsletterFile,
    [switch]$FastPoll,
    [switch]$IncludeArchive
)
$ErrorActionPreference = "Stop"
$consoleUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $consoleUtf8
[Console]::OutputEncoding = $consoleUtf8
$OutputEncoding = $consoleUtf8
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$collector = Join-Path $PSScriptRoot "collector.py"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$database = Join-Path $projectRoot "work\rss-news-monitor.db"
$output = Join-Path $projectRoot "work\rss-news-candidates.json"
if ($OutputFile) { $output = [IO.Path]::GetFullPath($OutputFile) }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Codex Python runtime을 찾을 수 없습니다: $python" }
if ($Mode -eq "export") {
    if (-not $BatchFile) { throw "Export requires BatchFile from run_files.snapshot." }
    & $python $collector export --db $database --batch $BatchFile --output $output --offset $Offset --max-candidates $MaxCandidates
    if ($LASTEXITCODE -ne 0) { throw "Candidate page export failed." }
    return
}
if ($Mode -eq "status") {
    & $python $collector status --db $database
    if ($LASTEXITCODE -ne 0) { throw "Collector status failed." }
    return
}
$dartKeyPath = Join-Path $projectRoot ".news-monitor-secrets\dart-key.dpapi"
$dartPointer = [IntPtr]::Zero
if (Test-Path -LiteralPath $dartKeyPath -PathType Leaf) {
    $dartSecure = ConvertTo-SecureString ([IO.File]::ReadAllText($dartKeyPath, [Text.Encoding]::UTF8).Trim())
    $dartPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($dartSecure)
    $env:NEWS_DART_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($dartPointer)
}
$collectArgs = @($collector, "collect", "--db", $database, "--output", $output, "--lookback-hours", $LookbackHours, "--lane", $Lane, "--max-candidates", $MaxCandidates)
if ($NewsletterFile) { $collectArgs += @("--newsletter-file", (Resolve-Path -LiteralPath $NewsletterFile).Path) }
if ($FastPoll) { $collectArgs += "--fast-poll" }
if ($IncludeArchive) { $collectArgs += "--include-archive" }
try { & $python @collectArgs }
finally {
    $env:NEWS_DART_KEY = $null
    if ($dartPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($dartPointer) }
    if ($null -ne $dartSecure) { $dartSecure.Dispose() }
}
if ($LASTEXITCODE -ne 0) { throw "뉴스 수집기가 오류 코드 $LASTEXITCODE 로 종료되었습니다." }

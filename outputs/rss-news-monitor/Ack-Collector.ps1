[CmdletBinding()]
param([string]$DeliveredUrlsFile, [string]$ReviewedUrlsFile, [string]$BriefUrlsFile, [string]$DecisionFile, [string]$BatchFile, [switch]$RecoverDeliveries)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$collector = Join-Path $PSScriptRoot "collector.py"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$database = Join-Path $projectRoot "work\rss-news-monitor.db"
$batch = Join-Path $projectRoot "work\rss-news-candidates.json"
if ($BatchFile) { $batch = (Resolve-Path -LiteralPath $BatchFile).Path }
$arguments = @($collector, "ack", "--db", $database, "--batch", $batch)
if ($DecisionFile) {
    if ($DeliveredUrlsFile -or $ReviewedUrlsFile -or $BriefUrlsFile) { throw "Use DecisionFile without legacy URL files." }
    $arguments += @("--decision-file", (Resolve-Path -LiteralPath $DecisionFile).Path)
}
if ($RecoverDeliveries) { $arguments += "--recover-deliveries" }
function Add-Urls([string]$Path, [string]$ArgumentName) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "URL 파일이 없습니다: $Path" }
    foreach ($url in [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $Path).Path, [Text.Encoding]::UTF8)) {
        if (-not [string]::IsNullOrWhiteSpace($url)) { $script:arguments += @($ArgumentName, $url.Trim()) }
    }
}
if (-not [string]::IsNullOrWhiteSpace($DeliveredUrlsFile)) {
    if (-not (Test-Path -LiteralPath $DeliveredUrlsFile -PathType Leaf)) { throw "전송 URL 파일이 없습니다: $DeliveredUrlsFile" }
    foreach ($url in [IO.File]::ReadAllLines((Resolve-Path -LiteralPath $DeliveredUrlsFile).Path, [Text.Encoding]::UTF8)) {
        if (-not [string]::IsNullOrWhiteSpace($url)) { $arguments += @("--delivered-url", $url.Trim()) }
    }
}
Add-Urls $ReviewedUrlsFile "--reviewed-url"
Add-Urls $BriefUrlsFile "--brief-url"
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "뉴스 후보 처리완료 기록에 실패했습니다." }

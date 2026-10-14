[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$MappingFile)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$collector = Join-Path $PSScriptRoot 'collector.py'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$database = Join-Path $projectRoot 'work\rss-news-monitor.db'
if (-not (Test-Path -LiteralPath $MappingFile -PathType Leaf)) { throw "복구 매핑 파일이 없습니다: $MappingFile" }
& $python $collector recover-legacy-deliveries --db $database --mapping-file (Resolve-Path -LiteralPath $MappingFile).Path
if ($LASTEXITCODE -ne 0) { throw "과거 전송 영수증 복구에 실패했습니다." }

[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$scriptPath = Join-Path $PSScriptRoot 'v11_service.py'
# Task Scheduler owns this process; a single-instance byte lock rejects duplicates.
& $python -X utf8 $scriptPath run --root $root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

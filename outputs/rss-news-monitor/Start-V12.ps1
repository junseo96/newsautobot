[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
& $python -X utf8 (Join-Path $PSScriptRoot 'v12_service.py') run --root $root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

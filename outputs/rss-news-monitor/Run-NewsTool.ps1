[CmdletBinding()]
param(
    [Parameter(Mandatory=$true,Position=0)]
    [ValidateSet('gmail_scan','gmail_run_check','newsletter_completion','run_packet','delivery_guard')]
    [string]$Tool,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ToolArguments
)
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
& $python -X utf8 (Join-Path $PSScriptRoot ($Tool + '.py')) @ToolArguments
exit $LASTEXITCODE

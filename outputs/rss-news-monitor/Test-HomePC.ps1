[CmdletBinding()]
param([switch]$Collect)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$status = [ordered]@{tested_at=[DateTimeOffset]::UtcNow.ToString('o');delivery_tests='pending';migration_audit='pending';collector='not_run'}
try {
    & (Join-Path $root 'outputs\telegram-forwarder\Test-VerifiedTelegram.ps1')
    $status.delivery_tests = 'passed'
    & $python (Join-Path $PSScriptRoot 'audit_migration.py')
    if ($LASTEXITCODE -ne 0) { throw 'Migration audit failed' }
    $status.migration_audit = 'passed'
    if ($Collect) {
        $args = @{Mode='collect';Lane='realtime';MaxCandidates=40}
        $mail = Join-Path $root 'work\gmail-home-next-import.json'
        if (Test-Path -LiteralPath $mail) { $args.NewsletterFile = $mail }
        & (Join-Path $PSScriptRoot 'Run-Collector.ps1') @args
        $status.collector = 'completed_check_coverage'
    }
} catch {
    $status.error = 'Home-PC validation failed; see the local console. No credential values saved.'
    Write-Host $status.error -ForegroundColor Yellow
} finally {
    [IO.File]::WriteAllText((Join-Path $root 'work\home-validation-status.json'),($status | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    $status | ConvertTo-Json
}

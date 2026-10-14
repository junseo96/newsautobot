[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$statusPath = Join-Path $root 'work\home-setup-status.json'
$state = [ordered]@{telegram='pending'; dart='pending'; updated_at=''}
function Save-SetupStatus {
    $state.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($statusPath, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
Save-SetupStatus
Write-Host 'NEWSFLOW - HOME PC SETUP' -ForegroundColor Cyan
Write-Host 'Enter secrets only in this window. They are never printed or saved as plain text.'
try {
    & (Join-Path $root 'outputs\telegram-forwarder\Setup-Telegram.ps1')
    $state.telegram = 'connected'; Save-SetupStatus
} catch {
    $state.telegram = 'failed'; Save-SetupStatus
    Write-Host 'Telegram setup did not complete. Retry Setup-Telegram.ps1.' -ForegroundColor Yellow
}
try {
    & (Join-Path $PSScriptRoot 'Setup-Dart.ps1')
    $state.dart = 'connected'; Save-SetupStatus
} catch {
    $state.dart = 'failed'; Save-SetupStatus
    Write-Host 'DART setup did not complete. Retry Setup-Dart.ps1.' -ForegroundColor Yellow
}
if ($state.telegram -eq 'connected' -and $state.dart -eq 'connected') {
    & (Join-Path $PSScriptRoot 'Test-HomePC.ps1') -Collect
}
Write-Host 'Setup results (no credentials):' -ForegroundColor Cyan
$state | ConvertTo-Json
Read-Host 'Press Enter to close this window'

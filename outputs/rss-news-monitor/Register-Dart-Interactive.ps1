[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$statusPath = Join-Path $root 'work\dart-setup-status.json'
$state = [ordered]@{status='waiting_for_key'; updated_at=''; message=''}
function Save-DartSetupStatus {
    $state.updated_at = [DateTimeOffset]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($statusPath, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
Save-DartSetupStatus
$Host.UI.RawUI.WindowTitle = 'NEWSFLOW - DART registration - SAFE STAGE CHECK'
Write-Host 'NEWSFLOW - DART KEY REGISTRATION' -ForegroundColor Cyan
Write-Host 'SAFE STAGE CHECK: failures show a step code, never your key.' -ForegroundColor Cyan
Write-Host 'Paste your 40-character OpenDART API key at the masked prompt and press Enter.'
Write-Host 'Do not paste the key in the Codex conversation. No news will be sent by this setup.'
try {
    & (Join-Path $PSScriptRoot 'Setup-Dart.ps1')
    $state.status = 'connected'
    $state.message = 'Official API accepted the key; encrypted for this Windows user.'
    Save-DartSetupStatus
    Write-Host 'SUCCESS. Return to Codex; the API connection can now be verified independently.' -ForegroundColor Green
} catch {
    $state.status = 'failed'
    # Only classify known sanitized failures. Never persist the raw exception.
    $failureText = $_.Exception.Message
    $state.message = 'SETUP: Registration did not complete. Unclassified details suppressed.'
    if ($failureText -match '^OpenDART key must contain 40 ') {
        $state.message = 'KEY_FORMAT: Expected 40 characters after trimming. Copy the complete API key value, not its label or quotes.'
    } elseif ($failureText -match '^DART rejected the key/request\. Status code: (\d{3})$') {
        $state.message = 'DART_STATUS_' + $Matches[1] + ': Check OpenDART key activation and permitted IP addresses.'
    } elseif ($failureText -match '^DART connection failed\.') {
        $state.message = 'NETWORK: Could not complete the official OpenDART API request.'
    } elseif ($failureText -match '^DART returned an unexpected response') {
        $state.message = 'API_RESPONSE: The server response was not a recognized DART status.'
    } elseif ($failureText -match '^DART_SETUP_FAILURE: stage=[a-z_]+; type=[A-Za-z0-9]+; code=-?\d+$') {
        $state.message = $failureText
    }
    $failureText = $null
    Save-DartSetupStatus
    Write-Host $state.message -ForegroundColor Yellow
}
if ($state.status -eq 'connected') {
    # Bookkeeping failure must not relabel a verified, saved key as invalid.
    try {
        $homeStatusPath = Join-Path $root 'work\home-setup-status.json'
        if (Test-Path -LiteralPath $homeStatusPath) {
            $homeState = Get-Content -LiteralPath $homeStatusPath -Raw | ConvertFrom-Json
            $homeState.dart = 'connected'
            $homeState.updated_at = $state.updated_at
            [IO.File]::WriteAllText($homeStatusPath, ($homeState | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        }
    } catch {
        Write-Host 'Key is registered. The separate home-PC summary could not be updated.' -ForegroundColor Yellow
    }
}
Read-Host 'Press Enter to close this window' | Out-Null

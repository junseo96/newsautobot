[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
# Isolated fixture: no real credentials, network, Telegram, or project state.
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('newsflow-dart-fixture-' + [Guid]::NewGuid().ToString('N'))
$fixtureScripts = Join-Path $fixtureRoot 'outputs\rss-news-monitor'
New-Item -ItemType Directory -Path $fixtureScripts -Force | Out-Null
foreach ($name in @('Setup-Dart.ps1', 'Dart-Key.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $fixtureScripts $name)
}
function Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    return (ConvertTo-SecureString ('z' * 40) -AsPlainText -Force)
}
function Invoke-RestMethod {
    param($Method, [string]$Uri, $TimeoutSec)
    if (-not $Uri.StartsWith('https://opendart.fss.or.kr/api/list.json?')) { throw 'Unexpected endpoint in fixture.' }
    return [pscustomobject]@{status='013'}
}
try {
    & (Join-Path $fixtureScripts 'Setup-Dart.ps1')
    $secretPath = Join-Path $fixtureRoot '.news-monitor-secrets\dart-key.dpapi'
    $saved = ConvertTo-SecureString ([IO.File]::ReadAllText($secretPath))
    if ($saved.Length -ne 40) { throw 'Fixture decrypted length mismatch.' }
    $saved.Dispose()
    # Exercise replacement of an existing encrypted key too.
    & (Join-Path $fixtureScripts 'Setup-Dart.ps1')
    if (-not (Test-Path -LiteralPath ($secretPath + '.previous'))) { throw 'Fixture backup missing.' }
    $beforeFailure = (Get-FileHash -LiteralPath $secretPath -Algorithm SHA256).Hash
    function ConvertFrom-SecureString {
        param($SecureString)
        throw 'Synthetic sensitive text MUST_NOT_BE_LOGGED'
    }
    $caughtFailure = $null
    try { & (Join-Path $fixtureScripts 'Setup-Dart.ps1') }
    catch { $caughtFailure = $_.Exception.Message }
    if ($caughtFailure -notmatch '^DART_SETUP_FAILURE: stage=dpapi_encrypt; type=[A-Za-z0-9]+; code=-?\d+$') {
        throw 'Fixture did not report a sanitized encryption-stage failure.'
    }
    if ($caughtFailure.Contains('MUST_NOT_BE_LOGGED')) { throw 'Fixture leaked raw error text.' }
    if ((Get-FileHash -LiteralPath $secretPath -Algorithm SHA256).Hash -ne $beforeFailure) {
        throw 'Fixture replaced the previous key on failure.'
    }
    Write-Output 'PASS: mock input/API, encryption roundtrip, atomic replacement, sanitized failure stage, previous-key preservation.'
} catch {
    [pscustomobject]@{
        result='failed'
        exception_type=$_.Exception.GetType().FullName
        error_id=$_.FullyQualifiedErrorId
        script_line=$_.InvocationInfo.ScriptLineNumber
        script_name=[IO.Path]::GetFileName($_.InvocationInfo.ScriptName)
        # Only synthetic data exists in this fixture.
        message=$_.Exception.Message
    } | ConvertTo-Json
    exit 1
}

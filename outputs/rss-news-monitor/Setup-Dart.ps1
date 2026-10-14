[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'Dart-Key.ps1')
# Interactive hosts may not auto-load this module. Resolve the built-in
# manifest explicitly, before requesting a key or making an API request.
try {
    $securityManifest = Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1'
    Import-Module -Name $securityManifest -ErrorAction Stop
    Get-Command -Name ConvertTo-SecureString, ConvertFrom-SecureString -Module Microsoft.PowerShell.Security -ErrorAction Stop | Out-Null
} catch {
    throw ('DART_SETUP_FAILURE: stage=dependency_security_module; type={0}; code={1}' -f $_.Exception.GetType().Name, $_.Exception.HResult)
}
$consoleUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $consoleUtf8
[Console]::OutputEncoding = $consoleUtf8
$OutputEncoding = $consoleUtf8
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$secretDir = Join-Path $projectRoot ".news-monitor-secrets"
$secretPath = Join-Path $secretDir "dart-key.dpapi"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$secure = Read-Host 'Paste OpenDART API key, then Enter' -AsSecureString
$pointer = [IntPtr]::Zero
$plain = $null
$normalizedSecure = $null
$encodedKey = $null
$encryptedKey = $null
$setupStage = 'read_secure_input'
try {
    $setupStage = 'read_secure_input'
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $setupStage = 'normalize_key'
    $plain = Normalize-DartKey ([Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer))
    $setupStage = 'encode_request'
    $encodedKey = [Uri]::EscapeDataString($plain)
    $today = Get-Date -Format 'yyyyMMdd'
    $setupStage = 'api_request'
    try {
        $response = Invoke-RestMethod -Method Get -Uri ('https://opendart.fss.or.kr/api/list.json?crtfc_key={0}&bgn_de={1}&end_de={1}&page_count=1' -f $encodedKey,$today) -TimeoutSec 30
    } catch { throw 'DART connection failed. Credential-bearing error details are suppressed.' }
    $setupStage = 'api_response'
    $apiStatus = [string]$response.status
    if ($apiStatus -notmatch '^\d{3}$') { throw 'DART returned an unexpected response; details suppressed.' }
    if ($apiStatus -notin @('000','013')) { throw ('DART rejected the key/request. Status code: ' + $apiStatus) }
    $setupStage = 'prepare_directory'
    New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
    [IO.File]::WriteAllText((Join-Path $secretDir '.gitignore'), "*`r`n!.gitignore`r`n", [Text.UTF8Encoding]::new($false))
    $setupStage = 'create_secure_string'
    $normalizedSecure = ConvertTo-SecureString $plain -AsPlainText -Force
    $setupStage = 'dpapi_encrypt'
    $encryptedKey = ConvertFrom-SecureString $normalizedSecure
    $temporaryPath = Join-Path $secretDir ('dart-key-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    $setupStage = 'write_encrypted_file'
    [IO.File]::WriteAllText($temporaryPath, $encryptedKey, [Text.UTF8Encoding]::new($true))
    $setupStage = 'replace_encrypted_file'
    if ([IO.File]::Exists($secretPath)) { [IO.File]::Replace($temporaryPath, $secretPath, ($secretPath + '.previous')) }
    else { [IO.File]::Move($temporaryPath, $secretPath) }
    Write-Host 'DART connection verified. Key encrypted for this Windows account.' -ForegroundColor Green
} catch {
    # Only fixed classifications and exception metadata may leave this script.
    # Raw network errors can include the API key in a URL.
    $failureText = $_.Exception.Message
    if ($failureText -match '^OpenDART key must contain 40 ' -or
        $failureText -match '^DART rejected the key/request\. Status code: \d{3}$' -or
        $failureText -eq 'DART connection failed. Credential-bearing error details are suppressed.' -or
        $failureText -eq 'DART returned an unexpected response; details suppressed.') {
        throw
    }
    $safeFailure = 'DART_SETUP_FAILURE: stage={0}; type={1}; code={2}' -f $setupStage, $_.Exception.GetType().Name, $_.Exception.HResult
    throw $safeFailure
} finally {
    $plain = $null
    $encodedKey = $null
    $encryptedKey = $null
    $failureText = $null
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $normalizedSecure) { $normalizedSecure.Dispose() }
    if ($null -ne $secure) { $secure.Dispose() }
}

# Run on the original Windows PC, as the account that owns its DPAPI files.
# Prepare leaves the local service running. Cutover requires a separately stopped
# supervisor, schedules and manual senders; this helper never terminates them.
[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Cutover')][string]$Phase = 'Prepare',
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [string]$Repository = 'junseo96/newsautobot',
    [string]$IdentityFile,
    [switch]$Stopped
)

$script:MigrationCodeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))

function ConvertTo-MigrationArgument([string]$Value) {
    # CommandLineToArgvW quoting, including quotes and trailing backslashes.
    return '"' + ([regex]::Replace(([regex]::Replace($Value, '(\\*)"', '$1$1\"')), '(\\+)$', '$1$1')) + '"'
}

function Invoke-MigrationNative {
    param([string]$File, [string[]]$Arguments, [string]$InputText, [int]$TimeoutSeconds = 60)
    $process = New-Object Diagnostics.Process
    $process.StartInfo = New-Object Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName = $File
    $process.StartInfo.Arguments = (@($Arguments | ForEach-Object { ConvertTo-MigrationArgument $_ }) -join ' ')
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardInput = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    try {
        if (-not $process.Start()) { throw 'Could not start command' }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if ($null -ne $InputText) {
            $inputBytes = (New-Object Text.UTF8Encoding($false)).GetBytes($InputText)
            try { $process.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length) }
            finally { [Array]::Clear($inputBytes, 0, $inputBytes.Length) }
        }
        $process.StandardInput.BaseStream.Close()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill()
            throw 'Command timed out'
        }
        $output = $stdout.GetAwaiter().GetResult()
        $null = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw 'Command failed' }
        return $output
    } catch {
        # Upstream errors can echo an input token or authenticated URL.
        throw 'Migration command failed; sensitive command output suppressed.'
    } finally {
        $InputText = $null; $output = $null
        $process.Dispose()
    }
}

function Get-MigrationTools {
    param([string]$SourceRoot, [string]$CodeRoot)
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { Write-Host 'Required: run this helper on the original Windows PC.'; throw 'Windows required.' }
    foreach ($relative in @('work/rss-news-monitor.db', 'work/v11/supervisor.lock')) {
        if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $relative) -PathType Leaf)) { Write-Host "Required source state missing: $relative"; throw 'Required source state is missing.' }
    }
    $result = @{}
    foreach ($pair in @(@('Gh', 'gh'), @('Age', 'age'), @('Keygen', 'age-keygen'))) {
        $command = Get-Command $pair[1] -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { Write-Host "Missing prerequisite: $($pair[1])"; throw 'Required command missing.' }
        $result[$pair[0]] = $command.Source
    }
    . (Join-Path $CodeRoot 'outputs/rss-news-monitor/Resolve-Python.ps1')
    try {
        $result.Python = Resolve-NewsPython
        $null = Invoke-MigrationNative $result.Python @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)')
    } catch { Write-Host 'Missing or unusable prerequisite: Python 3.10 or newer (set NEWS_PYTHON if needed).'; throw 'Python prerequisite failed.' }
    return $result
}

function ConvertFrom-MigrationSecure([Security.SecureString]$Value) {
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
}

function Read-MigrationValue([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) {
        $secure = Read-Host "$Name (hidden input)" -AsSecureString
        try { $value = ConvertFrom-MigrationSecure $secure } finally { $secure.Dispose() }
    }
    if ([string]::IsNullOrWhiteSpace($value)) { throw 'A required value is empty.' }
    return $value.Trim()
}

function Get-MigrationInputs([string]$SourceRoot) {
    $values = @{}
    foreach ($name in @('NEWS_CODEX_API_KEY', 'NEWS_GMAIL_CLIENT_ID', 'NEWS_GMAIL_CLIENT_SECRET', 'NEWS_GMAIL_REFRESH_TOKEN')) {
        $values[$name] = Read-MigrationValue $name
    }
    . (Join-Path $script:MigrationCodeRoot 'outputs/telegram-forwarder/Telegram-Auth.ps1')
    $telegram = Get-NewsTelegramCredential -ConfigDir (Join-Path $SourceRoot '.telegram-forwarder')
    try { $values.NEWS_TELEGRAM_BOT_TOKEN = ConvertFrom-MigrationSecure $telegram.SecureToken } finally { $telegram.SecureToken.Dispose() }
    $values.NEWS_TELEGRAM_CHAT_ID = $telegram.ChatId
    $dart = [Environment]::GetEnvironmentVariable('NEWS_DART_KEY', 'Process')
    if ([string]::IsNullOrWhiteSpace($dart)) {
        $secure = ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $SourceRoot '.news-monitor-secrets/dart-key.dpapi')).Trim())
        try { $dart = ConvertFrom-MigrationSecure $secure } finally { $secure.Dispose() }
    }
    $values.NEWS_DART_KEY = $dart
    $url = [Environment]::GetEnvironmentVariable('NEWS_GRID_URL', 'Process')
    $token = [Environment]::GetEnvironmentVariable('NEWS_GRID_TOKEN', 'Process')
    if ($null -ne $url -or $null -ne $token) {
        if ([string]::IsNullOrWhiteSpace($url) -or [string]::IsNullOrWhiteSpace($token)) { throw 'Dashboard environment values must be configured together.' }
    } else {
        Add-Type -AssemblyName System.Security
        $config = [IO.File]::ReadAllText((Join-Path $SourceRoot 'work/grid-bridge/connection.json')) | ConvertFrom-Json
        $url = $config.url
        $bytes = [Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($config.protected_token), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        try { $token = [Text.Encoding]::UTF8.GetString($bytes) } finally { [Array]::Clear($bytes, 0, $bytes.Length) }
    }
    $uri = $null
    if (-not [Uri]::TryCreate($url, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $url -match '[\s\\]') { throw 'Dashboard URL must be an HTTPS base URL without embedded credentials.' }
    $values.NEWS_GRID_TOKEN = $token
    foreach ($value in $values.Values) {
        if ([string]::IsNullOrWhiteSpace($value) -or $value -match '[\x00-\x1f\x7f]') { throw 'A required value is invalid.' }
    }
    return @{ Secrets = $values; GridUrl = $uri.AbsoluteUri.TrimEnd('/') }
}

function Write-MigrationPrivateFile([string]$Path, [string]$Value) {
    # CreateNew protects existing keys. Tighten only our new file, never a
    # caller-selected parent directory or unrelated files within it.
    $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))
    $stream = New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
            $acl = New-Object Security.AccessControl.FileSecurity
            $acl.SetAccessRuleProtection($true, $false)
            $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
            $acl.SetOwner($sid)
            $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'Allow')))
            $stream.SetAccessControl($acl)
        }
        $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes($Value)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush() } finally { [Array]::Clear($bytes, 0, $bytes.Length) }
    } finally { $stream.Dispose() }
}

function New-MigrationScratch([string]$Parent) {
    $path = Join-Path $Parent ('scratch-' + [Guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $path -ErrorAction Stop
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl.SetOwner($sid)
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')))
        Set-Acl -LiteralPath $path -AclObject $acl -ErrorAction Stop
    }
    return $path
}

function Get-MigrationIdentity {
    param([string]$IdentityFile, [string]$Keygen, [bool]$RemoteExists, [switch]$ExistingOnly)
    $value = [Environment]::GetEnvironmentVariable('NEWS_STATE_AGE_KEY', 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) {
        if (Test-Path -LiteralPath $IdentityFile -PathType Leaf) { $value = [IO.File]::ReadAllText($IdentityFile) }
        elseif ($RemoteExists -or $ExistingOnly) { throw 'The existing age identity is required; refusing to replace the repository encryption key.' }
        else { $value = Invoke-MigrationNative $Keygen @() }
    }
    $lines = @($value -split '\r?\n' | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
    if ($lines.Count -ne 1 -or $lines[0] -notmatch '^AGE-SECRET-KEY-1[0-9A-Z]+$') { throw 'Invalid native age identity.' }
    if (-not (Test-Path -LiteralPath $IdentityFile)) { Write-MigrationPrivateFile $IdentityFile ($lines[0] + "`n") }
    else {
        $existing = @([IO.File]::ReadAllLines($IdentityFile) | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
        if ($existing.Count -ne 1 -or $existing[0] -cne $lines[0]) { throw 'The environment and existing age identity differ; no file was overwritten.' }
    }
    $recipient = (Invoke-MigrationNative $Keygen @('-y', $IdentityFile)).Trim()
    if ($recipient -notmatch '^age1[0-9a-z]+$') { throw 'Could not validate the native age identity.' }
    return $lines[0]
}

function Assert-MigrationIdle([string]$Gh, [string]$Repository) {
    $runs = Invoke-MigrationNative $Gh @('run', 'list', '--repo', $Repository, '--workflow', 'news-runtime.yml', '--limit', '100', '--json', 'status') | ConvertFrom-Json
    if (@($runs | Where-Object { $_.status -ne 'completed' }).Count) { throw 'Wait for the existing GitHub runtime to finish before migration.' }
}

function Wait-MigrationRun {
    param([string]$Gh, [string]$Repository, [string]$Workflow, [string]$Title, [int]$Minutes = 15)
    $deadline = [DateTime]::UtcNow.AddMinutes($Minutes)
    $reported = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        $runs = Invoke-MigrationNative $Gh @('run', 'list', '--repo', $Repository, '--workflow', $Workflow, '--branch', 'main', '--limit', '100', '--json', 'databaseId,displayTitle,status,conclusion') | ConvertFrom-Json
        $matches = @($runs | Where-Object { $_.displayTitle -ceq $Title })
        if ($matches.Count -gt 1) { throw 'Ambiguous workflow result.' }
        if ($matches.Count -eq 1) {
            $run = $matches[0]
            if ([string]$run.databaseId -notmatch '^[1-9][0-9]*$') { throw 'Invalid workflow identifier.' }
            if (-not $reported) { Write-Host "GitHub run: https://github.com/$Repository/actions/runs/$($run.databaseId)"; $reported = $true }
            if ($run.status -eq 'completed') {
                if ($run.conclusion -ne 'success') { throw 'GitHub workflow did not succeed.' }
                return $run
            }
        }
        Start-Sleep -Seconds 10
    }
    throw 'Timed out waiting for GitHub; do not rerun or restart the local sender until the run is inspected.'
}

function Invoke-NewsGitHubMigration {
    [CmdletBinding()]
    param([ValidateSet('Prepare', 'Cutover')][string]$Phase, [string]$SourceRoot,
          [string]$Repository = 'junseo96/newsautobot', [string]$IdentityFile, [switch]$Stopped)
    $ErrorActionPreference = 'Stop'
    if ($Phase -eq 'Cutover' -and -not $Stopped) { throw 'Cutover requires -Stopped after stopping the local supervisor, schedules and manual senders.' }
    $stage = 'local preflight'
    $disabled = $false; $activationAttempted = $false; $inputs = $null; $identity = $null
    try {
        if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'Invalid repository name.' }
        $SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd([IO.Path]::DirectorySeparatorChar)
        if (-not $IdentityFile) {
            if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is required or specify IdentityFile.' }
            $IdentityFile = Join-Path $env:LOCALAPPDATA 'Newsautobot/github-state/identity.txt'
        }
        $IdentityFile = [IO.Path]::GetFullPath($IdentityFile)
        foreach ($root in @($SourceRoot, $script:MigrationCodeRoot)) {
            if ($IdentityFile.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or $IdentityFile.StartsWith($root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'IdentityFile must be outside both the source root and this checkout.' }
        }
        # Do not let a junction redirect the private key back into a checkout
        # or another user's directory after the lexical containment check.
        $ancestor = $IdentityFile
        while ($ancestor) {
            if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'IdentityFile must not traverse links or junctions.' }
            $ancestor = [IO.Path]::GetDirectoryName($ancestor)
        }
        $privateRoot = [IO.Path]::GetDirectoryName($IdentityFile)
        $receiptPath = Join-Path $privateRoot 'prepare.json'
        $tools = Get-MigrationTools -SourceRoot $SourceRoot -CodeRoot $script:MigrationCodeRoot
        $stage = 'GitHub authentication and schedule disable'
        $null = Invoke-MigrationNative $tools.Gh @('auth', 'status')
        $repo = Invoke-MigrationNative $tools.Gh @('repo', 'view', $Repository, '--json', 'nameWithOwner,defaultBranchRef') | ConvertFrom-Json
        if ($repo.nameWithOwner -ine $Repository -or $repo.defaultBranchRef.name -ne 'main') { throw 'Repository main branch could not be verified.' }
        $null = Invoke-MigrationNative $tools.Gh @('variable', 'set', 'NEWS_SERVICE_ENABLED', '--repo', $Repository, '--body', 'false')
        $disabled = $true
        Assert-MigrationIdle $tools.Gh $Repository
        $releases = Invoke-MigrationNative $tools.Gh @('api', "repos/$Repository/releases?per_page=100", '--paginate', '--slurp') | ConvertFrom-Json
        if (@($releases | ForEach-Object { $_ } | Where-Object { $_.tag_name -eq 'news-state-bootstrap' }).Count) { throw 'The bootstrap release already exists; inspect it before any manual recovery. It will not be overwritten.' }
        if ($Phase -eq 'Prepare') {
            $stage = 'identity preparation and secure configuration'
            if (Test-Path -LiteralPath $receiptPath) { Remove-Item -LiteralPath $receiptPath -ErrorAction Stop }
            $names = Invoke-MigrationNative $tools.Gh @('secret', 'list', '--repo', $Repository, '--json', 'name') | ConvertFrom-Json
            $remoteExists = @($names | Where-Object { $_.name -eq 'NEWS_STATE_AGE_KEY' }).Count -gt 0
            $identity = Get-MigrationIdentity -IdentityFile $IdentityFile -Keygen $tools.Keygen -RemoteExists $remoteExists
            $inputs = Get-MigrationInputs -SourceRoot $SourceRoot
            $inputs.Secrets.NEWS_STATE_AGE_KEY = $identity
            foreach ($name in $inputs.Secrets.Keys) {
                $null = Invoke-MigrationNative -File $tools.Gh -Arguments @('secret', 'set', $name, '--repo', $Repository) -InputText $inputs.Secrets[$name]
            }
            $null = Invoke-MigrationNative $tools.Gh @('variable', 'set', 'NEWS_GRID_URL', '--repo', $Repository, '--body', $inputs.GridUrl)
            $stage = 'GitHub connection verification'
            $request = [Guid]::NewGuid().ToString('N')
            $null = Invoke-MigrationNative $tools.Gh @('workflow', 'run', 'news-connection-check.yml', '--repo', $Repository, '--ref', 'main', '-f', "request_id=$request")
            $run = Wait-MigrationRun -Gh $tools.Gh -Repository $Repository -Workflow 'news-connection-check.yml' -Title "News connection check $request" -Minutes 30
            $receipt = @{ source_root = $SourceRoot; repository = $Repository; verification_run_id = $run.databaseId; verified_at = [DateTime]::UtcNow.ToString('o') }
            [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
            Write-Host 'Prepare succeeded. GitHub scheduling remains disabled. Keep the age identity backed up privately.'
            Write-Host 'Disable local scheduled restarts and stop the local supervisor and manual senders after in-flight sends finish. Review uncertain receipts before Cutover.'
            $safeSource = $SourceRoot.Replace("'", "''"); $safeIdentity = $IdentityFile.Replace("'", "''")
            Write-Host "Next: .\deploy\cloud\Migrate-ToGitHub.ps1 -Phase Cutover -SourceRoot '$safeSource' -Repository '$Repository' -IdentityFile '$safeIdentity' -Stopped"
            return
        }
        $stage = 'verification of the prior Prepare result'
        $receipt = [IO.File]::ReadAllText($receiptPath) | ConvertFrom-Json
        $verified = [DateTime]::Parse($receipt.verified_at).ToUniversalTime()
        if ($receipt.source_root -ine $SourceRoot -or $receipt.repository -ine $Repository -or $verified -gt [DateTime]::UtcNow -or $verified -lt [DateTime]::UtcNow.AddHours(-24) -or [string]$receipt.verification_run_id -notmatch '^[1-9][0-9]*$') { throw 'A matching successful Prepare within the last 24 hours is required.' }
        $check = Invoke-MigrationNative $tools.Gh @('run', 'view', [string]$receipt.verification_run_id, '--repo', $Repository, '--json', 'status,conclusion,workflowName,headBranch') | ConvertFrom-Json
        if ($check.status -ne 'completed' -or $check.conclusion -ne 'success' -or $check.workflowName -ne 'News connection check' -or $check.headBranch -ne 'main') { throw 'The prior connection check could not be verified.' }
        $identity = Get-MigrationIdentity -IdentityFile $IdentityFile -Keygen $tools.Keygen -RemoteExists $true -ExistingOnly
        $stage = 'locked snapshot and encryption'
        $destination = Join-Path $privateRoot ('backups/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '/state.tar.age')
        $previous = @{}
        foreach ($name in @('NEWS_STATE_AGE_KEY', 'TEMP', 'TMP', 'TMPDIR')) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
        $scratch = New-MigrationScratch $privateRoot
        try {
            [Environment]::SetEnvironmentVariable('NEWS_STATE_AGE_KEY', $identity, 'Process')
            [Environment]::SetEnvironmentVariable('TEMP', $scratch, 'Process')
            [Environment]::SetEnvironmentVariable('TMP', $scratch, 'Process')
            [Environment]::SetEnvironmentVariable('TMPDIR', $scratch, 'Process')
            $null = Invoke-MigrationNative -File $tools.Python -Arguments @((Join-Path $script:MigrationCodeRoot 'deploy/cloud/artifact_state.py'), 'encrypt', '--root', $SourceRoot, '--destination', $destination, '--stopped') -TimeoutSeconds 1800
        } finally {
            foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
            Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or (Get-Item -LiteralPath $destination).Length -eq 0) { throw 'No encrypted snapshot was produced.' }
        $stage = 'encrypted bootstrap release upload'
        Assert-MigrationIdle $tools.Gh $Repository
        $null = Invoke-MigrationNative -File $tools.Gh -Arguments @('release', 'create', 'news-state-bootstrap', $destination, '--repo', $Repository, '--target', 'main', '--title', 'Encrypted news runtime bootstrap', '--notes', 'Operator-prepared age-encrypted state. Never upload a plaintext archive or identity.', '--latest=false') -TimeoutSeconds 1800
        $stage = 'GitHub bootstrap processing and checkpoint verification'
        $request = [Guid]::NewGuid().ToString('N')
        $null = Invoke-MigrationNative $tools.Gh @('workflow', 'run', 'news-runtime.yml', '--repo', $Repository, '--ref', 'main', '-f', 'bootstrap=true', '-f', "request_id=$request")
        $run = Wait-MigrationRun -Gh $tools.Gh -Repository $Repository -Workflow 'news-runtime.yml' -Title "News runtime $request" -Minutes 75
        $artifacts = Invoke-MigrationNative $tools.Gh @('api', "repos/$Repository/actions/runs/$($run.databaseId)/artifacts?per_page=100") | ConvertFrom-Json
        if (@($artifacts.artifacts | Where-Object { $_.name -eq 'newsautobot-state' -and -not $_.expired -and $_.size_in_bytes -gt 0 }).Count -ne 1) { throw 'Bootstrap did not produce a usable state artifact.' }
        $stage = 'schedule activation'
        $activationAttempted = $true
        $null = Invoke-MigrationNative $tools.Gh @('variable', 'set', 'NEWS_SERVICE_ENABLED', '--repo', $Repository, '--body', 'true')
        Write-Host 'Cutover succeeded. GitHub scheduled processing is enabled. Keep the original local supervisor, schedules and manual senders stopped.'
    } catch {
        if ($activationAttempted) {
            # A lost activation response can still mean GitHub applied it.
            # Re-disable if reachable; otherwise report the unknown outcome.
            $disabled = $false
            try {
                $null = Invoke-MigrationNative $tools.Gh @('variable', 'set', 'NEWS_SERVICE_ENABLED', '--repo', $Repository, '--body', 'false')
                $disabled = $true
            } catch { }
        }
        $schedule = if ($disabled) { 'GitHub scheduling remains disabled.' } else { 'Verify NEWS_SERVICE_ENABLED=false in GitHub; repository access may have failed before it could be disabled.' }
        throw "Migration stopped during $stage. $schedule Do not restart or repeat a bootstrap until any GitHub run and its receipts have been inspected. Sensitive errors suppressed."
    } finally {
        if ($inputs) { $inputs.Secrets.Clear() }
        $identity = $null; $inputs = $null
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-NewsGitHubMigration -Phase $Phase -SourceRoot $SourceRoot -Repository $Repository -IdentityFile $IdentityFile -Stopped:$Stopped
}

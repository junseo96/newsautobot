function Resolve-NewsPython {
    $candidates = @($env:NEWS_PYTHON)
    if ($env:USERPROFILE) {
        $candidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    $commands = if ([Environment]::OSVersion.Platform -eq 'Win32NT') { @('python.exe', 'python3.exe') } else { @('python3', 'python') }
    foreach ($name in $commands) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source -notmatch 'WindowsApps') { return $command.Source }
    }
    throw 'Python runtime not found. Set NEWS_PYTHON to the Python executable.'
}

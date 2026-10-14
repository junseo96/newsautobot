[CmdletBinding()]
param([switch]$Start)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$windowless = Join-Path ([IO.Path]::GetDirectoryName($python)) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowless -PathType Leaf)) { throw 'pythonw.exe unavailable' }
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$service = Join-Path $PSScriptRoot 'v12_service.py'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $windowless -Argument ('-X utf8 "' + $service + '" run') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'Newsflow-V12-Continuous' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Newsflow V12: important industrial changes24h; standard briefs06,10,14,18 KST; persistent receipts, deduplication, usage/coverage evidence. Signed-in user required.' -Force | Out-Null
$legacy = Get-ScheduledTask -TaskName 'Newsflow-V11-Continuous' -ErrorAction SilentlyContinue
if ($legacy) {
    Stop-ScheduledTask -TaskName $legacy.TaskName
    Disable-ScheduledTask -TaskName $legacy.TaskName | Out-Null
}
if ($Start) { Start-ScheduledTask -TaskName 'Newsflow-V12-Continuous' }
$task = Get-ScheduledTask -TaskName 'Newsflow-V12-Continuous'
[ordered]@{task_name=$task.TaskName; state=[string]$task.State; legacy='preserved disabled'; durable_state='work/v11; existing history retained'} | ConvertTo-Json

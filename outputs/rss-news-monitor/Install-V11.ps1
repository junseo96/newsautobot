[CmdletBinding()]
param([switch]$Start)
$ErrorActionPreference = 'Stop'
$name = 'Newsflow-V11-Continuous'
$scriptPath = Join-Path $PSScriptRoot 'Start-V11.ps1'
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$python = Resolve-NewsPython
$pythonWindowless = Join-Path ([IO.Path]::GetDirectoryName($python)) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless -PathType Leaf)) { throw 'pythonw.exe required for the hidden scheduler process.' }
$servicePath = Join-Path $PSScriptRoot 'v11_service.py'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('-X utf8 "' + $servicePath + '" run') -WorkingDirectory (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Newsflow V11: 24h incremental collection, read-only gpt-6-sol medium judgment, guarded Telegram delivery. Important news at night; standard 06:00-21:00 KST. Requires signed-in user and network.' -Force | Out-Null
if ($Start) { Start-ScheduledTask -TaskName $name }
$task = Get-ScheduledTask -TaskName $name
$info = Get-ScheduledTaskInfo -TaskName $name
[ordered]@{task_name=$name; state=[string]$task.State; last_run=$info.LastRunTime.ToString('o'); last_result=$info.LastTaskResult; startup='current-user logon; desktop lock allowed, sign-out/sleep/power-off unavailable'} | ConvertTo-Json

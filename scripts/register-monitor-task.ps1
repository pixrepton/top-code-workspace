# Register Windows Scheduled Task for scripts/monitor-stack.ps1 (P3.3)
param(
    [string]$TaskName = 'TopInstal-StackMonitor',
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$monitorScript = Join-Path $root 'scripts\monitor-stack.ps1'
$logPath = Join-Path $root 'monitor.log'

if (-not (Test-Path $monitorScript)) {
    throw "Missing $monitorScript"
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$monitorScript`" -LogPath `"$logPath`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Host
Write-Host "Registered scheduled task '$TaskName' every $IntervalMinutes min; log: $logPath"

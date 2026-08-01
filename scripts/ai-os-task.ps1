param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $ArgsFromUser
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'ai_os_task.py'
python $script @ArgsFromUser
exit $LASTEXITCODE

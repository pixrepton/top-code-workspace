$ErrorActionPreference = "Stop"

$root = Join-Path $PSScriptRoot "core"
$cases = Get-ChildItem $root -Directory

if ($cases.Count -lt 1) {
    throw "no agent behavior cases found"
}

foreach ($case in $cases) {
    $scenarioPath = Join-Path $case.FullName "scenario.md"
    $oraclePath = Join-Path $case.FullName "oracle.md"

    if (!(Test-Path $scenarioPath)) {
        throw "missing scenario.md: $($case.Name)"
    }

    if (!(Test-Path $oraclePath)) {
        throw "missing oracle.md: $($case.Name)"
    }

    $scenario = Get-Content -Raw $scenarioPath
    $oracle = Get-Content -Raw $oraclePath

    if ($scenario -match "Expected PASS|Failure Signals|Oracle:") {
        throw "oracle rubric leaked into scenario: $($case.Name)"
    }

    if ($oracle -notmatch "Expected PASS Signals") {
        throw "oracle missing PASS rubric: $($case.Name)"
    }

    if ($oracle -notmatch "Failure Signals") {
        throw "oracle missing failure rubric: $($case.Name)"
    }
}

"AGENT_BEHAVIOR_SUITE_OK cases=$($cases.Count)"

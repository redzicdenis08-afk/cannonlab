param(
    [Parameter(Mandatory = $true)]
    [string]$Manifest,
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab' }),
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ManifestPath = (Resolve-Path (Join-Path $RepoRoot $Manifest)).Path
if (-not $ManifestPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Manifest escapes CannonLab repository: $Manifest"
}

$Job = Get-Content $ManifestPath -Raw | ConvertFrom-Json
if ($Job.schema -ne 'cannonlab-forge-job-v1') {
    throw "Unsupported forge manifest schema: $($Job.schema)"
}
if ($Job.status -ne 'PASS') {
    throw "Forge manifest is not runnable: status=$($Job.status)"
}

$JobRoot = Split-Path $ManifestPath -Parent
$RunsRoot = Join-Path $JobRoot 'runs'
New-Item -ItemType Directory -Force -Path $RunsRoot | Out-Null

foreach ($Scenario in $Job.scenarios) {
    if ($Scenario.integrity.status -ne 'PASS') {
        throw "Scenario integrity is not PASS: $($Scenario.name) status=$($Scenario.integrity.status)"
    }

    Write-Host "===== Forge scenario: $($Scenario.name) ====="
    & (Join-Path $PSScriptRoot 'run-lab.ps1') `
        -Scenario ([IO.Path]::GetFileName($Scenario.path)) `
        -LabHome $LabHome `
        -TimeoutSeconds $TimeoutSeconds
    if ($LASTEXITCODE -ne 0) {
        throw "CannonLab run failed for $($Scenario.name) with exit code $LASTEXITCODE"
    }

    $Artifacts = Join-Path $RepoRoot 'lab-artifacts'
    $Destination = Join-Path $RunsRoot $Scenario.name
    if (Test-Path $Destination) {
        Remove-Item $Destination -Recurse -Force
    }
    Copy-Item $Artifacts $Destination -Recurse -Force

    $Results = Join-Path $Destination 'results'
    $AssertionOut = Join-Path $Destination 'assertion.json'
    $AssertArgs = @(
        (Join-Path $PSScriptRoot 'assert-results.py'),
        $Results
    )
    foreach ($Value in $Scenario.assert_args) {
        $AssertArgs += [string]$Value
    }
    $AssertArgs += @('--json-out', $AssertionOut)
    & py @AssertArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Evidence assertion failed for $($Scenario.name)"
    }

    if ($Scenario.corridor_args -and @($Scenario.corridor_args).Count -gt 0) {
        $CorridorOut = Join-Path $Destination 'output-corridor.json'
        $CorridorArgs = @(
            (Join-Path $PSScriptRoot 'analyze-output-corridor.py'),
            $Results
        )
        foreach ($Value in $Scenario.corridor_args) {
            $CorridorArgs += [string]$Value
        }
        $CorridorArgs += @('--json-out', $CorridorOut)
        & py @CorridorArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Output corridor repeatability failed for $($Scenario.name)"
        }
    }

    if ($Scenario.wall_breach_args -and @($Scenario.wall_breach_args).Count -gt 0) {
        $WallBreachOut = Join-Path $Destination 'wall-breach.json'
        $WallBreachArgs = @(
            (Join-Path $PSScriptRoot 'wall-breach-intelligence.py'),
            $Results
        )
        foreach ($Value in $Scenario.wall_breach_args) {
            $WallBreachArgs += [string]$Value
        }
        $WallBreachArgs += @('--json-out', $WallBreachOut)
        & py @WallBreachArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Wall-breach contract failed for $($Scenario.name)"
        }
    }
}

$Summary = [ordered]@{
    schema = 'cannonlab-forge-campaign-v1'
    job = $Job.job
    status = 'PASS'
    scenarios = @($Job.scenarios | ForEach-Object {
        [ordered]@{
            name = $_.name
            artifacts = "runs/$($_.name)"
            assertion = "runs/$($_.name)/assertion.json"
            output_corridor = if ($_.corridor_args -and @($_.corridor_args).Count -gt 0) {
                "runs/$($_.name)/output-corridor.json"
            } else {
                $null
            }
            wall_breach = if ($_.wall_breach_args -and @($_.wall_breach_args).Count -gt 0) {
                "runs/$($_.name)/wall-breach.json"
            } else {
                $null
            }
        }
    })
    truth_boundary = 'Local campaign pass only. Live ExtremeCraft readiness still requires recorded field evidence.'
}
$Summary | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $JobRoot 'campaign-summary.json') -Encoding utf8
$Summary | ConvertTo-Json -Depth 8
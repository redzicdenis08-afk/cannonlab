param(
    [Parameter(Mandatory = $true)]
    [string]$Manifest,
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab' }),
    [int]$TimeoutSeconds = 900,
    [ValidateSet('smoke', 'qualify', 'full')]
    [string]$MaxTier = 'smoke',
    [switch]$NoResume,
    [switch]$Force,
    [bool]$StopOnFailure = $true,
    [int]$WallClockBudgetSeconds = 0,
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ManifestPath = (Resolve-Path (Join-Path $RepoRoot $Manifest)).Path
if (-not $ManifestPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Manifest escapes CannonLab repository: $Manifest"
}
if ($TimeoutSeconds -lt 1) {
    throw 'TimeoutSeconds must be positive.'
}
if ($WallClockBudgetSeconds -lt 0) {
    throw 'WallClockBudgetSeconds cannot be negative.'
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
$StateRoot = Join-Path $JobRoot 'state'
New-Item -ItemType Directory -Force -Path $RunsRoot, $StateRoot | Out-Null

$TierOrder = @{ smoke = 0; qualify = 1; full = 2 }
$Resume = -not $NoResume
$HasTierMetadata = @($Job.scenarios | Where-Object {
    $_.PSObject.Properties.Name -contains 'tier'
}).Count -gt 0
$SelectedScenarios = @(
    if ($HasTierMetadata) {
        $Job.scenarios | Where-Object {
            $TierOrder[[string]$_.tier] -le $TierOrder[$MaxTier]
        } | Sort-Object @{ Expression = { [int]$_.tier_rank } }, @{ Expression = { [string]$_.name } }
    } else {
        # Legacy manifests had no tiers and always represented a full campaign.
        $Job.scenarios
    }
)
if ($SelectedScenarios.Count -eq 0) {
    throw "No scenarios selected for MaxTier=$MaxTier"
}

function Get-StringSha256([string]$Value) {
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    } finally {
        $Hasher.Dispose()
    }
}

$ToolHashes = [ordered]@{}
foreach ($RelativePath in @(
    'scripts/run-forge-campaign.ps1',
    'scripts/run-lab.ps1',
    'scripts/assert-results.py',
    'scripts/analyze-output-corridor.py',
    'scripts/wall-breach-intelligence.py'
)) {
    $ToolPath = Join-Path $RepoRoot $RelativePath
    if (Test-Path $ToolPath) {
        $ToolHashes[$RelativePath] = (Get-FileHash $ToolPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$RuntimeHashes = [ordered]@{}
$RuntimeCandidates = @()
$BuildLibs = Join-Path $RepoRoot 'build\libs'
if (Test-Path $BuildLibs) {
    $RuntimeCandidates += @(Get-ChildItem $BuildLibs -Filter '*.jar' -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
}
foreach ($PluginDirectory in @((Join-Path $LabHome 'server\plugins'), (Join-Path $LabHome 'plugins'))) {
    if (Test-Path $PluginDirectory) {
        $RuntimeCandidates += @(Get-ChildItem $PluginDirectory -Filter '*.jar' -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    }
}
foreach ($RuntimePath in @((Join-Path $LabHome 'server\server.jar'), (Join-Path $LabHome 'server.jar'))) {
    if (Test-Path $RuntimePath -PathType Leaf) {
        $RuntimeCandidates += $RuntimePath
    }
}
foreach ($RuntimePath in @($RuntimeCandidates | Sort-Object -Unique)) {
    $RuntimeHashes[$RuntimePath] = (Get-FileHash $RuntimePath -Algorithm SHA256).Hash.ToLowerInvariant()
}
$RuntimeFingerprintComplete = $RuntimeHashes.Count -gt 0
$CannonLabEnvironment = [ordered]@{}
Get-ChildItem Env: | Where-Object { $_.Name -like 'CANNONLAB_*' } | Sort-Object Name | ForEach-Object {
    $CannonLabEnvironment[$_.Name] = $_.Value
}

$CampaignStarted = [DateTime]::UtcNow
$Stopwatch = [Diagnostics.Stopwatch]::StartNew()
$Executed = @()
$Skipped = @()
$Failures = @()
$Planned = @()
$BudgetExhausted = $false

function Test-PassJson([string]$Path) {
    if (-not (Test-Path $Path -PathType Leaf)) {
        return $false
    }
    try {
        $Payload = Get-Content $Path -Raw | ConvertFrom-Json
        return ([string]$Payload.status).ToUpperInvariant() -eq 'PASS'
    } catch {
        return $false
    }
}

foreach ($Scenario in $SelectedScenarios) {
    if ($Scenario.integrity.status -ne 'PASS') {
        throw "Scenario integrity is not PASS: $($Scenario.name) status=$($Scenario.integrity.status)"
    }

    $Tier = if ($Scenario.PSObject.Properties.Name -contains 'tier') { [string]$Scenario.tier } else { 'full' }
    $Destination = Join-Path $RunsRoot $Scenario.name
    $FingerprintPayload = [ordered]@{
        schema = 'cannonlab-forge-stage-fingerprint-v2'
        candidate_sha256 = [string]$Job.candidate.sha256
        scenario_sha256 = [string]$Scenario.sha256
        expected_shots = [int]$Scenario.expected_shots
        tier = $Tier
        assert_args = @($Scenario.assert_args)
        corridor_args = @($Scenario.corridor_args)
        wall_breach_args = @($Scenario.wall_breach_args)
        tool_hashes = $ToolHashes
        runtime_hashes = $RuntimeHashes
        lab_home = [IO.Path]::GetFullPath($LabHome)
        cannonlab_environment = $CannonLabEnvironment
    }
    $Fingerprint = Get-StringSha256 ($FingerprintPayload | ConvertTo-Json -Depth 20 -Compress)
    $StatePath = Join-Path $StateRoot "$($Scenario.name).json"
    $ResumeHit = $false
    if ($Resume -and -not $Force -and $RuntimeFingerprintComplete -and (Test-Path $StatePath)) {
        try {
            $Previous = Get-Content $StatePath -Raw | ConvertFrom-Json
            $ResumeHit = $Previous.status -eq 'PASS' `
                -and $Previous.fingerprint -eq $Fingerprint `
                -and (Test-PassJson (Join-Path $Destination 'assertion.json'))
            if ($ResumeHit -and $Scenario.corridor_args -and @($Scenario.corridor_args).Count -gt 0) {
                $ResumeHit = Test-PassJson (Join-Path $Destination 'output-corridor.json')
            }
            if ($ResumeHit -and $Scenario.wall_breach_args -and @($Scenario.wall_breach_args).Count -gt 0) {
                $ResumeHit = Test-PassJson (Join-Path $Destination 'wall-breach.json')
            }
        } catch {
            $ResumeHit = $false
        }
    }

    if ($PlanOnly) {
        $Planned += [ordered]@{
            name = $Scenario.name
            tier = $Tier
            expected_shots = [int]$Scenario.expected_shots
            action = if ($ResumeHit) { 'CACHE_HIT' } else { 'RUN' }
            fingerprint = $Fingerprint
            runtime_fingerprint_complete = $RuntimeFingerprintComplete
        }
        continue
    }

    if ($WallClockBudgetSeconds -gt 0 -and $Stopwatch.Elapsed.TotalSeconds -ge $WallClockBudgetSeconds) {
        $BudgetExhausted = $true
        break
    }

    if ($ResumeHit) {
        Write-Host "===== Forge scenario: $($Scenario.name) [SKIP exact cached PASS] ====="
        $Skipped += [ordered]@{
            name = $Scenario.name
            tier = $Tier
            fingerprint = $Fingerprint
            state = "state/$($Scenario.name).json"
            artifacts = "runs/$($Scenario.name)"
        }
        continue
    }

    $ScenarioStarted = [DateTime]::UtcNow
    $Failure = $null
    try {
        $RemainingSeconds = if ($WallClockBudgetSeconds -gt 0) {
            [Math]::Floor($WallClockBudgetSeconds - $Stopwatch.Elapsed.TotalSeconds)
        } else {
            $TimeoutSeconds
        }
        if ($RemainingSeconds -lt 1) {
            throw 'Wall-clock budget exhausted before scenario execution.'
        }
        $EffectiveTimeout = [Math]::Min($TimeoutSeconds, [int]$RemainingSeconds)
        Write-Host "===== Forge scenario: $($Scenario.name) [tier=$Tier shots=$($Scenario.expected_shots) timeout=${EffectiveTimeout}s] ====="
        & (Join-Path $PSScriptRoot 'run-lab.ps1') `
            -Scenario ([IO.Path]::GetFileName($Scenario.path)) `
            -LabHome $LabHome `
            -TimeoutSeconds $EffectiveTimeout
        if ($LASTEXITCODE -ne 0) {
            throw "CannonLab run failed with exit code $LASTEXITCODE"
        }

        $Artifacts = Join-Path $RepoRoot 'lab-artifacts'
        if (Test-Path $Destination) {
            Remove-Item $Destination -Recurse -Force
        }
        Copy-Item $Artifacts $Destination -Recurse -Force

        $Results = Join-Path $Destination 'results'
        $AssertionOut = Join-Path $Destination 'assertion.json'
        $AssertArgs = @((Join-Path $PSScriptRoot 'assert-results.py'), $Results)
        foreach ($Value in $Scenario.assert_args) { $AssertArgs += [string]$Value }
        $AssertArgs += @('--json-out', $AssertionOut)
        & py @AssertArgs
        if ($LASTEXITCODE -ne 0) { throw 'Evidence assertion failed.' }

        if ($Scenario.corridor_args -and @($Scenario.corridor_args).Count -gt 0) {
            $CorridorOut = Join-Path $Destination 'output-corridor.json'
            $CorridorArgs = @((Join-Path $PSScriptRoot 'analyze-output-corridor.py'), $Results)
            foreach ($Value in $Scenario.corridor_args) { $CorridorArgs += [string]$Value }
            $CorridorArgs += @('--json-out', $CorridorOut)
            & py @CorridorArgs
            if ($LASTEXITCODE -ne 0) { throw 'Output corridor repeatability failed.' }
        }

        if ($Scenario.wall_breach_args -and @($Scenario.wall_breach_args).Count -gt 0) {
            $WallBreachOut = Join-Path $Destination 'wall-breach.json'
            $WallBreachArgs = @((Join-Path $PSScriptRoot 'wall-breach-intelligence.py'), $Results)
            foreach ($Value in $Scenario.wall_breach_args) { $WallBreachArgs += [string]$Value }
            $WallBreachArgs += @('--json-out', $WallBreachOut)
            & py @WallBreachArgs
            if ($LASTEXITCODE -ne 0) { throw 'Wall-breach contract failed.' }
        }

        $Elapsed = [Math]::Round(([DateTime]::UtcNow - $ScenarioStarted).TotalSeconds, 3)
        $State = [ordered]@{
            schema = 'cannonlab-forge-stage-state-v2'
            status = 'PASS'
            job = $Job.job
            scenario = $Scenario.name
            tier = $Tier
            fingerprint = $Fingerprint
            fingerprint_payload = $FingerprintPayload
            runtime_fingerprint_complete = $RuntimeFingerprintComplete
            completed_utc = [DateTime]::UtcNow.ToString('o')
            elapsed_seconds = $Elapsed
            artifacts = "runs/$($Scenario.name)"
            truth_boundary = 'Exact local runtime fingerprint only. This state never proves live ExtremeCraft parity.'
        }
        $State | ConvertTo-Json -Depth 20 | Set-Content $StatePath -Encoding utf8
        $Executed += $State
    } catch {
        $Failure = [ordered]@{
            name = $Scenario.name
            tier = $Tier
            fingerprint = $Fingerprint
            elapsed_seconds = [Math]::Round(([DateTime]::UtcNow - $ScenarioStarted).TotalSeconds, 3)
            error = $_.Exception.Message
        }
        $Failures += $Failure
        if ($Failure.error -like '*budget exhausted*') {
            $BudgetExhausted = $true
        }
        if ($StopOnFailure) {
            break
        }
    }
}

$Stopwatch.Stop()
$Status = if ($PlanOnly) {
    'PLANNED'
} elseif ($Failures.Count -gt 0) {
    if ($BudgetExhausted) { 'BUDGET_EXHAUSTED' } else { 'FAIL' }
} elseif ($BudgetExhausted) {
    'BUDGET_EXHAUSTED'
} else {
    'PASS'
}
$Summary = [ordered]@{
    schema = 'cannonlab-forge-campaign-v3'
    job = $Job.job
    status = $Status
    max_tier = $MaxTier
    resume_enabled = $Resume
    runtime_fingerprint_complete = $RuntimeFingerprintComplete
    force = [bool]$Force
    stop_on_failure = $StopOnFailure
    wall_clock_budget_seconds = $WallClockBudgetSeconds
    selected_scenarios = $SelectedScenarios.Count
    executed_count = $Executed.Count
    skipped_count = $Skipped.Count
    failure_count = $Failures.Count
    elapsed_seconds = [Math]::Round($Stopwatch.Elapsed.TotalSeconds, 3)
    executed = $Executed
    skipped = $Skipped
    failures = $Failures
    planned = $Planned
    next_tier = if ($Status -eq 'PASS' -and $MaxTier -eq 'smoke') { 'qualify' } elseif ($Status -eq 'PASS' -and $MaxTier -eq 'qualify') { 'full' } else { $null }
    truth_boundary = 'Smoke and qualification accelerate local iteration only. Full local promotion and live ExtremeCraft evidence remain separate gates.'
}
$TierSummaryPath = Join-Path $JobRoot "campaign-summary-$MaxTier.json"
$Summary | ConvertTo-Json -Depth 20 | Set-Content $TierSummaryPath -Encoding utf8
$Summary | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $JobRoot 'campaign-summary.json') -Encoding utf8
$Summary | ConvertTo-Json -Depth 20
if ($Status -notin @('PASS', 'PLANNED')) {
    exit 2
}

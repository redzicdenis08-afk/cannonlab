param(
    [string]$Scenario = 'probe-smoke.yml',
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab' }),
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ServerRoot = Join-Path $LabHome 'server'
$ArtifactRoot = Join-Path $RepoRoot 'lab-artifacts'
$ResultsRoot = Join-Path $ServerRoot 'plugins\CannonLab\results'
$FreshWorld = $env:CANNONLAB_FRESH_WORLD -match '^(?i:1|true|yes)$'
if ($env:CANNONLAB_FRESH_WORLD -and
        $env:CANNONLAB_FRESH_WORLD -notmatch '^(?i:0|false|no|1|true|yes)$') {
    throw "Invalid CANNONLAB_FRESH_WORLD=$($env:CANNONLAB_FRESH_WORLD)"
}

& (Join-Path $PSScriptRoot 'prepare-server.ps1') -LabHome $LabHome

if (Test-Path $ArtifactRoot) {
    Remove-Item $ArtifactRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null

$ScenarioPath = Join-Path (Join-Path $RepoRoot 'scenarios') $Scenario
if (-not (Test-Path $ScenarioPath)) {
    throw "Scenario does not exist: $ScenarioPath"
}
$ScenarioAudit = Join-Path $PSScriptRoot 'scenario-integrity-audit.py'
$ScenarioAuditOut = Join-Path $ArtifactRoot 'scenario-integrity.json'
$ScenarioAuditArgs = @($ScenarioAudit, $ScenarioPath, '--json-out', $ScenarioAuditOut)
if ($env:CANNONLAB_REQUIRE_FIELD_CANDIDATE -match '^(?i:1|true|yes)$') {
    $ScenarioAuditArgs += '--require-field-candidate'
} elseif ($env:CANNONLAB_REQUIRE_FIELD_CANDIDATE -and
        $env:CANNONLAB_REQUIRE_FIELD_CANDIDATE -notmatch '^(?i:0|false|no)$') {
    throw "Invalid CANNONLAB_REQUIRE_FIELD_CANDIDATE=$($env:CANNONLAB_REQUIRE_FIELD_CANDIDATE)"
}
if ($env:CANNONLAB_REQUIRE_READINESS -match '^(?i:1|true|yes)$') {
    $ScenarioAuditArgs += '--require-readiness'
} elseif ($env:CANNONLAB_REQUIRE_READINESS -and
        $env:CANNONLAB_REQUIRE_READINESS -notmatch '^(?i:0|false|no)$') {
    throw "Invalid CANNONLAB_REQUIRE_READINESS=$($env:CANNONLAB_REQUIRE_READINESS)"
}
& py @ScenarioAuditArgs | Set-Content (Join-Path $ArtifactRoot 'scenario-integrity.stdout.json')
if ($LASTEXITCODE -ne 0) {
    throw "Scenario integrity audit failed with exit code $LASTEXITCODE."
}
$ExpectedScenarioName = (Get-Content $ScenarioAuditOut -Raw | ConvertFrom-Json).name
if (-not $ExpectedScenarioName) {
    throw 'Scenario integrity report did not contain a scenario name.'
}

if (Test-Path $ResultsRoot) {
    Remove-Item $ResultsRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ResultsRoot | Out-Null
if ($FreshWorld) {
    foreach ($WorldName in @('world', 'world_nether', 'world_the_end')) {
        $WorldPath = Join-Path $ServerRoot $WorldName
        if (Test-Path $WorldPath) {
            Remove-Item $WorldPath -Recurse -Force
        }
    }
}

$Stdout = Join-Path $ArtifactRoot 'server-stdout.log'
$Stderr = Join-Path $ArtifactRoot 'server-stderr.log'
$JavaArguments = @(
    '-Xms1G',
    '-Xmx4G',
    "-Dcannonlab.scenario=$Scenario",
    "-Dcannonlab.fresh-world=$($FreshWorld.ToString().ToLowerInvariant())",
    '-jar',
    'server.jar',
    '--nogui'
)

Write-Host "Starting CannonLab scenario $Scenario"
$RunStartedUtc = [DateTime]::UtcNow
$Process = Start-Process -FilePath 'java' -ArgumentList $JavaArguments -WorkingDirectory $ServerRoot -PassThru -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr

$Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (-not $Process.HasExited -and (Get-Date) -lt $Deadline) {
    Start-Sleep -Seconds 2
    $Process.Refresh()
}

if (-not $Process.HasExited) {
    Stop-Process -Id $Process.Id -Force
    throw "CannonLab timed out after $TimeoutSeconds seconds."
}
$Process.WaitForExit()
$Process.Refresh()
$ServerExitCode = $Process.ExitCode

if ($null -ne $ServerExitCode -and $ServerExitCode -ne 0) {
    Write-Host '===== server stdout tail ====='
    if (Test-Path $Stdout) { Get-Content $Stdout -Tail 120 }
    Write-Host '===== server stderr tail ====='
    if (Test-Path $Stderr) { Get-Content $Stderr -Tail 120 }
    throw "CannonLab server exited with code $ServerExitCode."
}

if (Test-Path $ResultsRoot) {
    Copy-Item $ResultsRoot (Join-Path $ArtifactRoot 'results') -Recurse -Force
}

$Summary = Get-ChildItem $ArtifactRoot -Recurse -Filter 'run-summary.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Summary) {
    Write-Host '===== server stdout tail ====='
    if (Test-Path $Stdout) { Get-Content $Stdout -Tail 120 }
    Write-Host '===== server stderr tail ====='
    if (Test-Path $Stderr) { Get-Content $Stderr -Tail 120 }
    throw 'Server exited without a CannonLab run summary.'
}

$SummaryJson = Get-Content $Summary.FullName -Raw | ConvertFrom-Json
if ($Summary.LastWriteTimeUtc -lt $RunStartedUtc.AddSeconds(-2)) {
    throw "Run summary predates this launch: $($Summary.FullName)"
}
if ($SummaryJson.scenario -ne $ExpectedScenarioName) {
    throw "Run summary scenario mismatch: expected '$ExpectedScenarioName', got '$($SummaryJson.scenario)'."
}

Write-Host '===== CannonLab result ====='
Get-Content $Summary.FullName

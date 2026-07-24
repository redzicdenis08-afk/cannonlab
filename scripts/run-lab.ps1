param(
    [string]$Scenario = 'probe-smoke.yml',
    [string]$ScenarioPath = '',
    [string]$CannonSnapshot = '',
    [string]$CannonRuntimeName = '',
    [string]$LabHome = $(
        if ($env:CANNONLAB_HOME) {
            $env:CANNONLAB_HOME
        } elseif ([IO.Path]::DirectorySeparatorChar -eq '\') {
            'C:\CannonLab'
        } else {
            Join-Path $HOME 'CannonLab'
        }
    ),
    [string]$Profile = $(if ($env:CANNONLAB_PROFILE) { $env:CANNONLAB_PROFILE } else { '' }),
    [int]$ArenaRadiusX = 0,
    [int]$ArenaRadiusY = 0,
    [int]$ArenaRadiusZ = 0,
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

$PrepareArguments = @{ LabHome = $LabHome }
if ($ArenaRadiusX -gt 0) { $PrepareArguments.ArenaRadiusX = $ArenaRadiusX }
if ($ArenaRadiusY -gt 0) { $PrepareArguments.ArenaRadiusY = $ArenaRadiusY }
if ($ArenaRadiusZ -gt 0) { $PrepareArguments.ArenaRadiusZ = $ArenaRadiusZ }
& (Join-Path $PSScriptRoot 'prepare-server.ps1') @PrepareArguments

$ResolvedScenarioPath = if ($ScenarioPath) {
    (Resolve-Path $ScenarioPath).Path
} else {
    (Resolve-Path (Join-Path (Join-Path $RepoRoot 'scenarios') $Scenario)).Path
}
if (-not $ResolvedScenarioPath.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $ResolvedScenarioPath.StartsWith((Split-Path $RepoRoot -Parent), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Scenario snapshot escapes CannonLab roots: $ResolvedScenarioPath"
}
$Scenario = [IO.Path]::GetFileName($ResolvedScenarioPath)
$ServerScenarioDirectory = Join-Path $ServerRoot 'plugins\CannonLab\scenarios'
New-Item -ItemType Directory -Force -Path $ServerScenarioDirectory | Out-Null
Copy-Item $ResolvedScenarioPath (Join-Path $ServerScenarioDirectory $Scenario) -Force

if ($CannonSnapshot) {
    if (-not $CannonRuntimeName) {
        throw 'CannonRuntimeName is required with CannonSnapshot.'
    }
    if ([IO.Path]::GetFileName($CannonRuntimeName) -ne $CannonRuntimeName -or
            -not $CannonRuntimeName.EndsWith('.schem', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "CannonRuntimeName must be one .schem filename: $CannonRuntimeName"
    }
    $ResolvedCannonSnapshot = (Resolve-Path $CannonSnapshot).Path
    if (-not $ResolvedCannonSnapshot.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
            -not $ResolvedCannonSnapshot.StartsWith((Split-Path $RepoRoot -Parent), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Cannon snapshot escapes CannonLab roots: $ResolvedCannonSnapshot"
    }
    $ServerCannonDirectory = Join-Path $ServerRoot 'plugins\CannonLab\cannons'
    New-Item -ItemType Directory -Force -Path $ServerCannonDirectory | Out-Null
    $ServerCannonPath = Join-Path $ServerCannonDirectory $CannonRuntimeName
    if ($ResolvedCannonSnapshot.EndsWith('.b64', [System.StringComparison]::OrdinalIgnoreCase)) {
        $Bytes = [Convert]::FromBase64String((Get-Content $ResolvedCannonSnapshot -Raw).Trim())
        [IO.File]::WriteAllBytes($ServerCannonPath, $Bytes)
    } else {
        Copy-Item $ResolvedCannonSnapshot $ServerCannonPath -Force
    }
}

if (Test-Path $ArtifactRoot) {
    Remove-Item $ArtifactRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null

$ProfileManifest = $null
if ($Profile) {
    $ProfilePath = if ([IO.Path]::IsPathRooted($Profile)) {
        $Profile
    } else {
        Join-Path $RepoRoot (Join-Path 'profiles' $Profile)
    }
    if (-not (Test-Path $ProfilePath)) {
        throw "Runtime profile does not exist: $ProfilePath"
    }
    $ProfileManifest = Join-Path $ArtifactRoot 'runtime-profile-manifest.json'
    & py (Join-Path $PSScriptRoot 'apply-runtime-profile.py') $ProfilePath `
        --server-root $ServerRoot `
        --manifest-out $ProfileManifest `
        | Set-Content (Join-Path $ArtifactRoot 'runtime-profile.stdout.json')
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime profile application failed with exit code $LASTEXITCODE."
    }
}

$PluginStackPath = Join-Path $ArtifactRoot 'plugin-stack.json'
& py (Join-Path $PSScriptRoot 'inventory-plugin-stack.py') `
    --plugins-dir (Join-Path $ServerRoot 'plugins') `
    --json-out $PluginStackPath `
    | Set-Content (Join-Path $ArtifactRoot 'plugin-stack.stdout.json')
if ($LASTEXITCODE -ne 0) {
    throw "Plugin stack inventory failed with exit code $LASTEXITCODE."
}
$PluginStack = Get-Content $PluginStackPath -Raw | ConvertFrom-Json

$ScenarioPath = $ResolvedScenarioPath
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
    "-Dcannonlab.fresh-world=$($FreshWorld.ToString().ToLowerInvariant())"
)
if ($ProfileManifest) {
    $ProfileJson = Get-Content $ProfileManifest -Raw | ConvertFrom-Json
    $JavaArguments += @(
        "-Dcannonlab.profile.id=$($ProfileJson.profile_id)",
        "-Dcannonlab.profile.grade=$($ProfileJson.evidence_grade)",
        "-Dcannonlab.profile.sha256=$($ProfileJson.profile_sha256)"
    )
}
$JavaArguments += "-Dcannonlab.plugin-stack.sha256=$($PluginStack.stack_sha256)"
$JavaArguments += @('-jar', 'server.jar', '--nogui')

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

param(
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab-EC-Calibrations' }),
    [string]$Profile = 'extremecraft-observed.yml',
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ServerRoot = Join-Path $LabHome 'server'
$ArtifactRoot = Join-Path $RepoRoot 'lab-artifacts\native-calibrations'
$Scenarios = @(
    'ec-native-dry-obsidian-4hit.yml',
    'ec-native-watered-obsidian-shield.yml'
)

if ($env:CANNONLAB_ACCEPT_EULA -ne 'TRUE') {
    throw 'Set CANNONLAB_ACCEPT_EULA=TRUE only after accepting the Minecraft EULA.'
}
if (-not $env:CANNONLAB_SAKURA_JAR -and -not (Test-Path (Join-Path $LabHome 'sakura-26.1.2.jar')) -and -not (Test-Path (Join-Path $ServerRoot 'sakura-26.1.2.jar'))) {
    throw 'Native calibrations require a pinned Sakura 26.1.2 jar. Set CANNONLAB_SAKURA_JAR.'
}

& (Join-Path $PSScriptRoot 'prepare-server.ps1') -LabHome $LabHome
if (Test-Path $ArtifactRoot) {
    Remove-Item $ArtifactRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null

$ProfilePath = if ([IO.Path]::IsPathRooted($Profile)) { $Profile } else { Join-Path $RepoRoot (Join-Path 'profiles' $Profile) }
$Manifest = Join-Path $ArtifactRoot 'runtime-profile-manifest.json'
& py (Join-Path $PSScriptRoot 'apply-runtime-profile.py') $ProfilePath --server-root $ServerRoot --manifest-out $Manifest *> (Join-Path $ArtifactRoot 'profile-apply.json')
if ($LASTEXITCODE -ne 0) {
    throw "Profile application failed with exit code $LASTEXITCODE."
}
$ProfileJson = Get-Content $Manifest -Raw | ConvertFrom-Json
$PluginStackManifest = Join-Path $ArtifactRoot 'plugin-stack.json'
& py (Join-Path $PSScriptRoot 'inventory-plugin-stack.py') `
    --plugins-dir (Join-Path $ServerRoot 'plugins') `
    --json-out $PluginStackManifest `
    *> (Join-Path $ArtifactRoot 'plugin-stack.stdout.json')
if ($LASTEXITCODE -ne 0) {
    throw "Plugin stack inventory failed with exit code $LASTEXITCODE."
}
$PluginStackJson = Get-Content $PluginStackManifest -Raw | ConvertFrom-Json

foreach ($Scenario in $Scenarios) {
    $ScenarioName = [IO.Path]::GetFileNameWithoutExtension($Scenario)
    $ScenarioArtifacts = Join-Path $ArtifactRoot $ScenarioName
    New-Item -ItemType Directory -Force -Path $ScenarioArtifacts | Out-Null

    $ResultsRoot = Join-Path $ServerRoot 'plugins\CannonLab\results'
    if (Test-Path $ResultsRoot) {
        Remove-Item $ResultsRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $ResultsRoot | Out-Null
    @('world', 'world_nether', 'world_the_end', 'worldeditregentempworld') | ForEach-Object {
        $WorldPath = Join-Path $ServerRoot $_
        if (Test-Path $WorldPath) {
            Remove-Item $WorldPath -Recurse -Force
        }
    }

    $Stdout = Join-Path $ScenarioArtifacts 'server-stdout.log'
    $Stderr = Join-Path $ScenarioArtifacts 'server-stderr.log'
    $Arguments = @(
        '-Xms1G',
        '-Xmx4G',
        "-Dcannonlab.scenario=$Scenario",
        '-Dcannonlab.fresh-world=true',
        "-Dcannonlab.profile.id=$($ProfileJson.profile_id)",
        "-Dcannonlab.profile.grade=$($ProfileJson.evidence_grade)",
        "-Dcannonlab.profile.sha256=$($ProfileJson.profile_sha256)",
        "-Dcannonlab.plugin-stack.sha256=$($PluginStackJson.stack_sha256)",
        '-jar',
        'server.jar',
        '--nogui'
    )
    $Process = Start-Process -FilePath 'java' -ArgumentList $Arguments -WorkingDirectory $ServerRoot -PassThru -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not $Process.HasExited -and (Get-Date) -lt $Deadline) {
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force
        throw "$Scenario timed out after $TimeoutSeconds seconds."
    }
    $Process.WaitForExit()
    $Process.Refresh()
    $ServerExitCode = if ($null -eq $Process.ExitCode) { 0 } else { $Process.ExitCode }
    if ($ServerExitCode -ne 0) {
        throw "$Scenario server exited with code $ServerExitCode."
    }

    $Summary = Get-ChildItem $ResultsRoot -Recurse -Filter 'run-summary.json' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $Summary) {
        throw "$Scenario produced no run-summary.json."
    }
    $SummaryJson = Get-Content $Summary.FullName -Raw | ConvertFrom-Json
    if ($SummaryJson.scenario -ne $ScenarioName) {
        throw "Scenario mismatch: expected $ScenarioName, got $($SummaryJson.scenario)."
    }
    Copy-Item $Summary.FullName (Join-Path $ScenarioArtifacts 'run-summary.json') -Force
    if ($SummaryJson.finish_reason -ne 'complete') {
        throw "$Scenario failed its runtime contract: $($SummaryJson.finish_reason)."
    }
    Write-Host "$ScenarioName PASS"
}

Write-Host "Native EC candidate calibrations PASS | profile=$($ProfileJson.profile_id) | sha256=$($ProfileJson.profile_sha256)"

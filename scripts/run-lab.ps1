param(
    [string]$Scenario = 'probe-smoke.yml',
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab' }),
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ServerRoot = Join-Path $LabHome 'server'
$ArtifactRoot = Join-Path $RepoRoot 'lab-artifacts'

& (Join-Path $PSScriptRoot 'prepare-server.ps1') -LabHome $LabHome

if (Test-Path $ArtifactRoot) {
    Remove-Item $ArtifactRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ArtifactRoot | Out-Null

$Stdout = Join-Path $ArtifactRoot 'server-stdout.log'
$Stderr = Join-Path $ArtifactRoot 'server-stderr.log'
$ServerJar = Join-Path $ServerRoot 'server.jar'
$JavaArguments = @(
    '-Xms1G',
    '-Xmx4G',
    "-Dcannonlab.scenario=$Scenario",
    '-jar',
    $ServerJar,
    '--nogui'
)

Write-Host "Starting CannonLab scenario $Scenario"
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

$ResultsRoot = Join-Path $ServerRoot 'plugins\CannonLab\results'
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

Write-Host '===== CannonLab result ====='
Get-Content $Summary.FullName

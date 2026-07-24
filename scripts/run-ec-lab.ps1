param(
    [Parameter(Mandatory=$true)][string]$Scenario,
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab-EC' }),
    [string]$Profile = 'extremecraft-observed.yml',
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
if ($env:CANNONLAB_ACCEPT_EULA -ne 'TRUE') {
    throw 'Set CANNONLAB_ACCEPT_EULA=TRUE only after accepting the Minecraft EULA.'
}
if (-not $env:CANNONLAB_SAKURA_JAR -and -not (Test-Path (Join-Path $LabHome 'sakura-26.1.2.jar')) -and -not (Test-Path (Join-Path $LabHome 'server\sakura-26.1.2.jar'))) {
    throw 'EC parity runs require a pinned Sakura 26.1.2 jar. Set CANNONLAB_SAKURA_JAR or place sakura-26.1.2.jar in the lab home.'
}
$env:CANNONLAB_FRESH_WORLD = 'true'
& (Join-Path $PSScriptRoot 'run-lab.ps1') `
    -Scenario $Scenario `
    -LabHome $LabHome `
    -Profile $Profile `
    -TimeoutSeconds $TimeoutSeconds

param(
    [string]$LabHome = $(if ($env:CANNONLAB_HOME) { $env:CANNONLAB_HOME } else { 'C:\CannonLab' }),
    [string]$MinecraftVersion = '26.1.2'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if ($env:CANNONLAB_ACCEPT_EULA -ne 'TRUE') {
    throw 'Set CANNONLAB_ACCEPT_EULA=TRUE only after accepting the Minecraft EULA.'
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ServerRoot = Join-Path $LabHome 'server'
$PluginsRoot = Join-Path $ServerRoot 'plugins'
$PluginData = Join-Path $PluginsRoot 'CannonLab'
$CannonsTarget = Join-Path $PluginData 'cannons'
$ScenariosTarget = Join-Path $PluginData 'scenarios'
$ResultsTarget = Join-Path $PluginData 'results'

New-Item -ItemType Directory -Force -Path $ServerRoot, $PluginsRoot, $PluginData, $CannonsTarget, $ScenariosTarget, $ResultsTarget | Out-Null

$UserAgent = 'CannonLab/0.2 (https://github.com/redzicdenis08-afk/cannonlab)'
$Headers = @{ 'User-Agent' = $UserAgent }

# Prefer a manually supplied Sakura jar. Paper is only the infrastructure smoke-test fallback.
$SakuraJar = Join-Path $ServerRoot "sakura-$MinecraftVersion.jar"
$ServerJar = Join-Path $ServerRoot 'server.jar'
if (Test-Path $SakuraJar) {
    Copy-Item $SakuraJar $ServerJar -Force
    Write-Host "Using local Sakura jar: $SakuraJar"
} elseif (-not (Test-Path $ServerJar)) {
    Write-Host "No Sakura jar found. Downloading Paper $MinecraftVersion for infrastructure smoke testing."
    $BuildsUrl = "https://fill.papermc.io/v3/projects/paper/versions/$MinecraftVersion/builds"
    $Builds = Invoke-RestMethod -Uri $BuildsUrl -Headers $Headers
    $Build = $Builds | Where-Object { $_.channel -eq 'STABLE' } | Select-Object -First 1
    if (-not $Build) {
        $Build = $Builds | Select-Object -First 1
    }
    if (-not $Build) {
        throw "No Paper build found for $MinecraftVersion"
    }
    $DownloadUrl = $Build.downloads.'server:default'.url
    Invoke-WebRequest -Uri $DownloadUrl -Headers $Headers -OutFile $ServerJar
}

$WorldEditJar = Join-Path $PluginsRoot 'worldedit-bukkit-7.4.3.jar'
if (-not (Test-Path $WorldEditJar)) {
    $WorldEditUrl = 'https://github.com/EngineHub/WorldEdit/releases/download/7.4.3/worldedit-bukkit-7.4.3.jar'
    Write-Host 'Downloading WorldEdit 7.4.3...'
    Invoke-WebRequest -Uri $WorldEditUrl -Headers $Headers -OutFile $WorldEditJar
}

$PluginJar = Get-ChildItem (Join-Path $RepoRoot 'build\libs\CannonLab-*.jar') | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $PluginJar) {
    throw 'CannonLab plugin JAR was not built.'
}
Copy-Item $PluginJar.FullName (Join-Path $PluginsRoot 'CannonLab.jar') -Force

# Decode deterministic binary fixtures kept as text in the private repository.
Get-ChildItem (Join-Path $RepoRoot 'cannons\*.schem.b64') | ForEach-Object {
    $OutputName = $_.Name.Substring(0, $_.Name.Length - 4)
    $Bytes = [Convert]::FromBase64String((Get-Content $_.FullName -Raw).Trim())
    [IO.File]::WriteAllBytes((Join-Path $CannonsTarget $OutputName), $Bytes)
}

Copy-Item (Join-Path $RepoRoot 'scenarios\*.yml') $ScenariosTarget -Force

@'
eula=true
'@ | Set-Content (Join-Path $ServerRoot 'eula.txt') -Encoding ascii

@'
server-port=25570
online-mode=false
spawn-protection=0
max-players=1
difficulty=peaceful
view-distance=4
simulation-distance=4
network-compression-threshold=-1
enable-command-block=false
generate-structures=false
allow-flight=true
motd=CannonLab isolated test server
'@ | Set-Content (Join-Path $ServerRoot 'server.properties') -Encoding ascii

@'
arena:
  world: world
  origin:
    x: 0
    y: 100
    z: 0
  radius-x: 256
  radius-y: 96
  radius-z: 96
telemetry:
  output-directory: results
'@ | Set-Content (Join-Path $PluginData 'config.yml') -Encoding utf8

Write-Host "CannonLab server prepared at $ServerRoot"

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

$UserAgent = 'CannonLab/0.3 (https://github.com/redzicdenis08-afk/cannonlab)'
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

    $Download = $Build.downloads.'server:default'
    if (-not $Download -or -not $Download.url) {
        throw 'Paper build did not contain a server:default download.'
    }
    Invoke-WebRequest -Uri $Download.url -Headers $Headers -OutFile $ServerJar

    $ExpectedSha256 = $Download.checksums.sha256
    if ($ExpectedSha256) {
        $ActualSha256 = (Get-FileHash $ServerJar -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ActualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
            Remove-Item $ServerJar -Force
            throw 'Paper SHA-256 verification failed.'
        }
        Write-Host 'Paper SHA-256 verified.'
    }
}

# WorldEdit does not publish GitHub release assets. Resolve the exact official
# Bukkit 7.4.3 build from Modrinth version yDUBafTJ and verify its SHA-512.
$WorldEditVersionId = 'yDUBafTJ'
$WorldEditMetadata = Invoke-RestMethod -Uri "https://api.modrinth.com/v2/version/$WorldEditVersionId" -Headers $Headers
$WorldEditFile = $WorldEditMetadata.files | Where-Object { $_.primary -and $_.filename.EndsWith('.jar') } | Select-Object -First 1
if (-not $WorldEditFile) {
    $WorldEditFile = $WorldEditMetadata.files | Where-Object { $_.filename.EndsWith('.jar') } | Select-Object -First 1
}
if (-not $WorldEditFile) {
    throw 'Official WorldEdit 7.4.3 metadata contained no Bukkit JAR.'
}

$WorldEditJar = Join-Path $PluginsRoot $WorldEditFile.filename
$NeedsWorldEditDownload = -not (Test-Path $WorldEditJar)
if (-not $NeedsWorldEditDownload -and $WorldEditFile.hashes.sha512) {
    $ExistingHash = (Get-FileHash $WorldEditJar -Algorithm SHA512).Hash.ToLowerInvariant()
    $NeedsWorldEditDownload = $ExistingHash -ne $WorldEditFile.hashes.sha512.ToLowerInvariant()
}
if ($NeedsWorldEditDownload) {
    Write-Host 'Downloading official WorldEdit 7.4.3 Bukkit build from Modrinth...'
    Invoke-WebRequest -Uri $WorldEditFile.url -Headers $Headers -OutFile $WorldEditJar
}
if ($WorldEditFile.hashes.sha512) {
    $ActualWorldEditHash = (Get-FileHash $WorldEditJar -Algorithm SHA512).Hash.ToLowerInvariant()
    if ($ActualWorldEditHash -ne $WorldEditFile.hashes.sha512.ToLowerInvariant()) {
        Remove-Item $WorldEditJar -Force
        throw 'WorldEdit SHA-512 verification failed.'
    }
    Write-Host 'WorldEdit SHA-512 verified.'
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
pause-when-empty-seconds=-1
max-tick-time=-1
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

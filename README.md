# CannonLab

Automated Minecraft cannon test laboratory targeting ExtremeCraft-like Sakura mechanics.

## Current milestone

Stage 1 builds and validates a headless Paper/Sakura plugin that can:

- define a chunk-aligned test arena
- clear and rebuild the arena
- build repeatable wall targets
- fill dispensers with TNT
- toggle a configured cannon input
- record TNT and falling-block telemetry every tick
- write machine-readable shot results

The local physics model must still be calibrated against live ExtremeCraft measurements. Matching the server name and plugin family alone does not prove identical mechanics.

## Safety boundary

This repository is for an isolated private test server. It does not contain credentials, Minecraft session tokens, or code that connects to or automates actions on ExtremeCraft.

## Build

Requirements:

- JDK 25
- Gradle 9.5.1 or newer

```powershell
gradle clean build
```

The plugin JAR is written to `build/libs/`.

## Commands

```text
/cannonlab status
/cannonlab reset
/cannonlab wall dry
/cannonlab wall watered
/cannonlab fill
/cannonlab record start
/cannonlab fire
/cannonlab record stop
/cannonlab smoke
```

## Automation plan

1. GitHub-hosted CI compiles and statically checks the plugin.
2. A Windows self-hosted runner starts the local test server.
3. CannonLab performs reset, build, fill, fire, telemetry and export.
4. Results are uploaded as GitHub Actions artifacts.
5. ExtremeCraft fingerprint tests are used to tune the local Sakura configuration.

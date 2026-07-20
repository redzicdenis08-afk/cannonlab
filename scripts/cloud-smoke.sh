#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/.cloud-lab"
SERVER="$WORK/server"
PLUGINS="$SERVER/plugins"
DATA="$PLUGINS/CannonLab"
ARTIFACTS="$ROOT/lab-artifacts"
VERSION="${CANNONLAB_MC_VERSION:-26.1.2}"
SCENARIO="${CANNONLAB_SCENARIO:-probe-cloud-stress.yml}"
SERVER_JAR_OVERRIDE="${CANNONLAB_SERVER_JAR:-}"
SERVER_LABEL="${CANNONLAB_SERVER_LABEL:-Paper $VERSION}"
USER_AGENT="CannonLab/0.3 (https://github.com/redzicdenis08-afk/cannonlab)"
WORLDEDIT_VERSION_ID="yDUBafTJ"

rm -rf "$WORK" "$ARTIFACTS"
mkdir -p "$PLUGINS" "$DATA/cannons" "$DATA/scenarios" "$DATA/results" "$ARTIFACTS"
exec > >(tee -a "$ARTIFACTS/cloud-smoke.log") 2>&1
trap 'code=$?; echo "cloud-smoke.sh failed at line $LINENO with exit code $code"; exit $code' ERR

if [[ -n "$SERVER_JAR_OVERRIDE" ]]; then
  if [[ ! -f "$SERVER_JAR_OVERRIDE" ]]; then
    echo "CANNONLAB_SERVER_JAR does not exist: $SERVER_JAR_OVERRIDE" >&2
    exit 1
  fi
  cp "$SERVER_JAR_OVERRIDE" "$SERVER/server.jar"
  echo "Using supplied server JAR: $SERVER_LABEL"
  sha256sum "$SERVER/server.jar" | tee "$ARTIFACTS/server-jar.sha256"
else
  printf 'Resolving Paper %s...\n' "$VERSION"
  BUILDS_JSON="$WORK/paper-builds.json"
  curl --fail --location --silent --show-error --retry 3 \
    --header "User-Agent: $USER_AGENT" \
    "https://fill.papermc.io/v3/projects/paper/versions/$VERSION/builds" \
    --output "$BUILDS_JSON"

  mapfile -t PAPER_INFO < <(python3 - "$BUILDS_JSON" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if isinstance(payload, dict):
    builds = payload.get("builds", [])
elif isinstance(payload, list):
    builds = payload
else:
    builds = []

if not builds:
    raise SystemExit("Paper Fill API returned no builds")

stable = [build for build in builds if str(build.get("channel", "")).upper() == "STABLE"]
selected = stable[0] if stable else builds[0]
download = selected.get("downloads", {}).get("server:default")
if not isinstance(download, dict) or not download.get("url"):
    raise SystemExit(f"Paper build has no server:default download: {selected}")

print(download["url"])
print(download.get("checksums", {}).get("sha256", ""))
PY
  )
  PAPER_URL="${PAPER_INFO[0]}"
  PAPER_SHA256="${PAPER_INFO[1]:-}"

  curl --fail --location --silent --show-error --retry 3 \
    --header "User-Agent: $USER_AGENT" \
    "$PAPER_URL" \
    --output "$SERVER/server.jar"
  if [[ -n "$PAPER_SHA256" ]]; then
    printf '%s  %s\n' "$PAPER_SHA256" "$SERVER/server.jar" | sha256sum --check --status
    echo 'Paper SHA-256 verified.'
  fi
fi

printf 'Resolving official WorldEdit 7.4.3 Bukkit build from Modrinth...\n'
WORLDEDIT_JSON="$WORK/worldedit-version.json"
curl --fail --location --silent --show-error --retry 3 \
  --header "User-Agent: $USER_AGENT" \
  "https://api.modrinth.com/v2/version/$WORLDEDIT_VERSION_ID" \
  --output "$WORLDEDIT_JSON"

mapfile -t WORLDEDIT_INFO < <(python3 - "$WORLDEDIT_JSON" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

version = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
files = version.get("files", [])
if not files:
    raise SystemExit("Modrinth returned no WorldEdit files")

jars = [entry for entry in files if str(entry.get("filename", "")).endswith(".jar")]
if not jars:
    raise SystemExit(f"WorldEdit version has no JAR file: {files}")
selected = next((entry for entry in jars if entry.get("primary")), jars[0])
print(selected["url"])
print(selected.get("hashes", {}).get("sha512", ""))
print(selected.get("filename", "worldedit-bukkit-7.4.3.jar"))
PY
)
WORLDEDIT_URL="${WORLDEDIT_INFO[0]}"
WORLDEDIT_SHA512="${WORLDEDIT_INFO[1]:-}"
WORLDEDIT_FILENAME="${WORLDEDIT_INFO[2]:-worldedit-bukkit-7.4.3.jar}"
WORLDEDIT_JAR="$PLUGINS/$WORLDEDIT_FILENAME"

curl --fail --location --silent --show-error --retry 3 \
  --header "User-Agent: $USER_AGENT" \
  "$WORLDEDIT_URL" \
  --output "$WORLDEDIT_JAR"
if [[ -n "$WORLDEDIT_SHA512" ]]; then
  printf '%s  %s\n' "$WORLDEDIT_SHA512" "$WORLDEDIT_JAR" | sha512sum --check --status
  echo 'WorldEdit SHA-512 verified.'
fi

PLUGIN_JAR="$(find "$ROOT/build/libs" -maxdepth 1 -type f -name 'CannonLab-*.jar' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
if [[ -z "$PLUGIN_JAR" || ! -f "$PLUGIN_JAR" ]]; then
  echo 'CannonLab plugin JAR was not built.' >&2
  exit 1
fi
cp "$PLUGIN_JAR" "$PLUGINS/CannonLab.jar"

for fixture in "$ROOT"/cannons/*.schem.b64; do
  output="$DATA/cannons/$(basename "${fixture%.b64}")"
  base64 --decode "$fixture" > "$output"
done
cp "$ROOT"/scenarios/*.yml "$DATA/scenarios/"

cat > "$SERVER/eula.txt" <<'EOF'
eula=true
EOF

cat > "$SERVER/server.properties" <<'EOF'
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
level-name=world
motd=CannonLab cloud runtime smoke test
EOF

cat > "$DATA/config.yml" <<'EOF'
arena:
  world: world
  origin:
    x: 0
    y: 100
    z: 0
  radius-x: 32
  radius-y: 16
  radius-z: 16
telemetry:
  output-directory: results
EOF

STDOUT="$ARTIFACTS/server-stdout.log"
STDERR="$ARTIFACTS/server-stderr.log"

printf 'Starting headless %s runtime for scenario %s...\n' "$SERVER_LABEL" "$SCENARIO"
set +e
(
  cd "$SERVER"
  timeout --signal=TERM --kill-after=30s 600s \
    java -Xms1G -Xmx3G \
    "-Dcannonlab.scenario=$SCENARIO" \
    -jar server.jar --nogui
) >"$STDOUT" 2>"$STDERR"
SERVER_EXIT=$?
set -e

if [[ -d "$DATA/results" ]]; then
  cp -R "$DATA/results" "$ARTIFACTS/results"
fi
if [[ -d "$SERVER/logs" ]]; then
  cp -R "$SERVER/logs" "$ARTIFACTS/server-logs"
fi

if [[ "$SERVER_EXIT" -ne 0 ]]; then
  echo "Server exited with code $SERVER_EXIT" >&2
  tail -n 200 "$STDOUT" || true
  tail -n 200 "$STDERR" || true
  exit "$SERVER_EXIT"
fi

python3 "$ROOT/scripts/assert-results.py" \
  "$ARTIFACTS/results" \
  --expected-shots 10 \
  | tee "$ARTIFACTS/assertion.json"

printf 'CannonLab cloud runtime smoke test passed.\n'

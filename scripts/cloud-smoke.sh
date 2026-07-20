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
USER_AGENT="CannonLab/0.3 (https://github.com/redzicdenis08-afk/cannonlab)"

rm -rf "$WORK" "$ARTIFACTS"
mkdir -p "$PLUGINS" "$DATA/cannons" "$DATA/scenarios" "$DATA/results" "$ARTIFACTS"

printf 'Resolving Paper %s...\n' "$VERSION"
BUILDS_JSON="$WORK/paper-builds.json"
curl --fail --location --silent --show-error --retry 3 \
  --header "User-Agent: $USER_AGENT" \
  "https://fill.papermc.io/v3/projects/paper/versions/$VERSION/builds" \
  --output "$BUILDS_JSON"

PAPER_URL="$(python3 - "$BUILDS_JSON" <<'PY'
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
try:
    print(selected["downloads"]["server:default"]["url"])
except KeyError as exc:
    raise SystemExit(f"Paper build has no server:default download: {selected}") from exc
PY
)"

curl --fail --location --silent --show-error --retry 3 \
  --header "User-Agent: $USER_AGENT" \
  "$PAPER_URL" \
  --output "$SERVER/server.jar"

printf 'Downloading WorldEdit 7.4.3...\n'
curl --fail --location --silent --show-error --retry 3 \
  --header "User-Agent: $USER_AGENT" \
  "https://github.com/EngineHub/WorldEdit/releases/download/7.4.3/worldedit-bukkit-7.4.3.jar" \
  --output "$PLUGINS/worldedit-bukkit-7.4.3.jar"

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

printf 'Starting headless Paper runtime for scenario %s...\n' "$SCENARIO"
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

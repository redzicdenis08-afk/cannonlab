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
TIMEOUT_SECONDS="${CANNONLAB_TIMEOUT_SECONDS:-600}"
EXPECTED_SHOTS="${CANNONLAB_EXPECTED_SHOTS:-10}"
STRICT_SINGLE_TNT="${CANNONLAB_STRICT_SINGLE_TNT:-true}"
MIN_TNT_PER_SHOT="${CANNONLAB_MIN_TNT_PER_SHOT:-1}"
MIN_EXPLOSIONS_PER_SHOT="${CANNONLAB_MIN_EXPLOSIONS_PER_SHOT:-1}"
EXPECTED_LIFETIME="${CANNONLAB_EXPECTED_LIFETIME:-79}"
LIFETIME_TOLERANCE="${CANNONLAB_LIFETIME_TOLERANCE:-0}"
MIN_FORWARD_TRAVEL="${CANNONLAB_MIN_FORWARD_TRAVEL:-}"
MAX_TARGET_MISS_DISTANCE="${CANNONLAB_MAX_TARGET_MISS_DISTANCE:-}"
MIN_TARGET_PEAK_DESTROYED="${CANNONLAB_MIN_TARGET_PEAK_DESTROYED:-}"
MIN_TARGET_PEAK_MEAN="${CANNONLAB_MIN_TARGET_PEAK_MEAN:-}"
MIN_LAYER_BREACHED="${CANNONLAB_MIN_LAYER_BREACHED:-}"
MAX_SELF_DAMAGE_BLOCKS="${CANNONLAB_MAX_SELF_DAMAGE_BLOCKS:-}"
REQUIRE_REGEN="${CANNONLAB_REQUIRE_REGEN:-false}"
MIN_REGEN_RESTORED="${CANNONLAB_MIN_REGEN_RESTORED:-1}"
ARENA_RADIUS_X="${CANNONLAB_ARENA_RADIUS_X:-32}"
ARENA_RADIUS_Y="${CANNONLAB_ARENA_RADIUS_Y:-16}"
ARENA_RADIUS_Z="${CANNONLAB_ARENA_RADIUS_Z:-16}"
USER_AGENT="CannonLab/0.5 (https://github.com/redzicdenis08-afk/cannonlab)"
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
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
builds = payload.get("builds", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
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
    --header "User-Agent: $USER_AGENT" "$PAPER_URL" --output "$SERVER/server.jar"
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
import json, sys
from pathlib import Path
version = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
files = version.get("files", [])
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
  --header "User-Agent: $USER_AGENT" "$WORLDEDIT_URL" --output "$WORLDEDIT_JAR"
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
cat > "$DATA/config.yml" <<EOF
arena:
  world: world
  origin:
    x: 0
    y: 100
    z: 0
  radius-x: $ARENA_RADIUS_X
  radius-y: $ARENA_RADIUS_Y
  radius-z: $ARENA_RADIUS_Z
telemetry:
  output-directory: results
EOF

STDOUT="$ARTIFACTS/server-stdout.log"
STDERR="$ARTIFACTS/server-stderr.log"
printf 'Starting headless %s runtime for scenario %s with timeout %ss...\n' "$SERVER_LABEL" "$SCENARIO" "$TIMEOUT_SECONDS"
printf 'Assertions: shots=%s strictSingleTnt=%s minTnt=%s minExplosions=%s lifetime=%s±%s arena=%sx%sx%s\n' \
  "$EXPECTED_SHOTS" "$STRICT_SINGLE_TNT" "$MIN_TNT_PER_SHOT" "$MIN_EXPLOSIONS_PER_SHOT" \
  "$EXPECTED_LIFETIME" "$LIFETIME_TOLERANCE" "$ARENA_RADIUS_X" "$ARENA_RADIUS_Y" "$ARENA_RADIUS_Z"
set +e
(
  cd "$SERVER"
  timeout --signal=TERM --kill-after=30s "${TIMEOUT_SECONDS}s" \
    java -Xms1G -Xmx3G "-Dcannonlab.scenario=$SCENARIO" -jar server.jar --nogui
) >"$STDOUT" 2>"$STDERR"
SERVER_EXIT=$?
set -e

if [[ -d "$DATA/results" ]]; then cp -R "$DATA/results" "$ARTIFACTS/results"; fi
if [[ -d "$SERVER/logs" ]]; then cp -R "$SERVER/logs" "$ARTIFACTS/server-logs"; fi
if [[ "$SERVER_EXIT" -ne 0 ]]; then
  echo "Server exited with code $SERVER_EXIT" >&2
  tail -n 200 "$STDOUT" || true
  tail -n 200 "$STDERR" || true
  exit "$SERVER_EXIT"
fi

ASSERT_ARGS=(
  "$ARTIFACTS/results"
  --expected-shots "$EXPECTED_SHOTS"
  --min-tnt-per-shot "$MIN_TNT_PER_SHOT"
  --min-explosions-per-shot "$MIN_EXPLOSIONS_PER_SHOT"
  --json-out "$ARTIFACTS/physics-fingerprint.json"
)
case "${STRICT_SINGLE_TNT,,}" in
  1|true|yes) ASSERT_ARGS+=(--strict-single-tnt) ;;
  0|false|no) ;;
  *) echo "Invalid CANNONLAB_STRICT_SINGLE_TNT=$STRICT_SINGLE_TNT" >&2; exit 1 ;;
esac
if [[ -n "$EXPECTED_LIFETIME" && "${EXPECTED_LIFETIME,,}" != "none" ]]; then
  ASSERT_ARGS+=(--expected-lifetime "$EXPECTED_LIFETIME" --lifetime-tolerance "$LIFETIME_TOLERANCE")
fi
if [[ -n "$MIN_FORWARD_TRAVEL" ]]; then
  ASSERT_ARGS+=(--min-forward-travel "$MIN_FORWARD_TRAVEL")
fi
if [[ -n "$MAX_TARGET_MISS_DISTANCE" ]]; then
  ASSERT_ARGS+=(--max-target-miss-distance "$MAX_TARGET_MISS_DISTANCE")
fi
if [[ -n "$MIN_TARGET_PEAK_DESTROYED" ]]; then
  ASSERT_ARGS+=(--min-target-peak-destroyed "$MIN_TARGET_PEAK_DESTROYED")
fi
if [[ -n "$MIN_TARGET_PEAK_MEAN" ]]; then
  ASSERT_ARGS+=(--min-target-peak-mean "$MIN_TARGET_PEAK_MEAN")
fi
if [[ -n "$MIN_LAYER_BREACHED" ]]; then
  ASSERT_ARGS+=(--min-layer-breached "$MIN_LAYER_BREACHED")
fi
if [[ -n "$MAX_SELF_DAMAGE_BLOCKS" ]]; then
  ASSERT_ARGS+=(--max-self-damage-blocks "$MAX_SELF_DAMAGE_BLOCKS")
fi
case "${REQUIRE_REGEN,,}" in
  1|true|yes) ASSERT_ARGS+=(--require-regen --min-regen-restored "$MIN_REGEN_RESTORED") ;;
  0|false|no) ;;
  *) echo "Invalid CANNONLAB_REQUIRE_REGEN=$REQUIRE_REGEN" >&2; exit 1 ;;
esac

python3 "$ROOT/scripts/assert-results.py" "${ASSERT_ARGS[@]}" \
  | tee "$ARTIFACTS/assertion.json"

printf 'CannonLab runtime and physics fingerprint passed.\n'

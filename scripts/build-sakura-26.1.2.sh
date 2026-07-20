#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/.sakura-source"
OUTPUT="$ROOT/.sakura-26.1.2.jar"
LOG_ROOT="$ROOT/sakura-build-artifacts"
EXPECTED_VERSION='26.1.2'
EXPECTED_COMMIT='63f35d74e0fbe6bcd76c58494c01c1632c83010d'

rm -rf "$SOURCE" "$OUTPUT" "$LOG_ROOT"
mkdir -p "$LOG_ROOT"
exec > >(tee "$LOG_ROOT/build-sakura.log") 2>&1
trap 'code=$?; echo "Sakura build failed at line $LINENO with exit code $code"; exit $code' ERR

# Paperweight creates nested temporary Git repositories while applying patches.
# GitHub-hosted runners are disposable, so set a CI-only global identity that
# every nested repository inherits.
export GIT_AUTHOR_NAME='CannonLab Builder'
export GIT_AUTHOR_EMAIL='cannonlab@users.noreply.github.com'
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
git config --global user.name "$GIT_AUTHOR_NAME"
git config --global user.email "$GIT_AUTHOR_EMAIL"

printf 'Fetching pinned public Sakura 26.1.2 commit %s...\n' "$EXPECTED_COMMIT"
git init "$SOURCE"
git -C "$SOURCE" remote add origin https://github.com/Samsuik/Sakura.git
git -C "$SOURCE" fetch --depth 1 origin "$EXPECTED_COMMIT"
git -C "$SOURCE" checkout --detach FETCH_HEAD

ACTUAL_COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
ACTUAL_VERSION="$(sed -n 's/^version=//p' "$SOURCE/gradle.properties" | head -n1)"
MC_VERSION="$(sed -n 's/^mcVersion=//p' "$SOURCE/gradle.properties" | head -n1)"
PAPER_REF="$(sed -n 's/^paperRef=//p' "$SOURCE/gradle.properties" | head -n1)"

if [[ "$ACTUAL_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  echo "Unexpected Sakura source commit: $ACTUAL_COMMIT" >&2
  exit 1
fi
if [[ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" || "$MC_VERSION" != "$EXPECTED_VERSION" ]]; then
  echo "Unexpected Sakura metadata: version=$ACTUAL_VERSION mcVersion=$MC_VERSION" >&2
  exit 1
fi

{
  echo "sakura_version=$ACTUAL_VERSION"
  echo "minecraft_version=$MC_VERSION"
  echo "paper_ref=$PAPER_REF"
  echo "git_commit=$ACTUAL_COMMIT"
} | tee "$LOG_ROOT/source-fingerprint.txt"

cd "$SOURCE"
chmod +x gradlew
./gradlew --no-daemon --stacktrace applyAllPatches

# Paperweight 2.x renamed the old README task createMojmapPaperclipJar.
# The runnable Mojang-mapped paperclip artifact is produced by this task.
./gradlew --no-daemon --stacktrace :sakura-server:createPaperclipJar

mapfile -t CANDIDATES < <(
  find "$SOURCE/sakura-server/build/libs" -maxdepth 1 -type f -name '*.jar' \
    ! -name '*sources*' ! -name '*javadoc*' \
    -printf '%s %p\n' | sort -nr
)
if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo 'Sakura build produced no runnable JAR candidate.' >&2
  exit 1
fi

SELECTED="${CANDIDATES[0]#* }"
SIZE="${CANDIDATES[0]%% *}"
if (( SIZE < 10000000 )); then
  printf 'Largest Sakura JAR is suspiciously small: %s bytes at %s\n' "$SIZE" "$SELECTED" >&2
  exit 1
fi

cp "$SELECTED" "$OUTPUT"
jar tf "$OUTPUT" | grep -q '^META-INF/MANIFEST.MF$'
sha256sum "$OUTPUT" | tee "$LOG_ROOT/sakura-jar.sha256"
printf 'Built Sakura runtime: %s (%s bytes)\n' "$OUTPUT" "$SIZE"

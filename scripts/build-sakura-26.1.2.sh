#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/.sakura-source"
OUTPUT="$ROOT/.sakura-26.1.2.jar"
LOG_ROOT="$ROOT/sakura-build-artifacts"

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

printf 'Cloning exact public Sakura ver/26.1.x branch...\n'
git clone --depth 1 --branch ver/26.1.x \
  https://github.com/Samsuik/Sakura.git \
  "$SOURCE"

EXPECTED_VERSION='26.1.2'
ACTUAL_VERSION="$(sed -n 's/^version=//p' "$SOURCE/gradle.properties" | head -n1)"
MC_VERSION="$(sed -n 's/^mcVersion=//p' "$SOURCE/gradle.properties" | head -n1)"
PAPER_REF="$(sed -n 's/^paperRef=//p' "$SOURCE/gradle.properties" | head -n1)"

if [[ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" || "$MC_VERSION" != "$EXPECTED_VERSION" ]]; then
  echo "Unexpected Sakura branch metadata: version=$ACTUAL_VERSION mcVersion=$MC_VERSION" >&2
  exit 1
fi

{
  echo "sakura_version=$ACTUAL_VERSION"
  echo "minecraft_version=$MC_VERSION"
  echo "paper_ref=$PAPER_REF"
  echo "git_commit=$(git -C "$SOURCE" rev-parse HEAD)"
} | tee "$LOG_ROOT/source-fingerprint.txt"

cd "$SOURCE"
chmod +x gradlew
./gradlew --no-daemon --stacktrace applyAllPatches
./gradlew --no-daemon --stacktrace createMojmapPaperclipJar

mapfile -t CANDIDATES < <(
  find "$SOURCE" -type f -path '*/build/libs/*.jar' \
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

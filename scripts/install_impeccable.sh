#!/usr/bin/env bash
# Install the pinned Impeccable design skill and its engine for the App
# Builder's build user, on the build host. Run as root on the host:
#
#   bash scripts/install_impeccable.sh
#
# What a marked build uses (mcp-servers/tasks/design_skill.py):
#   ~claude-agent/.impeccable/skills/impeccable     the skill, linked into a
#                                                   marked run's own folder
#   ~claude-agent/.impeccable/bin/<engine>/impeccable  the engine, in the
#                                                   launcher's version-pinned
#                                                   cache, so no build ever
#                                                   downloads anything
#
# Pinned, not "latest": upstream syncs generated output several times a day,
# and what a build is told to follow should change only when someone moves
# these two lines. The engine is checked against the sha256 upstream publishes
# beside it before it is installed; a mismatch installs nothing.
#
# Upstream's hooks and plugin are deliberately NOT installed: the Stop hook
# runs a design deep pass at the end of every session, which on a build means
# more spend and more of the 600 second limit on every run.
set -euo pipefail

COMMIT=c74755d920985f7a92cef691ca970ba95f90126e   # v4.4.0, 2026-10-01
ENGINE=0.1.9
BUILD_USER=${AGENT_USER:-claude-agent}

HOME_DIR=$(getent passwd "$BUILD_USER" | cut -d: -f6)
[ -n "$HOME_DIR" ] || { echo "no such user: $BUILD_USER" >&2; exit 1; }
DEST=$HOME_DIR/.impeccable

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "fetching impeccable $COMMIT"
curl -fsSL --retry 2 -o "$TMP/src.tgz" \
  "https://codeload.github.com/pbakaus/impeccable/tar.gz/$COMMIT"
tar --no-same-owner -xzf "$TMP/src.tgz" -C "$TMP"
SRC_ROOT="$TMP/impeccable-$COMMIT"
SKILL_SRC="$SRC_ROOT/.claude/skills/impeccable"
[ -f "$SKILL_SRC/SKILL.md" ] || { echo "no SKILL.md in $SKILL_SRC" >&2; exit 1; }
WANT=$(tr -d '[:space:]' < "$SKILL_SRC/scripts/VERSION")
[ "$WANT" = "$ENGINE" ] || {
  echo "skill wants engine $WANT, this script pins $ENGINE" >&2; exit 1; }

# The production host is aarch64 (Hetzner ARM), which the first run of this
# script got wrong: an x64 engine verified its checksum and then failed with
# "Exec format error". Chosen the way upstream's own launcher chooses.
case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  x86_64|amd64) ARCH=x64 ;;
  *) echo "no impeccable engine for $(uname -m)" >&2; exit 1 ;;
esac
echo "fetching engine $ENGINE for linux-$ARCH"
URL="https://github.com/pbakaus/impeccable/releases/download/engine-v$ENGINE/impeccable-linux-$ARCH"
curl -fsSL --retry 2 -o "$TMP/impeccable" "$URL"
curl -fsSL --retry 2 -o "$TMP/impeccable.sha256" "$URL.sha256"
EXPECTED=$(cut -d' ' -f1 < "$TMP/impeccable.sha256")
ACTUAL=$(sha256sum "$TMP/impeccable" | cut -d' ' -f1)
[ -n "$EXPECTED" ] && [ "$EXPECTED" = "$ACTUAL" ] || {
  echo "engine checksum mismatch: expected $EXPECTED got $ACTUAL" >&2; exit 1; }
echo "engine sha256 $ACTUAL verified"

mkdir -p "$DEST/skills" "$DEST/bin/$ENGINE"
rm -rf "$DEST/skills/impeccable.new"
cp -a "$SKILL_SRC" "$DEST/skills/impeccable.new"
# Apache 2.0 travels with the copy.
cp "$SRC_ROOT/LICENSE" "$SRC_ROOT/NOTICE.md" "$DEST/skills/impeccable.new/"
echo "$COMMIT" > "$DEST/skills/impeccable.new/UPSTREAM_COMMIT"
install -m 0755 "$TMP/impeccable" "$DEST/bin/$ENGINE/impeccable"

# Swap in one rename, so a build starting now sees the old skill or the new
# one and never half of each.
if [ -d "$DEST/skills/impeccable" ]; then
  rm -rf "$DEST/skills/impeccable.old"
  mv "$DEST/skills/impeccable" "$DEST/skills/impeccable.old"
fi
mv "$DEST/skills/impeccable.new" "$DEST/skills/impeccable"
rm -rf "$DEST/skills/impeccable.old"
chown -R "$BUILD_USER:$BUILD_USER" "$DEST"

echo "probing as $BUILD_USER"
su -s /bin/sh "$BUILD_USER" -c \
  "$DEST/skills/impeccable/scripts/impeccable engine-probe"

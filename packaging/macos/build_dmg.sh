#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

APP_PATH="${1:-dist/OpenPlot.app}"
DMG_PATH="${2:-dist/OpenPlot-arm64.dmg}"
VOLUME_NAME="${3:-OpenPlot}"
QUICK_REFERENCE_PATH="packaging/macos/dmg-quick-reference.txt"

if [[ ! -d "$APP_PATH" ]]; then
  echo "error: app bundle not found at $APP_PATH" >&2
  exit 1
fi

if [[ ! -f "$QUICK_REFERENCE_PATH" ]]; then
  echo "error: quick reference not found at $QUICK_REFERENCE_PATH" >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/openplot-dmg.XXXXXX")"
cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

cp -R "$APP_PATH" "$STAGING_DIR/"
cp "$QUICK_REFERENCE_PATH" "$STAGING_DIR/Install OpenPlot.txt"
ln -s /Applications "$STAGING_DIR/Applications"

rm -f "$DMG_PATH"
hdiutil create \
  -volname "$VOLUME_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "Built $DMG_PATH"

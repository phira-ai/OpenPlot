#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
ICON_PATH="${ICON_PATH:-$ROOT_DIR/packaging/macos/openplot.icns}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: macOS build script must run on Darwin" >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "warning: expected arm64 host, found $(uname -m)" >&2
fi

if [[ ! -f "$ICON_PATH" ]]; then
  echo "error: app icon not found at $ICON_PATH" >&2
  exit 1
fi

echo "[1/3] Syncing Python dependencies"
uv sync --group dev --group packaging --extra desktop

echo "[2/3] Building frontend assets"
npm ci --prefix frontend
npm run build --prefix frontend

echo "[3/3] Building OpenPlot.app"
export OPENPLOT_MACOS_ICON="$ICON_PATH"
uv run pyinstaller \
  --noconfirm \
  --clean \
  packaging/pyinstaller/OpenPlot.spec

echo "Built dist/OpenPlot.app"

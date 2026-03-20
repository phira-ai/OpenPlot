#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "error: Linux build script must run on Linux" >&2
  exit 1
fi

echo "[1/3] Syncing Python dependencies"
uv sync --group dev --group packaging --extra desktop

echo "[2/3] Building frontend assets"
npm ci --prefix frontend
npm run build --prefix frontend

echo "[3/4] Building OpenPlot bundle"
uv run pyinstaller \
  --noconfirm \
  --clean \
  packaging/pyinstaller/OpenPlot.spec

echo "[4/4] Building AppImage"
bash packaging/linux/build_appimage.sh

echo "Built dist/OpenPlot/ and an AppImage under dist/"

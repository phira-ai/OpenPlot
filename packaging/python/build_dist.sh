#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR"

echo "[1/4] Installing frontend dependencies"
npm ci --prefix frontend

echo "[2/4] Building frontend assets"
npm run build --prefix frontend

echo "[3/4] Verifying packaged frontend assets"
python packaging/python/verify_python_dist.py \
  --source-static-dir src/openplot/static

echo "[4/4] Building Python distributions"
uv build

echo "Done. Built Python distributions in dist/."

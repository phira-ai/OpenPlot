#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

ensure_host_tool() {
  local tool_name="$1"

  if command -v "$tool_name" >/dev/null 2>&1; then
    return 0
  fi

  echo "error: the '$tool_name' command is required to run appimagetool" >&2
  if command -v nix >/dev/null 2>&1; then
    echo "hint: run 'nix shell nixpkgs#file -c bash packaging/linux/build_appimage.sh'" >&2
  fi
  exit 1
}

ensure_python() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi

  echo "error: python3 (or python) is required to bundle runtime libraries" >&2
  exit 1
}

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "error: AppImage build script must run on Linux" >&2
  exit 1
fi

DIST_DIR="$ROOT_DIR/dist"
BUNDLE_DIR="$DIST_DIR/OpenPlot"
APPDIR="$DIST_DIR/AppDir"
APPIMAGE_ARCH="${APPIMAGE_ARCH:-}"

if [[ -z "$APPIMAGE_ARCH" ]]; then
  case "$(uname -m)" in
    x86_64|amd64) APPIMAGE_ARCH="x86_64" ;;
    aarch64|arm64) APPIMAGE_ARCH="aarch64" ;;
    *)
      echo "error: unsupported architecture $(uname -m) for AppImage packaging" >&2
      exit 1
      ;;
  esac
fi

OUTPUT_PATH="${APPIMAGE_OUTPUT:-$DIST_DIR/OpenPlot-linux-${APPIMAGE_ARCH}.AppImage}"
ICON_PATH="${ICON_PATH:-$ROOT_DIR/packaging/macos/openplot.iconset/icon_512x512.png}"
XKB_CONFIG_ROOT_SOURCE="${OPENPLOT_XKB_CONFIG_ROOT:-}"
APPIMAGETOOL_PATH="${APPIMAGETOOL:-}"
PYTHON_CMD="$(ensure_python)"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "error: PyInstaller bundle not found at $BUNDLE_DIR" >&2
  echo "Run packaging/linux/build_app.sh first." >&2
  exit 1
fi

if [[ ! -f "$ICON_PATH" ]]; then
  echo "error: icon not found at $ICON_PATH" >&2
  exit 1
fi

if [[ -z "$XKB_CONFIG_ROOT_SOURCE" ]]; then
  for candidate in "/usr/share/X11/xkb" "/usr/local/share/X11/xkb"; do
    if [[ -d "$candidate" ]]; then
      XKB_CONFIG_ROOT_SOURCE="$candidate"
      break
    fi
  done
fi

if [[ -z "$XKB_CONFIG_ROOT_SOURCE" || ! -d "$XKB_CONFIG_ROOT_SOURCE" ]]; then
  echo "error: XKB data directory not found. Set OPENPLOT_XKB_CONFIG_ROOT to a valid X11 xkb path." >&2
  exit 1
fi

download_appimagetool() {
  local cache_dir tool_path tool_url
  cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/openplot"
  mkdir -p "$cache_dir"
  tool_path="$cache_dir/appimagetool-${APPIMAGE_ARCH}.AppImage"
  tool_url="${APPIMAGETOOL_URL:-https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage}"

  if [[ ! -x "$tool_path" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
      echo "error: curl is required to download appimagetool" >&2
      exit 1
    fi
    echo "Downloading appimagetool to $tool_path"
    curl -L "$tool_url" -o "$tool_path"
    chmod +x "$tool_path"
  fi

  APPIMAGETOOL_PATH="$tool_path"
}

if [[ -z "$APPIMAGETOOL_PATH" ]]; then
  if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL_PATH="$(command -v appimagetool)"
  else
    download_appimagetool
  fi
fi

ensure_host_tool file

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/X11"

cp -r "$BUNDLE_DIR" "$APPDIR/usr/lib/openplot"
cp -a "$XKB_CONFIG_ROOT_SOURCE" "$APPDIR/usr/share/X11/xkb"

"$PYTHON_CMD" "$ROOT_DIR/packaging/linux/bundle_runtime_libs.py" \
  --bundle-dir "$APPDIR/usr/lib/openplot" \
  --dest-lib-dir "$APPDIR/usr/lib"

"$PYTHON_CMD" "$ROOT_DIR/packaging/linux/bundle_runtime_libs.py" \
  --bundle-dir "$APPDIR/usr/lib/openplot" \
  --dest-lib-dir "$APPDIR/usr/lib" \
  --verify-only

cp "$ICON_PATH" "$APPDIR/openplot.png"
cp "$ROOT_DIR/packaging/linux/openplot.desktop" "$APPDIR/openplot.desktop"
ln -s openplot.png "$APPDIR/.DirIcon"

cat > "$APPDIR/usr/bin/openplot-desktop" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENPLOT_BUNDLE="$HERE/../lib/openplot"
export LD_LIBRARY_PATH="$HERE/../lib:$OPENPLOT_BUNDLE/_internal:$OPENPLOT_BUNDLE/_internal/PyQt6/Qt6/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XKB_CONFIG_ROOT="${XKB_CONFIG_ROOT:-$HERE/../share/X11/xkb}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_OPENGL="${QT_OPENGL:-software}"
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
export QTWEBENGINE_DISABLE_SANDBOX="${QTWEBENGINE_DISABLE_SANDBOX:-1}"
export QT_PLUGIN_PATH="$OPENPLOT_BUNDLE/_internal/PyQt6/Qt6/plugins"
export QML2_IMPORT_PATH="$OPENPLOT_BUNDLE/_internal/PyQt6/Qt6/qml"
export QTWEBENGINEPROCESS_PATH="$OPENPLOT_BUNDLE/_internal/PyQt6/Qt6/libexec/QtWebEngineProcess"
OPENPLOT_DEFAULT_CHROMIUM_FLAGS="--disable-gpu --disable-gpu-compositing --disable-features=Vulkan --no-sandbox"
if [[ -n "${QTWEBENGINE_CHROMIUM_FLAGS:-}" ]]; then
  export QTWEBENGINE_CHROMIUM_FLAGS="$QTWEBENGINE_CHROMIUM_FLAGS $OPENPLOT_DEFAULT_CHROMIUM_FLAGS"
else
  export QTWEBENGINE_CHROMIUM_FLAGS="$OPENPLOT_DEFAULT_CHROMIUM_FLAGS"
fi
exec "$OPENPLOT_BUNDLE/OpenPlot" "$@"
EOF
chmod +x "$APPDIR/usr/bin/openplot-desktop"

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export APPDIR="$HERE"
exec "$HERE/usr/bin/openplot-desktop" "$@"
EOF
chmod +x "$APPDIR/AppRun"

rm -f "$OUTPUT_PATH"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$APPIMAGE_ARCH" "$APPIMAGETOOL_PATH" "$APPDIR" "$OUTPUT_PATH"
chmod +x "$OUTPUT_PATH"

echo "Built $OUTPUT_PATH"

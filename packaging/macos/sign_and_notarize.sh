#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

APP_PATH="${1:-dist/OpenPlot.app}"
DMG_PATH="${2:-dist/OpenPlot-arm64.dmg}"
NOTARY_OUTPUT_PATH="$(mktemp -t openplot-notary-output.XXXXXX.json)"
NOTARY_LOG_PATH="$(mktemp -t openplot-notary-log.XXXXXX.json)"
NOTARY_POLL_INTERVAL_SECONDS="${NOTARY_POLL_INTERVAL_SECONDS:-30}"
APPLE_KEYCHAIN_PATH="${APPLE_KEYCHAIN_PATH:-}"
APPLE_KEYCHAIN_PASSWORD="${APPLE_KEYCHAIN_PASSWORD:-}"
APPLE_SIGNING_CERT_PATH="${APPLE_SIGNING_CERT_PATH:-}"
APPLE_SIGNING_CERT_BASE64="${APPLE_SIGNING_CERT_BASE64:-}"
APPLE_SIGNING_CERT_PASSWORD="${APPLE_SIGNING_CERT_PASSWORD:-}"
APPLE_TEMP_KEYCHAIN_PATH="${APPLE_TEMP_KEYCHAIN_PATH:-}"

ORIGINAL_KEYCHAIN_LIST=()
ORIGINAL_KEYCHAIN_COUNT=0
KEYCHAIN_SEARCH_LIST_UPDATED=0
TEMP_SIGNING_CERT_PATH=""
TEMP_SIGNING_KEYCHAIN_CREATED=0

cleanup() {
  if [[ $KEYCHAIN_SEARCH_LIST_UPDATED -eq 1 && $ORIGINAL_KEYCHAIN_COUNT -gt 0 ]]; then
    security list-keychains -d user -s "${ORIGINAL_KEYCHAIN_LIST[@]}" >/dev/null 2>&1 || true
  fi

  if [[ $TEMP_SIGNING_KEYCHAIN_CREATED -eq 1 && -n "$APPLE_KEYCHAIN_PATH" ]]; then
    security delete-keychain "$APPLE_KEYCHAIN_PATH" >/dev/null 2>&1 || true
  fi

  if [[ -n "$TEMP_SIGNING_CERT_PATH" ]]; then
    rm -f "$TEMP_SIGNING_CERT_PATH"
  fi

  rm -f "$NOTARY_OUTPUT_PATH"
  rm -f "$NOTARY_LOG_PATH"
}

trap cleanup EXIT

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "error: required environment variable '$name' is not set" >&2
    exit 1
  fi
}

require_env APPLE_SIGNING_IDENTITY
require_env APPLE_API_KEY_ID
require_env APPLE_API_ISSUER_ID
require_env APPLE_API_PRIVATE_KEY_PATH

trim_keychain_line() {
  local line="$1"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%\"}"
  line="${line#\"}"
  printf '%s\n' "$line"
}

capture_current_keychain_list() {
  local line
  ORIGINAL_KEYCHAIN_LIST=()
  ORIGINAL_KEYCHAIN_COUNT=0

  while IFS= read -r line; do
    line="$(trim_keychain_line "$line")"
    if [[ -n "$line" ]]; then
      ORIGINAL_KEYCHAIN_LIST+=("$line")
      ORIGINAL_KEYCHAIN_COUNT=$((ORIGINAL_KEYCHAIN_COUNT + 1))
    fi
  done < <(security list-keychains -d user)
}

prepend_keychain_to_search_list() {
  local keychain_path="$1"
  local keychain_entry

  if [[ $KEYCHAIN_SEARCH_LIST_UPDATED -eq 1 ]]; then
    return
  fi

  capture_current_keychain_list

  if [[ $ORIGINAL_KEYCHAIN_COUNT -gt 0 ]]; then
    for keychain_entry in "${ORIGINAL_KEYCHAIN_LIST[@]}"; do
      if [[ "$keychain_entry" == "$keychain_path" ]]; then
        return
      fi
    done
  fi

  if [[ $ORIGINAL_KEYCHAIN_COUNT -gt 0 ]]; then
    security list-keychains -d user -s "$keychain_path" "${ORIGINAL_KEYCHAIN_LIST[@]}"
  else
    security list-keychains -d user -s "$keychain_path"
  fi
  KEYCHAIN_SEARCH_LIST_UPDATED=1
}

create_temp_file_path() {
  local suffix="$1"
  python - "$suffix" <<'PY'
import os
import sys
import tempfile
from pathlib import Path

suffix = sys.argv[1]
handle, path = tempfile.mkstemp(prefix="openplot-signing-", suffix=suffix)
os.close(handle)
Path(path).unlink()
print(path)
PY
}

decode_signing_cert_to_temp_file() {
  TEMP_SIGNING_CERT_PATH="$(create_temp_file_path ".p12")"

  APPLE_SIGNING_CERT_BASE64="$APPLE_SIGNING_CERT_BASE64" \
  TEMP_SIGNING_CERT_PATH="$TEMP_SIGNING_CERT_PATH" \
    python - <<'PY'
import base64
import os
from pathlib import Path

payload = os.environ["APPLE_SIGNING_CERT_BASE64"]
path = Path(os.environ["TEMP_SIGNING_CERT_PATH"])
path.write_bytes(base64.b64decode(payload))
path.chmod(0o600)
PY
}

create_temp_keychain_for_codesign() {
  local keychain_path="${APPLE_TEMP_KEYCHAIN_PATH:-}"
  local keychain_password="${APPLE_KEYCHAIN_PASSWORD:-}"

  if [[ -z "$APPLE_SIGNING_CERT_PATH" && -z "$APPLE_SIGNING_CERT_BASE64" ]]; then
    echo "error: set APPLE_SIGNING_CERT_PATH or APPLE_SIGNING_CERT_BASE64 to import a Developer ID certificate" >&2
    exit 1
  fi

  if [[ -z "$APPLE_SIGNING_CERT_PASSWORD" ]]; then
    echo "error: APPLE_SIGNING_CERT_PASSWORD is required to import the Developer ID certificate" >&2
    exit 1
  fi

  if [[ -n "$APPLE_SIGNING_CERT_BASE64" ]]; then
    decode_signing_cert_to_temp_file
    APPLE_SIGNING_CERT_PATH="$TEMP_SIGNING_CERT_PATH"
  fi

  if [[ ! -f "$APPLE_SIGNING_CERT_PATH" ]]; then
    echo "error: signing certificate not found at $APPLE_SIGNING_CERT_PATH" >&2
    exit 1
  fi

  if [[ -z "$keychain_path" ]]; then
    keychain_path="$(create_temp_file_path ".keychain-db")"
  fi

  if [[ -e "$keychain_path" ]]; then
    echo "error: temp keychain path already exists at $keychain_path" >&2
    exit 1
  fi

  if [[ -z "$keychain_password" ]]; then
    keychain_password="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
    APPLE_KEYCHAIN_PASSWORD="$keychain_password"
  fi

  APPLE_KEYCHAIN_PATH="$keychain_path"
  TEMP_SIGNING_KEYCHAIN_CREATED=1

  security create-keychain -p "$keychain_password" "$keychain_path"
  security set-keychain-settings -lut 21600 "$keychain_path"
  security unlock-keychain -p "$keychain_password" "$keychain_path"
  security import "$APPLE_SIGNING_CERT_PATH" \
    -k "$keychain_path" \
    -P "$APPLE_SIGNING_CERT_PASSWORD" \
    -T /usr/bin/codesign \
    -T /usr/bin/security \
    -T /usr/bin/productsign \
    -T /usr/bin/xcrun
  security set-key-partition-list \
    -S apple-tool:,apple: \
    -s \
    -k "$keychain_password" \
    "$keychain_path"

  prepend_keychain_to_search_list "$keychain_path"
}

prepare_keychain_for_codesign() {
  if [[ -n "$APPLE_SIGNING_CERT_PATH" || -n "$APPLE_SIGNING_CERT_BASE64" ]]; then
    create_temp_keychain_for_codesign
  fi

  if [[ -z "$APPLE_KEYCHAIN_PATH" ]]; then
    return
  fi

  if [[ ! -f "$APPLE_KEYCHAIN_PATH" ]]; then
    echo "error: keychain not found at $APPLE_KEYCHAIN_PATH" >&2
    exit 1
  fi

  if ! security show-keychain-info "$APPLE_KEYCHAIN_PATH" >/dev/null 2>&1; then
    if [[ -z "$APPLE_KEYCHAIN_PASSWORD" ]]; then
      echo "error: keychain '$APPLE_KEYCHAIN_PATH' is locked or unavailable" >&2
      echo "set APPLE_KEYCHAIN_PASSWORD (or unlock the keychain manually) and retry" >&2
      exit 1
    fi

    security unlock-keychain -p "$APPLE_KEYCHAIN_PASSWORD" "$APPLE_KEYCHAIN_PATH"
  fi

  prepend_keychain_to_search_list "$APPLE_KEYCHAIN_PATH"

  if [[ -n "$APPLE_KEYCHAIN_PASSWORD" ]]; then
    security set-key-partition-list \
      -S apple-tool:,apple: \
      -s \
      -k "$APPLE_KEYCHAIN_PASSWORD" \
      "$APPLE_KEYCHAIN_PATH"
  fi

}

ensure_signing_identity_available() {
  local identity_list

  if [[ -n "$APPLE_KEYCHAIN_PATH" ]]; then
    identity_list="$(security find-identity -v -p codesigning "$APPLE_KEYCHAIN_PATH" 2>/dev/null || true)"
  else
    identity_list="$(security find-identity -v -p codesigning 2>/dev/null || true)"
  fi

  if [[ "$identity_list" != *"$APPLE_SIGNING_IDENTITY"* ]]; then
    echo "error: signing identity '$APPLE_SIGNING_IDENTITY' not found" >&2
    if [[ -n "$identity_list" ]]; then
      echo "available identities:" >&2
      printf '%s\n' "$identity_list" >&2
    else
      echo "no valid code-signing identities are available" >&2
    fi
    exit 1
  fi
}

prepare_keychain_for_codesign
ensure_signing_identity_available

run_codesign() {
  local output
  local exit_code

  set +e
  output="$(codesign "$@" 2>&1)"
  exit_code=$?
  set -e

  if [[ $exit_code -ne 0 ]]; then
    printf '%s\n' "$output" >&2

    if [[ "$output" == *"errSecInternalComponent"* ]]; then
      echo "hint: codesign could not access the private key in the keychain" >&2
      if [[ -n "$APPLE_KEYCHAIN_PATH" ]]; then
        echo "hint: verify the identity is in $APPLE_KEYCHAIN_PATH and the key partition list was set" >&2
      fi
      if [[ -z "$APPLE_KEYCHAIN_PATH" && -z "$APPLE_SIGNING_CERT_PATH" && -z "$APPLE_SIGNING_CERT_BASE64" ]]; then
        echo "hint: set APPLE_SIGNING_CERT_PATH (or APPLE_SIGNING_CERT_BASE64) and APPLE_SIGNING_CERT_PASSWORD to import a Developer ID .p12" >&2
      fi
      if [[ -z "$APPLE_KEYCHAIN_PASSWORD" && -n "$APPLE_KEYCHAIN_PATH" ]]; then
        echo "hint: set APPLE_KEYCHAIN_PASSWORD if the selected keychain needs unlocking" >&2
      fi
    fi

    return "$exit_code"
  fi

  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  fi
}

codesign_with_identity() {
  local target_path="$1"
  shift

  local codesign_args=("$@")
  codesign_args+=(--sign "$APPLE_SIGNING_IDENTITY")
  codesign_args+=(--timestamp)

  if [[ -n "$APPLE_KEYCHAIN_PATH" ]]; then
    codesign_args+=(--keychain "$APPLE_KEYCHAIN_PATH")
  fi

  codesign_args+=("$target_path")
  run_codesign "${codesign_args[@]}"
}

NOTARYTOOL_AUTH_ARGS=(
  --key "$APPLE_API_PRIVATE_KEY_PATH"
  --key-id "$APPLE_API_KEY_ID"
  --issuer "$APPLE_API_ISSUER_ID"
)

read_notary_submission_id() {
  local payload_path="$1"
  python - "$payload_path" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("id", ""))
PY
}

read_notary_status() {
  local payload_path="$1"
  python - "$payload_path" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("status", ""))
PY
}

print_notary_log() {
  local submission_id="$1"
  if [[ -z "$submission_id" ]]; then
    return
  fi

  if xcrun notarytool log "$submission_id" "${NOTARYTOOL_AUTH_ARGS[@]}" "$NOTARY_LOG_PATH"; then
    echo "Notarization log for $submission_id:" >&2
    cat "$NOTARY_LOG_PATH" >&2
  fi
}

list_nested_sign_targets() {
  local app_path="$1"
  python - "$app_path" <<'PY'
import os
import stat
import sys
from pathlib import Path

app_path = Path(sys.argv[1]).resolve()
contents_path = app_path / "Contents"
bundle_suffixes = {".app", ".appex", ".bundle", ".framework", ".plugin", ".xpc"}
binary_suffixes = {".dylib", ".so"}
targets: list[Path] = []

for root, dirs, files in os.walk(contents_path, topdown=False):
    root_path = Path(root)

    for name in files:
        path = root_path / name
        if path.is_symlink():
            continue

        suffix = path.suffix.lower()
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            continue

        if suffix in binary_suffixes or (mode & stat.S_IXUSR):
            targets.append(path)

    for name in dirs:
        path = root_path / name
        if path.is_symlink():
            continue
        if path.suffix.lower() in bundle_suffixes:
            targets.append(path)

seen: set[Path] = set()
for path in targets:
    resolved = path.resolve()
    if resolved in seen:
        continue
    seen.add(resolved)
    sys.stdout.write(str(path))
    sys.stdout.write("\0")
PY
}

codesign_nested_target() {
  local target_path="$1"
  echo "Signing nested code: $target_path"
  codesign_with_identity \
    "$target_path" \
    --force
}

sign_app_bundle() {
  local app_path="$1"
  local target_path

  xattr -cr "$app_path"

  while IFS= read -r -d '' target_path; do
    codesign_nested_target "$target_path"
  done < <(list_nested_sign_targets "$app_path")

  echo "Signing app bundle: $app_path"
  codesign_with_identity \
    "$app_path" \
    --force \
    --options runtime
}

if [[ ! -d "$APP_PATH" ]]; then
  echo "error: app bundle not found at $APP_PATH" >&2
  exit 1
fi

if [[ ! -f "$APPLE_API_PRIVATE_KEY_PATH" ]]; then
  echo "error: notarization API key not found at $APPLE_API_PRIVATE_KEY_PATH" >&2
  exit 1
fi

echo "[1/5] Signing OpenPlot.app"
sign_app_bundle "$APP_PATH"

echo "[2/5] Verifying OpenPlot.app signature"
codesign --verify --strict --verbose=2 "$APP_PATH"

echo "[3/5] Building and signing DMG"
packaging/macos/build_dmg.sh "$APP_PATH" "$DMG_PATH"

codesign_with_identity \
  "$DMG_PATH" \
  --force
codesign --verify --verbose=2 "$DMG_PATH"

echo "[4/5] Submitting DMG for notarization"
xcrun notarytool submit \
  "$DMG_PATH" \
  "${NOTARYTOOL_AUTH_ARGS[@]}" \
  --output-format json | tee "$NOTARY_OUTPUT_PATH"

NOTARY_SUBMISSION_ID="$(read_notary_submission_id "$NOTARY_OUTPUT_PATH")"

if [[ -z "$NOTARY_SUBMISSION_ID" ]]; then
  echo "error: notarization submission did not return a submission id" >&2
  exit 1
fi

echo "Tracking notarization submission $NOTARY_SUBMISSION_ID"
while true; do
  xcrun notarytool info \
    "$NOTARY_SUBMISSION_ID" \
    "${NOTARYTOOL_AUTH_ARGS[@]}" \
    --output-format json > "$NOTARY_OUTPUT_PATH"

  NOTARY_STATUS="$(read_notary_status "$NOTARY_OUTPUT_PATH")"

  echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") notarization status: ${NOTARY_STATUS:-unknown}"

  if [[ "$NOTARY_STATUS" == "Accepted" ]]; then
    break
  fi

  if [[ "$NOTARY_STATUS" == "Invalid" || "$NOTARY_STATUS" == "Rejected" ]]; then
    print_notary_log "$NOTARY_SUBMISSION_ID"
    echo "error: notarization did not succeed (status=$NOTARY_STATUS)" >&2
    exit 1
  fi

  sleep "$NOTARY_POLL_INTERVAL_SECONDS"
done

echo "[5/5] Stapling and validating notarization"
xcrun stapler staple -v "$APP_PATH"
xcrun stapler validate -v "$APP_PATH"
xcrun stapler staple -v "$DMG_PATH"
xcrun stapler validate -v "$DMG_PATH"
spctl --assess --type execute --verbose=4 "$APP_PATH"
spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG_PATH"

echo "Signed, notarized, and stapled $DMG_PATH"

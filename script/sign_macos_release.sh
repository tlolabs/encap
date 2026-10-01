#!/usr/bin/env bash
# Sign a built, tested EnCap bundle; optionally notarize the app for ZIP distribution.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
IDENTITY="${ENCAP_SIGN_IDENTITY:?Set ENCAP_SIGN_IDENTITY to a Developer ID Application identity}"
APP="${ENCAP_APP_BUNDLE:-$ROOT/dist/EnCap.app}"
FRAMEWORK="$APP/Contents/Frameworks/Sparkle.framework"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
case "$(lipo -archs "$APP/Contents/MacOS/EnCap")" in arm64) ARCH=arm64;; x86_64) ARCH=intel;; *) exit 1;; esac
ZIP="$ROOT/dist/EnCap-${VERSION}-macos-${ARCH}-signed.zip"
if ! security find-identity -v -p codesigning | grep 'Developer ID Application:' | grep -F -- "$IDENTITY" >/dev/null; then
  echo 'A valid Developer ID Application identity is required.' >&2
  exit 1
fi
# Verify the tested payload before signing can change or bless executable hashes.
TARGET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target"])' "$APP/Contents/Resources/FFmpeg/build.json")"
python3 "$ROOT/script/ffmpeg_runtime.py" validate "$TARGET" --binary "$APP/Contents/MacOS" --metadata "$APP/Contents/Resources/FFmpeg"
sign() { codesign --force --sign "$IDENTITY" --options runtime --timestamp "$@"; }
for binary in "$APP/Contents/MacOS/"*; do
  if [[ -f "$binary" ]] && file -b "$binary" | grep -q 'Mach-O'; then sign "$binary"; fi
done
sign "$FRAMEWORK/Versions/B/XPCServices/Installer.xpc"
sign --preserve-metadata=entitlements "$FRAMEWORK/Versions/B/XPCServices/Downloader.xpc"
sign "$FRAMEWORK/Versions/B/Autoupdate"
sign "$FRAMEWORK/Versions/B/Updater.app"
sign "$FRAMEWORK"
# Preserve Core's original manifest and bind the newly signed executable hashes.
python3 "$ROOT/script/ffmpeg_runtime.py" finish "$TARGET" --binary "$APP/Contents/MacOS" --metadata "$APP/Contents/Resources/FFmpeg"
sign "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
"$APP/Contents/MacOS/encap-engine" validate-tools
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
if [[ -n "${ENCAP_NOTARY_PROFILE:-}" ]]; then
  REPORT="$ZIP.notary.json"
  xcrun notarytool submit "$ZIP" --keychain-profile "$ENCAP_NOTARY_PROFILE" --wait --output-format json > "$REPORT"
  python3 - "$REPORT" <<'PY_STATUS'
import json, sys
report = json.load(open(sys.argv[1]))
print('Notarization:', report.get('status'), report.get('id'))
if report.get('status') != 'Accepted':
    raise SystemExit('Notarization was not accepted; inspect the submission log.')
PY_STATUS
  xcrun stapler staple "$APP"
  xcrun stapler validate "$APP"
  spctl --assess --type execute --verbose=2 "$APP"
  # A ZIP cannot be stapled. Recreate it with the ticket stapled to the app.
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
else
  echo 'Signed only: notarization is still required before public distribution.' >&2
fi
(cd "$(dirname "$ZIP")" && shasum -a 256 "$(basename "$ZIP")") > "$ZIP.sha256"
printf '%s\n' "$ZIP"

#!/usr/bin/env bash
# Sign a built, tested EnCap bundle; notarize the app for ZIP distribution.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
IDENTITY="${ENCAP_SIGN_IDENTITY:?Set ENCAP_SIGN_IDENTITY to a Developer ID Application identity}"
APP="${ENCAP_APP_BUNDLE:-$ROOT/dist/EnCap.app}"
FRAMEWORK="$APP/Contents/Frameworks/Sparkle.framework"
: "${ENCAP_NOTARY_PROFILE:?Notarization is required for this final-signing path}"
# Read-only profile validation precedes all bundle mutation.
xcrun notarytool history --keychain-profile "$ENCAP_NOTARY_PROFILE" --output-format json >/dev/null
# The linked replacement remains unqualified while upstream Audio/playback
# contracts or corresponding dependency sources are absent. Never notarize it
# as a standard distributable on the strength of a startup-only smoke.
python3 "$ROOT/script/linked_runtime.py" verify-stage --directory "$APP/Contents/Frameworks" --require-qualified
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
case "$(lipo -archs "$APP/Contents/MacOS/EnCap")" in arm64) ARCH=arm64;; x86_64) ARCH=intel;; *) exit 1;; esac
ZIP="$ROOT/dist/EnCap-${VERSION}-macos-${ARCH}-signed.zip"
[[ ! -e "$ZIP" ]] || { echo "Final package output already exists; refusing replacement." >&2; exit 1; }
[[ "$IDENTITY" != "-" ]] || { echo "A Developer ID Application identity is required." >&2; exit 1; }
if ! security find-identity -v -p codesigning | grep 'Developer ID Application:' | grep -F -- "$IDENTITY" >/dev/null; then
  echo 'A valid Developer ID Application identity is required.' >&2
  exit 1
fi
# Verify the tested payload before signing can change or bless executable hashes.
TARGET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target"])' "$APP/Contents/Resources/FFmpeg/build.json")"
python3 "$ROOT/script/ffmpeg_runtime.py" validate "$TARGET" --binary "$APP/Contents/MacOS" --metadata "$APP/Contents/Resources/FFmpeg"
sign() { codesign --force --sign "$IDENTITY" --options runtime --timestamp "$@"; }
for resource_bundle in "$APP/Contents/Resources/"*.bundle; do
  [[ -d "$resource_bundle" ]] || continue
  sign "$resource_bundle"
done
while IFS= read -r -d '' resource_bundle; do
  sign "$resource_bundle"
done < <(find "$APP/Contents/Frameworks/EnCAPTranscription.framework" -type d -name '*.bundle' -print0 2>/dev/null || true)
while IFS= read -r -d '' library; do
  sign "$library"
done < <(find "$APP/Contents/Frameworks" -type f -name '*.dylib' -print0)
if [[ -d "$APP/Contents/Frameworks/EnCAPTranscription.framework" ]]; then
  sign "$APP/Contents/Frameworks/EnCAPTranscription.framework/Versions/A/EnCAPTranscription"
  sign "$APP/Contents/Frameworks/EnCAPTranscription.framework"
  python3 "$ROOT/script/stage_avid_transcriber.py" --bind-signature "$APP/Contents/Frameworks/EnCAPTranscription.framework" --metadata-directory "$APP/Contents/Resources/EnCAPTranscription"
fi
python3 "$ROOT/script/linked_runtime.py" verify-stage --directory "$APP/Contents/Frameworks" --bind-signature
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
# Nested signatures change the qualified helper, engine and resource hashes.
# Refresh the packaged smoke evidence before the enclosing signature seals it.
python3 "$ROOT/script/qualify_transcription.py" --application "$APP/Contents/MacOS/EnCap" --output "$APP/Contents/Resources/transcription-qualification.json"
sign "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
"$APP/Contents/MacOS/EnCap" --linked-operation validate-tools
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
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
VERIFY="$(mktemp -d)"
trap 'rm -rf "$VERIFY"' EXIT
ditto -x -k "$ZIP" "$VERIFY"
codesign --verify --deep --strict "$VERIFY/EnCap.app"
xcrun stapler validate "$VERIFY/EnCap.app"
spctl --assess --type execute --verbose=2 "$VERIFY/EnCap.app"
python3 "$ROOT/script/ffmpeg_runtime.py" validate "$TARGET" --binary "$VERIFY/EnCap.app/Contents/MacOS" --metadata "$VERIFY/EnCap.app/Contents/Resources/FFmpeg"
python3 "$ROOT/script/linked_runtime.py" verify-stage --directory "$VERIFY/EnCap.app/Contents/Frameworks" --require-qualified
(cd "$(dirname "$ZIP")" && shasum -a 256 "$(basename "$ZIP")") > "$ZIP.sha256"
printf '%s\n' "$ZIP"

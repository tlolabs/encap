#!/usr/bin/env bash
# Sign a built, tested EnCap bundle; optionally notarize the distribution DMG.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
IDENTITY="${ENCAP_SIGN_IDENTITY:?Set ENCAP_SIGN_IDENTITY to a Developer ID Application identity}"
APP="${ENCAP_APP_BUNDLE:-$ROOT/dist/EnCap.app}"
FRAMEWORK="$APP/Contents/Frameworks/Sparkle.framework"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
case "$(lipo -archs "$APP/Contents/MacOS/EnCap")" in arm64) ARCH=arm64;; x86_64) ARCH=intel;; *) exit 1;; esac
DMG="$ROOT/dist/EnCap-${VERSION}-macos-${ARCH}-signed.dmg"
if ! security find-identity -v -p codesigning | grep 'Developer ID Application:' | grep -F -- "$IDENTITY" >/dev/null; then
  echo 'A valid Developer ID Application identity is required.' >&2
  exit 1
fi
sign() { codesign --force --sign "$IDENTITY" --options runtime --timestamp "$@"; }
for binary in "$APP/Contents/MacOS/"*; do
  if [[ -f "$binary" ]] && file -b "$binary" | grep -q 'Mach-O'; then sign "$binary"; fi
done
sign "$FRAMEWORK/Versions/B/XPCServices/Installer.xpc"
sign --preserve-metadata=entitlements "$FRAMEWORK/Versions/B/XPCServices/Downloader.xpc"
sign "$FRAMEWORK/Versions/B/Autoupdate"
sign "$FRAMEWORK/Versions/B/Updater.app"
sign "$FRAMEWORK"
# Signing changes the FFmpeg bytes; refresh the manifest before sealing the app.
python3 - "$APP" <<'PY'
import hashlib, json, pathlib, sys
app = pathlib.Path(sys.argv[1])
manifest = app / 'Contents/Resources/FFmpeg/signed-payload.json'
data = json.loads(manifest.read_text())
data['signed_binary_sha256'] = {name: hashlib.sha256((app / 'Contents/MacOS' / name).read_bytes()).hexdigest() for name in ('ffmpeg', 'ffprobe')}
manifest.write_text(json.dumps(data, indent=2) + '\n')
PY
sign "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
"$APP/Contents/MacOS/encap-engine" validate-tools
hdiutil create -volname EnCap -srcfolder "$APP" -ov -format UDZO "$DMG"
codesign --force --sign "$IDENTITY" --timestamp "$DMG"
if [[ -n "${ENCAP_NOTARY_PROFILE:-}" ]]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$ENCAP_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
else
  echo 'Signed only: notarization is still required before public distribution.' >&2
fi
(cd "$(dirname "$DMG")" && shasum -a 256 "$(basename "$DMG")") > "$DMG.sha256"
printf '%s\n' "$DMG"

#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="EnCap"
BUNDLE_ID="com.tlolabs.encap"
SPARKLE_VERSION="2.9.4"
SPARKLE_SHA256="ce89daf967db1e1893ed3ebd67575ed82d3902563e3191ca92aaec9164fbdef9"
WHISPER_CPP_VERSION="v1.9.1"

NATIVE_ARCH="$(uname -m)"
case "$NATIVE_ARCH" in
  arm64)
    ENCAP_PLATFORM_NAME="macos-arm64"
    DMG_ARCH_LABEL="arm64"
    ;;
  x86_64)
    ENCAP_PLATFORM_NAME="macos-intel"
    DMG_ARCH_LABEL="intel"
    ;;
  *)
    echo "Unsupported macOS architecture: $NATIVE_ARCH" >&2
    exit 1
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv-packaging/bin/python"
APP_BUNDLE="$ROOT_DIR/dist/EnCap.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/EnCap"
SPARKLE_DIR="$ROOT_DIR/.sparkle"
SPARKLE_ARCHIVE="$SPARKLE_DIR/Sparkle.tar.xz"
SPARKLE_FRAMEWORK="$SPARKLE_DIR/Sparkle.framework"
PUBLIC_KEY_FILE="$ROOT_DIR/src/encap/update_public_key.txt"
WHISPER_CPP_DIR="$ROOT_DIR/.whisper-cpp"
APPLE_TRANSCRIBER="$ROOT_DIR/.build-tools/apple-transcriber"
WHISPERKIT_PACKAGE="$ROOT_DIR/helpers/whisperkit_transcriber"
WHISPERKIT_BUILD_DIR="$ROOT_DIR/.build-tools/whisperkit-transcriber-build"
WHISPERKIT_TRANSCRIBER="$ROOT_DIR/.build-tools/whisperkit-transcriber"
XCODE_DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ACTOOL="$XCODE_DEVELOPER_DIR/usr/bin/actool"
ICON_COMPOSER_TOOL="/Applications/Icon Composer.app/Contents/Executables/ictool"
ICON_DOCUMENT="$ROOT_DIR/assets/icons/liquid-glass/AppIcon.icon"
ICON_BUILD_DIR="$ROOT_DIR/build/icon-composer-compiled"
ICON_ASSET_CAR="$ICON_BUILD_DIR/Assets.car"
ICON_FALLBACK="$ICON_BUILD_DIR/AppIcon.icns"
ICON_FALLBACK_SOURCE="$ICON_BUILD_DIR/AppIcon-default.png"
ICON_FALLBACK_SET="$ICON_BUILD_DIR/AppIcon.iconset"
ICON_PARTIAL_PLIST="$ICON_BUILD_DIR/assetcatalog_generated_info.plist"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing packaging environment: $PYTHON" >&2
  echo "Create it and install the project plus PyInstaller first." >&2
  exit 1
fi
if [[ ! -s "$PUBLIC_KEY_FILE" ]]; then
  echo "Missing update public key: $PUBLIC_KEY_FILE" >&2
  echo "Run: $PYTHON scripts/configure_update_keys.py" >&2
  exit 1
fi
if [[ ! -x "$ACTOOL" ]]; then
  echo "Missing Xcode 26 asset compiler: $ACTOOL" >&2
  exit 1
fi
if [[ ! -x "$ICON_COMPOSER_TOOL" ]]; then
  echo "Missing Icon Composer export tool: $ICON_COMPOSER_TOOL" >&2
  exit 1
fi
if [[ ! -d "$ICON_DOCUMENT" ]]; then
  echo "Missing Icon Composer document: $ICON_DOCUMENT" >&2
  exit 1
fi

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

mkdir -p "$ICON_BUILD_DIR"
DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" "$ACTOOL" \
  "$ICON_DOCUMENT" \
  --compile "$ICON_BUILD_DIR" \
  --output-format human-readable-text \
  --notices \
  --warnings \
  --output-partial-info-plist "$ICON_PARTIAL_PLIST" \
  --app-icon AppIcon \
  --compress-pngs \
  --enable-on-demand-resources NO \
  --development-region en \
  --minimum-deployment-target 13.0 \
  --platform macosx
test -s "$ICON_ASSET_CAR"
test -s "$ICON_FALLBACK"

# The asset compiler's compatibility ICNS currently tops out at 256 px. Build
# a complete static fallback from the Default (light) rendition for legacy
# macOS, while retaining Assets.car for appearance-aware current systems.
rm -rf "$ICON_FALLBACK_SET"
mkdir -p "$ICON_FALLBACK_SET"
"$ICON_COMPOSER_TOOL" \
  "$ICON_DOCUMENT" \
  --export-image \
  --output-file "$ICON_FALLBACK_SOURCE" \
  --platform macOS \
  --rendition Default \
  --width 1024 \
  --height 1024 \
  --scale 1 \
  --light-angle -45 >/dev/null
for ICON_SPEC in \
  "16 icon_16x16.png" \
  "32 icon_16x16@2x.png" \
  "32 icon_32x32.png" \
  "64 icon_32x32@2x.png" \
  "128 icon_128x128.png" \
  "256 icon_128x128@2x.png" \
  "256 icon_256x256.png" \
  "512 icon_256x256@2x.png" \
  "512 icon_512x512.png" \
  "1024 icon_512x512@2x.png"; do
  read -r ICON_SIZE ICON_NAME <<< "$ICON_SPEC"
  sips -z "$ICON_SIZE" "$ICON_SIZE" "$ICON_FALLBACK_SOURCE" \
    --out "$ICON_FALLBACK_SET/$ICON_NAME" >/dev/null
done
iconutil -c icns "$ICON_FALLBACK_SET" -o "$ICON_FALLBACK"
test "$(sips -g pixelWidth "$ICON_FALLBACK" | awk '/pixelWidth/ {print $2}')" = "1024"

mkdir -p "$SPARKLE_DIR"
if [[ ! -f "$SPARKLE_ARCHIVE" ]]; then
  curl --fail --location --silent --show-error \
    "https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/Sparkle-${SPARKLE_VERSION}.tar.xz" \
    --output "$SPARKLE_ARCHIVE"
fi
echo "$SPARKLE_SHA256  $SPARKLE_ARCHIVE" | shasum -a 256 --check
if [[ ! -d "$SPARKLE_FRAMEWORK" ]]; then
  tar -xJf "$SPARKLE_ARCHIVE" -C "$SPARKLE_DIR"
fi

if [[ ! -d "$WHISPER_CPP_DIR/.git" ]]; then
  git clone --branch "$WHISPER_CPP_VERSION" --depth 1 \
    https://github.com/ggml-org/whisper.cpp.git "$WHISPER_CPP_DIR"
fi
test "$(git -C "$WHISPER_CPP_DIR" describe --tags --exact-match)" = "$WHISPER_CPP_VERSION"
cmake -S "$WHISPER_CPP_DIR" -B "$WHISPER_CPP_DIR/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_SERVER=OFF
cmake --build "$WHISPER_CPP_DIR/build" --config Release --target whisper-cli

mkdir -p "$(dirname "$APPLE_TRANSCRIBER")"
swiftc -swift-version 5 -O "$ROOT_DIR/helpers/apple_transcriber.swift" \
  -o "$APPLE_TRANSCRIBER"
if [[ "$NATIVE_ARCH" == "arm64" ]]; then
  swift build \
    --package-path "$WHISPERKIT_PACKAGE" \
    --scratch-path "$WHISPERKIT_BUILD_DIR" \
    --configuration release \
    --product whisperkit-transcriber
  WHISPERKIT_BIN_DIR="$(swift build \
    --package-path "$WHISPERKIT_PACKAGE" \
    --scratch-path "$WHISPERKIT_BUILD_DIR" \
    --configuration release \
    --show-bin-path)"
  cp "$WHISPERKIT_BIN_DIR/whisperkit-transcriber" "$WHISPERKIT_TRANSCRIBER"
  chmod +x "$WHISPERKIT_TRANSCRIBER"
fi

APP_VERSION="$($PYTHON -c "import runpy; print(runpy.run_path('$ROOT_DIR/src/encap/version.py')['__version__'])")"
UPDATE_PUBLIC_KEY="$(tr -d '\r\n' < "$PUBLIC_KEY_FILE")"

cd "$ROOT_DIR"
ENCAP_PLATFORM="$ENCAP_PLATFORM_NAME" \
ENCAP_UPDATE_PUBLIC_KEY="$UPDATE_PUBLIC_KEY" \
  "$PYTHON" -m PyInstaller --noconfirm --clean encap_gui.spec

cp "$ICON_ASSET_CAR" "$APP_BUNDLE/Contents/Resources/Assets.car"
cp "$ICON_FALLBACK" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile AppIcon' "$APP_BUNDLE/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Delete :CFBundleIconName' "$APP_BUNDLE/Contents/Info.plist" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconName string AppIcon' "$APP_BUNDLE/Contents/Info.plist"

for TOOL_NAME in ffmpeg ffprobe; do
  TOOL_PATH="$(command -v "$TOOL_NAME")"
  cp "$TOOL_PATH" "$APP_BUNDLE/Contents/MacOS/$TOOL_NAME"
  chmod +x "$APP_BUNDLE/Contents/MacOS/$TOOL_NAME"
  codesign --force --sign - "$APP_BUNDLE/Contents/MacOS/$TOOL_NAME"
done

cp "$WHISPER_CPP_DIR/build/bin/whisper-cli" "$APP_BUNDLE/Contents/MacOS/whisper-cli"
chmod +x "$APP_BUNDLE/Contents/MacOS/whisper-cli"
codesign --force --sign - "$APP_BUNDLE/Contents/MacOS/whisper-cli"
cp "$APPLE_TRANSCRIBER" "$APP_BUNDLE/Contents/MacOS/apple-transcriber"
chmod +x "$APP_BUNDLE/Contents/MacOS/apple-transcriber"
codesign --force --sign - "$APP_BUNDLE/Contents/MacOS/apple-transcriber"
if [[ "$NATIVE_ARCH" == "arm64" && -x "$WHISPERKIT_TRANSCRIBER" ]]; then
  cp "$WHISPERKIT_TRANSCRIBER" "$APP_BUNDLE/Contents/MacOS/whisperkit-transcriber"
  chmod +x "$APP_BUNDLE/Contents/MacOS/whisperkit-transcriber"
  codesign --force --sign - "$APP_BUNDLE/Contents/MacOS/whisperkit-transcriber"
fi

ditto "$SPARKLE_FRAMEWORK" "$APP_BUNDLE/Contents/Frameworks/Sparkle.framework"
codesign --force --sign - "$APP_BUNDLE/Contents/Frameworks/Sparkle.framework"
codesign --force --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"
plutil -lint "$APP_BUNDLE/Contents/Info.plist"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP_BUNDLE/Contents/Info.plist")" = "$BUNDLE_ID"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP_BUNDLE/Contents/Info.plist")" = "$APP_VERSION"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconFile' "$APP_BUNDLE/Contents/Info.plist")" = "AppIcon"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconName' "$APP_BUNDLE/Contents/Info.plist")" = "AppIcon"
assetutil --info "$APP_BUNDLE/Contents/Resources/Assets.car" > "$ICON_BUILD_DIR/bundle-assets.json"
grep '"AssetType" : "IconGroup"' "$ICON_BUILD_DIR/bundle-assets.json" >/dev/null
file "$APP_BINARY" | grep "$NATIVE_ARCH" >/dev/null

open_app() {
  /usr/bin/open -n "$APP_BUNDLE"
}

package_dmg() {
  local dmg_path="$ROOT_DIR/dist/EnCap-${APP_VERSION}-macos-${DMG_ARCH_LABEL}.dmg"
  hdiutil create \
    -volname EnCap \
    -srcfolder "$APP_BUNDLE" \
    -ov \
    -format UDZO \
    "$dmg_path"
  echo "$dmg_path"
}

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    sleep 2
    pgrep -x "$APP_NAME" >/dev/null
    ;;
  --package|package)
    package_dmg
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package]" >&2
    exit 2
    ;;
esac

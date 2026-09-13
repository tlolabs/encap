#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="EnCap"
BUNDLE_ID="com.tlolabs.encap"
SPARKLE_VERSION="2.9.6"
SPARKLE_SHA256="52bf9e88cdd972fc0c81501377a880e90d47031bd8ca5462488f843e2609e192"
WHISPER_CPP_VERSION="v1.9.1"
WHISPER_CPP_COMMIT="f049fff95a089aa9969deb009cdd4892b3e74916"

NATIVE_ARCH="$(uname -m)"
case "$NATIVE_ARCH" in
  arm64) DMG_ARCH_LABEL="arm64" ;;
  x86_64) DMG_ARCH_LABEL="intel" ;;
  *)
    echo "Unsupported macOS architecture: $NATIVE_ARCH" >&2
    exit 1
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CARGO="${CARGO:-$HOME/.cargo/bin/cargo}"
APP_BUNDLE="$ROOT_DIR/dist/EnCap.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_FRAMEWORKS="$APP_CONTENTS/Frameworks"
APP_BINARY="$APP_MACOS/EnCap"
ENGINE_BINARY="$APP_MACOS/encap-engine"
INFO_PLIST="$APP_CONTENTS/Info.plist"
XCODE_PROJECT="$ROOT_DIR/macos/EnCap.xcodeproj"
XCODE_BUILD_DIR="$ROOT_DIR/build/xcode"
XCODE_APP="$XCODE_BUILD_DIR/Build/Products/Release/EnCap.app"
RUST_ENGINE="$ROOT_DIR/target/release/encap-engine"
SPARKLE_DIR="$ROOT_DIR/.sparkle"
SPARKLE_VERSION_DIR="$SPARKLE_DIR/$SPARKLE_VERSION"
SPARKLE_ARCHIVE="$SPARKLE_DIR/Sparkle-$SPARKLE_VERSION.tar.xz"
SPARKLE_FRAMEWORK="$SPARKLE_VERSION_DIR/Sparkle.framework"
PUBLIC_KEY_FILE="$ROOT_DIR/src/encap/update_public_key.txt"
WHISPER_CPP_DIR="$ROOT_DIR/.whisper-cpp"
APPLE_TRANSCRIBER="$ROOT_DIR/.build-tools/apple-transcriber"
APPLE_AAC_INFO="$ROOT_DIR/.build-tools/apple-aac-info"
WHISPERKIT_PACKAGE="$ROOT_DIR/helpers/whisperkit_transcriber"
WHISPERKIT_BUILD_DIR="$ROOT_DIR/.build-tools/whisperkit-transcriber-build"
WHISPERKIT_TRANSCRIBER="$ROOT_DIR/.build-tools/whisperkit-transcriber"
XCODE_DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
ICON_DOCUMENT="$ROOT_DIR/assets/icons/liquid-glass/AppIcon.icon"
LEGACY_ICON="$ROOT_DIR/assets/icons/EnCap.icns"
ICON_REPORT="$ROOT_DIR/build/icon-assets.json"

if [[ ! -x "$CARGO" ]]; then
  echo "Missing Rust toolchain: $CARGO" >&2
  echo "Install Rust with rustup before building EnCap." >&2
  exit 1
fi
if [[ ! -s "$PUBLIC_KEY_FILE" ]]; then
  echo "Missing update public key: $PUBLIC_KEY_FILE" >&2
  echo "Run the legacy key setup helper under legacy-python before building a release." >&2
  exit 1
fi
if [[ ! -x "$XCODE_DEVELOPER_DIR/usr/bin/xcodebuild" ]]; then
  echo "Missing Xcode build tool: $XCODE_DEVELOPER_DIR/usr/bin/xcodebuild" >&2
  exit 1
fi
if [[ ! -d "$ICON_DOCUMENT" ]]; then
  echo "Missing Icon Composer document: $ICON_DOCUMENT" >&2
  exit 1
fi

pkill -x "$APP_NAME" >/dev/null 2>&1 || true

APP_VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT_DIR/Cargo.toml" | head -n 1)"
UPDATE_PUBLIC_KEY="$(tr -d '\r\n' < "$PUBLIC_KEY_FILE")"
ENCAP_PLATFORM_NAME="macos-$DMG_ARCH_LABEL"
FFMPEG_INSTALL_DIR="$("$ROOT_DIR/script/build_ffmpeg.sh" | tail -n 1)"

mkdir -p "$SPARKLE_DIR"
if [[ ! -f "$SPARKLE_ARCHIVE" ]]; then
  curl --fail --location --silent --show-error \
    "https://github.com/sparkle-project/Sparkle/releases/download/${SPARKLE_VERSION}/Sparkle-${SPARKLE_VERSION}.tar.xz" \
    --output "$SPARKLE_ARCHIVE"
fi
echo "$SPARKLE_SHA256  $SPARKLE_ARCHIVE" | shasum -a 256 --check
if [[ ! -d "$SPARKLE_FRAMEWORK" ]]; then
  mkdir -p "$SPARKLE_VERSION_DIR"
  tar -xJf "$SPARKLE_ARCHIVE" -C "$SPARKLE_VERSION_DIR"
fi

# Building the application through its Xcode target is required for Icon
# Composer. Xcode links the layered icon stack and generates the compatibility
# renditions as one atomic asset-catalog operation.
DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" xcodebuild \
  -project "$XCODE_PROJECT" \
  -scheme EnCap \
  -configuration Release \
  -derivedDataPath "$XCODE_BUILD_DIR" \
  CODE_SIGNING_ALLOWED=NO \
  ARCHS="$NATIVE_ARCH" \
  ONLY_ACTIVE_ARCH=YES \
  MARKETING_VERSION="$APP_VERSION" \
  CURRENT_PROJECT_VERSION="$APP_VERSION" \
  PRODUCT_BUNDLE_IDENTIFIER="$BUNDLE_ID" \
  build
test -x "$XCODE_APP/Contents/MacOS/EnCap"

cd "$ROOT_DIR"
"$CARGO" build --locked --release --package encap-engine
test -x "$RUST_ENGINE"

if [[ ! -d "$WHISPER_CPP_DIR/.git" ]]; then
  git clone --branch "$WHISPER_CPP_VERSION" --depth 1 \
    https://github.com/ggml-org/whisper.cpp.git "$WHISPER_CPP_DIR"
fi
test "$(git -C "$WHISPER_CPP_DIR" describe --tags --exact-match)" = "$WHISPER_CPP_VERSION"
test "$(git -C "$WHISPER_CPP_DIR" rev-parse HEAD)" = "$WHISPER_CPP_COMMIT"
cmake -S "$WHISPER_CPP_DIR" -B "$WHISPER_CPP_DIR/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF \
  -DGGML_OPENMP=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_SERVER=OFF
cmake --build "$WHISPER_CPP_DIR/build" --config Release --target whisper-cli

mkdir -p "$(dirname "$APPLE_TRANSCRIBER")"
DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swiftc -swift-version 5 -O \
  "$ROOT_DIR/helpers/apple_transcriber.swift" -o "$APPLE_TRANSCRIBER"
DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swiftc -swift-version 5 -O \
  "$ROOT_DIR/helpers/apple_aac_info.swift" -o "$APPLE_AAC_INFO"
if [[ "$NATIVE_ARCH" == "arm64" ]]; then
  DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swift build \
    --package-path "$WHISPERKIT_PACKAGE" \
    --scratch-path "$WHISPERKIT_BUILD_DIR" \
    --configuration release \
    --product whisperkit-transcriber
  WHISPERKIT_BIN_DIR="$(DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" swift build \
    --package-path "$WHISPERKIT_PACKAGE" \
    --scratch-path "$WHISPERKIT_BUILD_DIR" \
    --configuration release \
    --show-bin-path)"
  cp "$WHISPERKIT_BIN_DIR/whisperkit-transcriber" "$WHISPERKIT_TRANSCRIBER"
  chmod +x "$WHISPERKIT_TRANSCRIBER"
fi

rm -rf "$APP_BUNDLE"
ditto "$XCODE_APP" "$APP_BUNDLE"
mkdir -p "$APP_MACOS" "$APP_RESOURCES" "$APP_FRAMEWORKS"
if [[ ! -s "$APP_RESOURCES/AppIcon.icns" ]]; then
  cp "$LEGACY_ICON" "$APP_RESOURCES/AppIcon.icns"
fi
cp "$RUST_ENGINE" "$ENGINE_BINARY"
cp "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$APP_RESOURCES/THIRD_PARTY_NOTICES.md"
ditto "$SPARKLE_FRAMEWORK" "$APP_FRAMEWORKS/Sparkle.framework"
chmod +x "$APP_BINARY" "$ENGINE_BINARY"
/usr/libexec/PlistBuddy -c "Add :SUFeedURL string https://github.com/tlolabs/encap/releases/latest/download/appcast-$ENCAP_PLATFORM_NAME.xml" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Add :SUPublicEDKey string $UPDATE_PUBLIC_KEY" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUEnableAutomaticChecks bool true' "$INFO_PLIST"
/usr/libexec/PlistBuddy -c 'Add :SUAutomaticallyUpdate bool true' "$INFO_PLIST"

for TOOL_NAME in ffmpeg ffprobe; do
  cp "$FFMPEG_INSTALL_DIR/bin/$TOOL_NAME" "$APP_MACOS/$TOOL_NAME"
  chmod +x "$APP_MACOS/$TOOL_NAME"
done
cp "$WHISPER_CPP_DIR/build/bin/whisper-cli" "$APP_MACOS/whisper-cli"
cp "$APPLE_TRANSCRIBER" "$APP_MACOS/apple-transcriber"
cp "$APPLE_AAC_INFO" "$APP_MACOS/apple-aac-info"
chmod +x "$APP_MACOS/whisper-cli" "$APP_MACOS/apple-transcriber" "$APP_MACOS/apple-aac-info"
if [[ "$NATIVE_ARCH" == "arm64" && -x "$WHISPERKIT_TRANSCRIBER" ]]; then
  cp "$WHISPERKIT_TRANSCRIBER" "$APP_MACOS/whisperkit-transcriber"
  chmod +x "$APP_MACOS/whisperkit-transcriber"
fi

for SIGNABLE in "$APP_MACOS"/*; do
  codesign --force --sign - "$SIGNABLE"
done
codesign --force --sign - "$APP_FRAMEWORKS/Sparkle.framework"
# CI packages use an ad-hoc identity. Re-sign the complete nested-code graph so
# architecture-specific helper binaries cannot retain or lose a stale signature.
codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"
plutil -lint "$INFO_PLIST"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")" = "$BUNDLE_ID"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$INFO_PLIST")" = "$APP_VERSION"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconName' "$INFO_PLIST")" = "AppIcon"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIconFile' "$INFO_PLIST")" = "AppIcon"
test -s "$APP_RESOURCES/AppIcon.icns"
if [[ -s "$APP_RESOURCES/Assets.car" ]]; then
  assetutil --info "$APP_RESOURCES/Assets.car" > "$ICON_REPORT"
  grep '"AssetType" : "IconImageStack"' "$ICON_REPORT" >/dev/null
fi
file "$APP_BINARY" | grep "$NATIVE_ARCH" >/dev/null

open_app() {
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APP_BUNDLE" >/dev/null
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
  run) open_app ;;
  --debug|debug) lldb -- "$APP_BINARY" ;;
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
  --package|package) package_dmg ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package]" >&2
    exit 2
    ;;
esac

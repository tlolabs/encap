#!/usr/bin/env bash
set -euo pipefail

FFMPEG_VERSION="9.0.1"
FFMPEG_SHA256="cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635"
LAME_VERSION="4.0"
LAME_SHA256="3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ARCHIVE="$ROOT_DIR/.build-tools/ffmpeg-$FFMPEG_VERSION.tar.xz"
SOURCE_DIR="$ROOT_DIR/.build-tools/ffmpeg-$FFMPEG_VERSION"
INSTALL_DIR="$ROOT_DIR/.build-tools/ffmpeg-$FFMPEG_VERSION-install-$(uname -m)"
LAME_ARCHIVE="$ROOT_DIR/.build-tools/lame-$LAME_VERSION.tar.gz"
LAME_SOURCE_DIR="$ROOT_DIR/.build-tools/lame-$LAME_VERSION"
LAME_INSTALL_DIR="$ROOT_DIR/.build-tools/lame-$LAME_VERSION-install-$(uname -m)"
XCODE_DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
CLANG="$XCODE_DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang"
SDKROOT="$(DEVELOPER_DIR="$XCODE_DEVELOPER_DIR" xcrun --sdk macosx --show-sdk-path)"
TARGET_ARCH="$(uname -m)"

has_linker_signature() {
  codesign -dvv "$1" 2>&1 | grep 'linker-signed' >/dev/null
}

if [[ -x "$INSTALL_DIR/bin/ffmpeg" && -x "$INSTALL_DIR/bin/ffprobe" ]] && \
   ! otool -L "$INSTALL_DIR/bin/ffmpeg" "$INSTALL_DIR/bin/ffprobe" | grep -Eq '/(opt|usr/local)/homebrew|/Cellar/' && \
   has_linker_signature "$INSTALL_DIR/bin/ffmpeg" && \
   has_linker_signature "$INSTALL_DIR/bin/ffprobe"; then
  "$INSTALL_DIR/bin/ffmpeg" -version | grep -q "ffmpeg version $FFMPEG_VERSION"
  printf '%s\n' "$INSTALL_DIR"
  exit 0
fi

mkdir -p "$ROOT_DIR/.build-tools"
if [[ ! -f "$SOURCE_ARCHIVE" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" \
    --output "$SOURCE_ARCHIVE"
fi
echo "$FFMPEG_SHA256  $SOURCE_ARCHIVE" | shasum -a 256 --check
if [[ ! -d "$SOURCE_DIR" ]]; then
  tar -xJf "$SOURCE_ARCHIVE" -C "$ROOT_DIR/.build-tools"
fi

if [[ ! -f "$LAME_ARCHIVE" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" \
    --output "$LAME_ARCHIVE"
fi
echo "$LAME_SHA256  $LAME_ARCHIVE" | shasum -a 256 --check
if [[ ! -d "$LAME_SOURCE_DIR" ]]; then
  tar -xzf "$LAME_ARCHIVE" -C "$ROOT_DIR/.build-tools"
fi
if [[ ! -f "$LAME_INSTALL_DIR/lib/libmp3lame.a" ]]; then
  rm -rf "$LAME_INSTALL_DIR"
  mkdir -p "$LAME_INSTALL_DIR"
  cd "$LAME_SOURCE_DIR"
  make distclean >/dev/null 2>&1 || true
  CC="$CLANG" \
  CFLAGS="--sysroot=$SDKROOT -arch $TARGET_ARCH -mmacosx-version-min=13.0 -Wno-implicit-function-declaration" \
  LDFLAGS="--sysroot=$SDKROOT -arch $TARGET_ARCH -mmacosx-version-min=13.0" \
  PKG_CONFIG="$ROOT_DIR/script/pkg-config-disabled" \
  ac_cv_prog_cc_c23=no \
  ./configure \
    --prefix="$LAME_INSTALL_DIR" \
    --disable-dependency-tracking \
    --disable-debug \
    --disable-shared \
    --enable-static \
    --disable-decoder \
    --disable-frontend
  make -j"$(sysctl -n hw.logicalcpu)"
  make install
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$SOURCE_DIR"
make distclean >/dev/null 2>&1 || true
PKG_CONFIG_PATH="$LAME_INSTALL_DIR/lib/pkgconfig" ./configure \
  --prefix="$INSTALL_DIR" \
  --cc="$CLANG" \
  --sysroot="$SDKROOT" \
  --extra-cflags="-arch $TARGET_ARCH -mmacosx-version-min=13.0 -I$LAME_INSTALL_DIR/include" \
  --extra-ldflags="-arch $TARGET_ARCH -mmacosx-version-min=13.0 -Wl,-adhoc_codesign -L$LAME_INSTALL_DIR/lib" \
  --host-cflags="--sysroot=$SDKROOT" \
  --host-ldflags="--sysroot=$SDKROOT" \
  --pkg-config-flags="--static" \
  --disable-shared \
  --enable-static \
  --disable-doc \
  --disable-debug \
  --disable-ffplay \
  --disable-network \
  --disable-autodetect \
  --disable-x86asm \
  --enable-gpl \
  --enable-libmp3lame \
  --enable-zlib \
  --enable-audiotoolbox \
  --enable-videotoolbox
make -j"$(sysctl -n hw.logicalcpu)"
make install

"$INSTALL_DIR/bin/ffmpeg" -hide_banner -version | grep -q "ffmpeg version $FFMPEG_VERSION"
"$INSTALL_DIR/bin/ffprobe" -hide_banner -version | grep -q "ffprobe version $FFMPEG_VERSION"
has_linker_signature "$INSTALL_DIR/bin/ffmpeg"
has_linker_signature "$INSTALL_DIR/bin/ffprobe"
printf '%s\n' "$INSTALL_DIR"

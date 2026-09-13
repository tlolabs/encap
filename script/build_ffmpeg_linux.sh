#!/usr/bin/env bash
set -euo pipefail

FFMPEG_VERSION="9.0.1"
FFMPEG_SHA256="cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635"
LAME_VERSION="4.0"
LAME_SHA256="3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="$ROOT_DIR/.build-tools"
ARCH="$(uname -m)"
FFMPEG_ARCHIVE="$BUILD_ROOT/ffmpeg-$FFMPEG_VERSION.tar.xz"
FFMPEG_SOURCE="$BUILD_ROOT/ffmpeg-$FFMPEG_VERSION"
FFMPEG_INSTALL="$BUILD_ROOT/ffmpeg-$FFMPEG_VERSION-install-$ARCH"
LAME_ARCHIVE="$BUILD_ROOT/lame-$LAME_VERSION.tar.gz"
LAME_SOURCE="$BUILD_ROOT/lame-$LAME_VERSION"
LAME_INSTALL="$BUILD_ROOT/lame-$LAME_VERSION-install-$ARCH"

if [[ -x "$FFMPEG_INSTALL/bin/ffmpeg" && -x "$FFMPEG_INSTALL/bin/ffprobe" ]]; then
  "$FFMPEG_INSTALL/bin/ffmpeg" -version | grep -q "ffmpeg version $FFMPEG_VERSION"
  printf '%s\n' "$FFMPEG_INSTALL"
  exit 0
fi

mkdir -p "$BUILD_ROOT"
if [[ ! -f "$FFMPEG_ARCHIVE" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" \
    --output "$FFMPEG_ARCHIVE"
fi
echo "$FFMPEG_SHA256  $FFMPEG_ARCHIVE" | sha256sum --check
if [[ ! -d "$FFMPEG_SOURCE" ]]; then tar -xJf "$FFMPEG_ARCHIVE" -C "$BUILD_ROOT"; fi

if [[ ! -f "$LAME_ARCHIVE" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" \
    --output "$LAME_ARCHIVE"
fi
echo "$LAME_SHA256  $LAME_ARCHIVE" | sha256sum --check
if [[ ! -d "$LAME_SOURCE" ]]; then tar -xzf "$LAME_ARCHIVE" -C "$BUILD_ROOT"; fi
if [[ ! -f "$LAME_INSTALL/lib/libmp3lame.a" ]]; then
  rm -rf "$LAME_INSTALL"
  mkdir -p "$LAME_INSTALL"
  cd "$LAME_SOURCE"
  make distclean >/dev/null 2>&1 || true
  PKG_CONFIG="$ROOT_DIR/script/pkg-config-disabled" ac_cv_prog_cc_c23=no ./configure \
    --prefix="$LAME_INSTALL" \
    --disable-dependency-tracking \
    --disable-debug \
    --disable-shared \
    --enable-static \
    --disable-decoder \
    --disable-frontend
  make -j"$(nproc)"
  make install
fi

rm -rf "$FFMPEG_INSTALL"
mkdir -p "$FFMPEG_INSTALL"
cd "$FFMPEG_SOURCE"
make distclean >/dev/null 2>&1 || true
PKG_CONFIG_PATH="$LAME_INSTALL/lib/pkgconfig" ./configure \
  --prefix="$FFMPEG_INSTALL" \
  --extra-cflags="-I$LAME_INSTALL/include" \
  --extra-ldflags="-L$LAME_INSTALL/lib" \
  --pkg-config-flags="--static" \
  --disable-shared \
  --enable-static \
  --disable-doc \
  --disable-debug \
  --disable-ffplay \
  --disable-network \
  --disable-autodetect \
  --enable-gpl \
  --enable-libmp3lame \
  --enable-zlib
make -j"$(nproc)"
make install

"$FFMPEG_INSTALL/bin/ffmpeg" -hide_banner -version | grep -q "ffmpeg version $FFMPEG_VERSION"
"$FFMPEG_INSTALL/bin/ffprobe" -hide_banner -version | grep -q "ffprobe version $FFMPEG_VERSION"
"$FFMPEG_INSTALL/bin/ffmpeg" -hide_banner -encoders | grep -q libmp3lame
printf '%s\n' "$FFMPEG_INSTALL"

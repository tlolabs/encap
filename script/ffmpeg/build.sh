#!/usr/bin/env bash
# One native source recipe for every EnCAP distribution. stdout is the prefix only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SPEC="$ROOT/runtime/ffmpeg/dependencies.json"
PLATFORM="${1:?macos, windows or linux}"
ARCH="${2:?arm64 or x86_64}"
ACTION="${3:-build}"
case "$ARCH" in aarch64) ARCH=arm64;; amd64|x64) ARCH=x86_64;; esac
TARGET="$PLATFORM-$ARCH"
jq -b -e --arg target "$TARGET" '.targets | index($target) != null' "$SPEC" >/dev/null
for tool in jq curl tar git gpg gpgv cmake make pkg-config; do command -v "$tool" >/dev/null; done
export LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$(jq -b -r .source_date_epoch "$SPEC")" ZERO_AR_DATE=1
export CC="${CC:-cc}" CXX="${CXX:-c++}"
# User flags would be hidden recipe inputs. Reject them rather than reuse a wrong cache.
for flag in CFLAGS CXXFLAGS CPPFLAGS LDFLAGS; do
  if [[ -n "${!flag:-}" ]]; then echo "Unset $flag; change the versioned recipe instead." >&2; exit 1; fi
done
case "$PLATFORM" in
  macos) [[ "$(uname -s)" == Darwin ]]; export MACOSX_DEPLOYMENT_TARGET=13.0 DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}";;
  linux) [[ "$(uname -s)" == Linux ]];;
  windows) [[ "${MSYSTEM:-}" == CLANG64 || "${MSYSTEM:-}" == CLANGARM64 ]]; export CC=clang CXX=clang++;;
esac
NATIVE="$($CC -dumpmachine)"
case "$ARCH:$NATIVE" in
  arm64:arm64-*|arm64:aarch64-*|x86_64:x86_64-*) ;;
  *) echo "Native compiler $NATIVE cannot build requested $TARGET" >&2; exit 1;;
esac
WORK_ROOT="${ENCAP_FFMPEG_WORK_ROOT:-$ROOT/.build-tools/encap-ffmpeg}"
mkdir -p "$WORK_ROOT"
WORK_ROOT="$(cd "$WORK_ROOT" && pwd)"
TOOLCHAIN="$(mktemp "$WORK_ROOT/toolchain.XXXXXX")"
trap 'rm -f "$TOOLCHAIN"' EXIT
{
  echo "target=$TARGET"; echo "epoch=$SOURCE_DATE_EPOCH"; echo "deployment=${MACOSX_DEPLOYMENT_TARGET:-}"
  echo "image=${ImageOS:-local}/${ImageVersion:-local}"; uname -srm
  for tool in "$CC" "$CXX" cmake make nasm pkg-config git ar ld; do
    command -v "$tool" || true
    "$tool" --version 2>&1 || true
  done
  if [[ "$PLATFORM" == macos ]]; then xcodebuild -version; xcrun --show-sdk-version; xcrun --show-sdk-path; fi
  if [[ "$PLATFORM" == windows ]]; then pacman -Q; fi
  if [[ "$PLATFORM" == linux ]]; then ldd --version; dpkg-query -W libc6 libc6-dev binutils gcc g++ 2>/dev/null || true; fi
} > "$TOOLCHAIN"
sha() { shasum -a 256 "$1" | awk '{print $1}'; }
RECIPE="$(cat "$SPEC" "$ROOT"/runtime/ffmpeg/release-key.asc "$ROOT/script/ffmpeg/build.sh" | shasum -a 256 | awk '{print $1}')"
KEY="$(printf '%s\n%s\n' "$RECIPE" "$(sha "$TOOLCHAIN")" | shasum -a 256 | awk '{print $1}')"
PREFIX="$WORK_ROOT/$TARGET-$KEY"
if [[ "$ACTION" == key ]]; then printf '%s\n' "$TARGET-$KEY"; exit; fi
if [[ "$ACTION" != build && "$ACTION" != clean ]]; then echo 'Expected build, key, or clean' >&2; exit 2; fi
if [[ "$ACTION" == build && -f "$PREFIX/files.sha256" ]] && (cd "$PREFIX" && shasum -a 256 -c files.sha256 >&2); then
  printf '%s\n' "$PREFIX"; exit
fi
# A stable source/build path plus prefix maps makes repeat builds practical.
WORK="$WORK_ROOT/work-$TARGET"
LOCK="$WORK_ROOT/lock-$TARGET"
mkdir "$LOCK" || { echo "Another $TARGET build is active; remove stale $LOCK after confirming." >&2; exit 1; }
trap 'rm -f "$TOOLCHAIN"; rmdir "$LOCK"' EXIT
rm -rf "$WORK" "$PREFIX"
mkdir -p "$WORK" "$PREFIX/bin" "$PREFIX/licenses" "$PREFIX/sources" "$PREFIX/recipe"
cp "$TOOLCHAIN" "$PREFIX/toolchain.txt"
cp "$SPEC" "$PREFIX/dependencies.json"
cp "$ROOT/script/ffmpeg/build.sh" "$PREFIX/recipe/"
cp "$ROOT/runtime/ffmpeg/release-key.asc" "$PREFIX/recipe/"
DOWNLOADS="$ROOT/.build-tools/encap-source-downloads"
mkdir -p "$DOWNLOADS"
fetch() {
  local url="$1" digest="$2" dest="$DOWNLOADS/${1##*/}"
  if [[ ! -f "$dest" ]] || [[ "$(sha "$dest")" != "$digest" ]]; then
    curl --fail --location --retry 3 --proto '=https' "$url" -o "$dest.part" >&2
    [[ "$(sha "$dest.part")" == "$digest" ]] || { echo "Source checksum mismatch: $url" >&2; exit 1; }
    mv "$dest.part" "$dest"
  fi
  cp "$dest" "$PREFIX/sources/"
  printf '%s\n' "$dest"
}
extract() { mkdir -p "$WORK/$2"; tar -xf "$1" -C "$WORK/$2" --strip-components=1; }
FFSOURCE="$(fetch "$(jq -b -r .ffmpeg.url "$SPEC")" "$(jq -b -r .ffmpeg.sha256 "$SPEC")")"
curl --fail --location --retry 3 --proto '=https' "$(jq -b -r .ffmpeg.signature "$SPEC")" -o "$PREFIX/sources/${FFSOURCE##*/}.asc" >&2
mkdir "$WORK/gnupg"; chmod 700 "$WORK/gnupg"
gpg --batch --yes --dearmor --output "$WORK/gnupg/release-key.gpg" "$ROOT/runtime/ffmpeg/release-key.asc"
gpgv --homedir "$WORK/gnupg" --keyring "$WORK/gnupg/release-key.gpg" --status-fd 1 "$PREFIX/sources/${FFSOURCE##*/}.asc" "$FFSOURCE" > "$PREFIX/source-verification.txt" 2>&1
grep -F "[GNUPG:] VALIDSIG $(jq -b -r .ffmpeg.signer "$SPEC") " "$PREFIX/source-verification.txt" >/dev/null
extract "$FFSOURCE" ffmpeg
[[ "$(cat "$WORK/ffmpeg/VERSION")" == "$(jq -b -r .ffmpeg.version "$SPEC")" ]]
while IFS=$'\t' read -r name url digest acquisition revision; do
  if [[ "$acquisition" == git-archive ]]; then
    archive="$DOWNLOADS/$name-$revision.tar"
    if [[ ! -f "$archive" ]] || [[ "$(sha "$archive")" != "$digest" ]]; then
      git init --bare "$WORK/$name.git" >&2
      git -C "$WORK/$name.git" fetch --depth=1 "$url" "$revision" >&2
      [[ "$(git -C "$WORK/$name.git" rev-parse FETCH_HEAD)" == "$revision" ]]
      git -C "$WORK/$name.git" archive --format=tar --prefix="$name/" "$revision" > "$archive.part"
      [[ "$(sha "$archive.part")" == "$digest" ]] || { echo "$name Git archive checksum mismatch" >&2; exit 1; }
      mv "$archive.part" "$archive"
    fi
    cp "$archive" "$PREFIX/sources/"
  else
    archive="$(fetch "$url" "$digest")"
  fi
  extract "$archive" "$name"
done < <(jq -b -r '.libraries[] | [.name,.url,.sha256,(.acquisition // "archive"),.version] | @tsv' "$SPEC")
DEPS="$WORK/deps"
mkdir -p "$DEPS"
# Whitespace in a checkout path must not become CFLAGS word splitting.
# Canonicalize build directories with a space-free work-root when needed.
if [[ "$WORK" == *' '* ]]; then echo 'Set ENCAP_FFMPEG_WORK_ROOT to a space-free directory.' >&2; exit 1; fi
export CFLAGS="-O2 -g0 -ffile-prefix-map=$WORK=/encap-build -fdebug-prefix-map=$ROOT=/encap-source"
export CXXFLAGS="$CFLAGS"
export CPPFLAGS="-I$DEPS/include"
export LDFLAGS="-L$DEPS/lib"
# Apple ld reproducible mode stabilizes content-derived UUIDs and signatures.
if [[ "$PLATFORM" == macos ]]; then export LDFLAGS="$LDFLAGS -Wl,-reproducible"; fi
export PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR="$DEPS/lib/pkgconfig"
JOBS="${ENCAP_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN)}"
CMAKE_ARGS=(-G 'Unix Makefiles' -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$DEPS" -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX" -DCMAKE_POLICY_VERSION_MINIMUM=3.5)
if [[ "$PLATFORM" == macos ]]; then CMAKE_ARGS+=(-DCMAKE_OSX_DEPLOYMENT_TARGET=13.0); fi
if [[ "$PLATFORM" == windows ]]; then
  # libc++ headers default to DLL imports on Windows. Static consumers must
  # disable those annotations, including when building the x265 archive.
  export CXXFLAGS="$CXXFLAGS -D_LIBCPP_DISABLE_VISIBILITY_ANNOTATIONS -D_LIBCXXABI_DISABLE_VISIBILITY_ANNOTATIONS"
  export LDFLAGS="$LDFLAGS -static -Wl,--no-insert-timestamp"
  CMAKE_ARGS+=(-DCMAKE_SYSTEM_NAME=Windows)
fi
# Record every effective command, including compiler flags, with the artifacts.
exec 3>&2
exec 2> >(tee "$PREFIX/build.log" >&3)
set -x
(cd "$WORK/zlib"; ./configure --static --prefix="$DEPS"; make -j"$JOBS"; make install) >&2
(cd "$WORK/lame"; ./configure --prefix="$DEPS" --disable-shared --enable-static --disable-frontend --disable-decoder --disable-dependency-tracking; make -j"$JOBS"; make install) >&2
(cd "$WORK/x264"; ./configure --prefix="$DEPS" --enable-static --enable-pic --disable-cli --disable-opencl; make -j"$JOBS"; make install) >&2
cmake -S "$WORK/x265/source" -B "$WORK/x265-build" "${CMAKE_ARGS[@]}" -DENABLE_SHARED=OFF -DENABLE_CLI=OFF -DENABLE_LIBNUMA=OFF -DENABLE_PIC=ON -DENABLE_ASSEMBLY=ON -DENABLE_SVE=OFF -DENABLE_SVE2=OFF >&2
cmake --build "$WORK/x265-build" -j "$JOBS" >&2
cmake --install "$WORK/x265-build" >&2
if [[ "$PLATFORM" == windows ]]; then
  # Validate the static codec's public C ABI before FFmpeg configure. This
  # emits ordinary compiler diagnostics only; no configure log is uploaded.
  printf '#include <x265.h>\nint main(void) { return x265_api_get(8) ? 0 : 1; }\n' > "$WORK/x265-link.c"
  $CC $CFLAGS $CPPFLAGS $(pkg-config --cflags --static x265) -c "$WORK/x265-link.c" -o "$WORK/x265-link.o" >&2
  $CXX $LDFLAGS "$WORK/x265-link.o" $(pkg-config --libs --static x265) -o "$WORK/x265-link.exe" >&2
  "$WORK/x265-link.exe" >&2
fi
OPTIONS=()
while IFS= read -r option; do OPTIONS+=("$option"); done < <(jq -b -r --arg p "$PLATFORM" '.configure[], .platform_configure[$p][]' "$SPEC")
OPTIONS+=("--prefix=$PREFIX" "--cc=$CC" "--cxx=$CXX" '--pkg-config-flags=--static' "--extra-cflags=$CFLAGS $CPPFLAGS" "--extra-ldflags=$LDFLAGS")
# x265 is C++; let the native C++ driver supply its matching runtime libraries.
if [[ "$PLATFORM" == windows ]]; then OPTIONS+=("--ld=$CXX"); fi
if [[ "$PLATFORM" == macos || "$PLATFORM" == windows ]]; then OPTIONS+=(--extra-libs=-lc++); else OPTIONS+=(--extra-libs=-lstdc++); fi
printf '%s\n' "${OPTIONS[@]}" > "$PREFIX/configure.txt"
(cd "$WORK/ffmpeg"; ./configure "${OPTIONS[@]}"; make -j"$JOBS"; make install) >&2
set +x
SUFFIX=; [[ "$PLATFORM" != windows ]] || SUFFIX=.exe
for tool in ffmpeg ffprobe; do
  "$PREFIX/bin/$tool$SUFFIX" -version > "$PREFIX/$tool-version.txt" 2>&1
  grep -F "$tool version $(jq -b -r .ffmpeg.version "$SPEC")" "$PREFIX/$tool-version.txt" >/dev/null
  case "$PLATFORM" in
    macos) otool -L "$PREFIX/bin/$tool" > "$PREFIX/$tool-linkage.txt";;
    linux) ldd "$PREFIX/bin/$tool" > "$PREFIX/$tool-linkage.txt";;
    windows) objdump -p "$PREFIX/bin/$tool.exe" > "$PREFIX/$tool-linkage.txt";;
  esac
  if grep -Ei 'lib(x264|x265|mp3lame|z)\.(so|dylib)|lib(x264|x265|mp3lame|winpthread|stdc\+\+|gcc|c\+\+|unwind|ssp).*\.dll|msys-2.0.dll|/opt/homebrew|/Cellar/' "$PREFIX/$tool-linkage.txt"; then echo 'Unexpected runtime library dependency' >&2; exit 1; fi
done
for name in ffmpeg x264 x265 lame zlib; do
  mkdir -p "$PREFIX/licenses/$name"
  find "$WORK/$name" -maxdepth 1 -type f \( -iname '*copying*' -o -iname '*license*' -o -name README \) -exec cp {} "$PREFIX/licenses/$name/" \;
done
if [[ "$PLATFORM" == windows ]]; then
  # Compiler runtimes are static too; retain their installed license texts.
  mkdir -p "$PREFIX/licenses/toolchain"
  cp -R "$MINGW_PREFIX/share/licenses/." "$PREFIX/licenses/toolchain/"
fi
cp "$WORK/ffmpeg/ffbuild/config.log" "$PREFIX/config.log"
jq -b -n --slurpfile deps "$SPEC" --arg target "$TARGET" --arg key "$KEY" --arg recipe "$RECIPE" --arg ffmpeg "$(sha "$PREFIX/bin/ffmpeg$SUFFIX")" --arg ffprobe "$(sha "$PREFIX/bin/ffprobe$SUFFIX")" \
  '{schema:1,version:$deps[0].ffmpeg.version,target:$target,cache_key:$key,recipe_sha256:$recipe,dependencies:$deps[0],binaries:{ffmpeg:$ffmpeg,ffprobe:$ffprobe}}' > "$PREFIX/runtime.json"
# Corresponding source travels with the runtime; not merely links to upstream.
# Include all evidence except the checksum file itself in cache integrity checks.
(cd "$PREFIX"; find . -type f ! -name files.sha256 ! -name build.log | LC_ALL=C sort | while IFS= read -r file; do shasum -a 256 "$file"; done > files.sha256)
printf '%s\n' "$PREFIX"

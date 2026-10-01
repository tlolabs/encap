#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${1:?architecture}"; STAGE="${2:?application prefix}"; VERSION="${3:?version}"
LABEL=x64
case "$ARCH" in
 x86_64) RUNTIME_HASH=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d; DEPLOY_HASH=c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d; IMAGE_HASH=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 ;;
 aarch64) LABEL=arm64; RUNTIME_HASH=00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444; DEPLOY_HASH=620095110d693282b8ebeb244a95b5e911cf8f65f76c88b4b47d16ae6346fcff; IMAGE_HASH=f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158 ;;
 *) exit 2 ;;
esac
TOOLS="$ROOT_DIR/build/appimage-tools-$ARCH"; APPDIR="$ROOT_DIR/build/EnCap-$ARCH.AppDir"
mkdir -p "$TOOLS"
fetch() { curl --fail --location --retry 3 --proto '=https' --proto-redir '=https' "$1" -o "$2"; printf '%s  %s\n' "$3" "$2" | sha256sum --check; chmod +x "$2"; }
fetch "https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-$ARCH.AppImage" "$TOOLS/linuxdeploy" "$DEPLOY_HASH"
fetch "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-$ARCH.AppImage" "$TOOLS/appimagetool" "$IMAGE_HASH"
fetch "https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-$ARCH" "$TOOLS/runtime" "$RUNTIME_HASH"
rm -rf "$APPDIR"; mkdir -p "$APPDIR"; mkdir -p "$APPDIR/usr"; cp -a "$STAGE/"* "$APPDIR/usr/"
export APPIMAGE_EXTRACT_AND_RUN=1 NO_STRIP=1
export PATH="$TOOLS:$PATH"
DESKTOP="$(find "$APPDIR/usr/share/applications" -name '*.desktop' -print -quit)"
# The verified FFmpeg pair only links system libraries. Keep it out of
# linuxdeploy's ELF rewriting, then restore the exact source-built bytes.
rm "$APPDIR/usr/bin/ffmpeg" "$APPDIR/usr/bin/ffprobe"
# .NET's optional LTTng provider targets the 2.12 ABI, unavailable on Ubuntu 24.
# It is loaded only for opt-in tracing. Preserve it unchanged for compatible
# hosts, but do not ask linuxdeploy to resolve optional tracing prerequisites.
# https://learn.microsoft.com/dotnet/core/diagnostics/trace-perfcollect-lttng
TRACE_PROVIDER=libcoreclrtraceptprovider.so
if [[ -f "$APPDIR/usr/bin/$TRACE_PROVIDER" ]]; then rm "$APPDIR/usr/bin/$TRACE_PROVIDER"; fi
# GLib/GIO remains a system dependency, as documented, rather than copying the
# runner's desktop-integration stack into the self-contained application.
SYSTEM_INTEGRATION=()
# linuxdeploy flattens ldd output, so exclude GLib's transitive OS libraries too.
for pattern in 'libgio-2.0.so*' 'libgobject-2.0.so*' 'libglib-2.0.so*' 'libgmodule-2.0.so*' 'libmount.so*' 'libblkid.so*' 'libselinux.so*' 'libffi.so*' 'libpcre2-*.so*'; do
  SYSTEM_INTEGRATION+=(--exclude-library "$pattern")
done
linuxdeploy "${SYSTEM_INTEGRATION[@]}" --appdir "$APPDIR" --executable "$APPDIR/usr/bin/EnCap" --desktop-file "$DESKTOP" --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/$(basename "$DESKTOP" .desktop).png"
cp -p "$STAGE/bin/ffmpeg" "$STAGE/bin/ffprobe" "$APPDIR/usr/bin/"
if [[ -f "$STAGE/bin/$TRACE_PROVIDER" ]]; then cp -p "$STAGE/bin/$TRACE_PROVIDER" "$APPDIR/usr/bin/"; fi
# Retain distro license texts referenced by copied dependency copyright files.
mkdir -p "$APPDIR/usr/share/common-licenses"
cp -a /usr/share/common-licenses/. "$APPDIR/usr/share/common-licenses/"
# linuxdeploy-generated AppRun supplies the relocatable runtime environment.
ARCH="$ARCH" "$TOOLS/appimagetool" --runtime-file "$TOOLS/runtime" "$APPDIR" "$ROOT_DIR/dist/release/EnCap-$VERSION-linux-$LABEL.AppImage"
python3 "$ROOT_DIR/script/ffmpeg_runtime.py" validate "linux-${ARCH/aarch64/arm64}" --binary "$APPDIR/usr/bin" --metadata "$APPDIR/usr/bin/ffmpeg-runtime"

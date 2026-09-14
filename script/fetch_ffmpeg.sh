#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:?usage: fetch_ffmpeg.sh <macos|linux|windows> <x86_64|aarch64> <destination>}"
ARCH="${2:?usage: fetch_ffmpeg.sh <macos|linux|windows> <x86_64|aarch64> <destination>}"
DESTINATION="${3:?usage: fetch_ffmpeg.sh <macos|linux|windows> <x86_64|aarch64> <destination>}"
RELEASE="autobuild-2026-09-11-13-20"
BUILD="n9.0.1-29-gad500d59cb"

verify_sha256() {
  local expected="$1"
  local archive="$2"
  local actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "${archive}" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "${archive}" | awk '{print $1}')"
  fi
  [[ "${actual}" == "${expected}" ]]
}

if [[ "${PLATFORM}" == "macos" ]]; then
  case "${ARCH}" in
    x86_64)
      BASE_URL="https://ffmpeg.martin-riedl.de/download/macos/amd64/1787081194_9.0.1"
      FFMPEG_SHA256="5bdead62ff504ab9b447cc72b212c4fb481e3f7de5877d427a51bee8136dda40"
      FFPROBE_SHA256="34511bbcf1988ad2886023bf5ace4f44cf62e6defeb3d194d6f7619e5b061f7f"
      ;;
    arm64|aarch64)
      BASE_URL="https://ffmpeg.martin-riedl.de/download/macos/arm64/1787073674_9.0.1"
      FFMPEG_SHA256="8287a1b2229e05eb41859f073e18e6c52c60a778f2f5e6881070fe51b79407fe"
      FFPROBE_SHA256="102a26b8940a053298d9929bfaae71e4b6ef65ba5f19a99a88c433108560741a"
      ;;
    *) echo "unsupported FFmpeg target: ${PLATFORM}:${ARCH}" >&2; exit 2 ;;
  esac
  WORK_DIR="$(mktemp -d)"
  trap 'rm -rf "${WORK_DIR}"' EXIT
  curl --fail --location --retry 3 --proto '=https' --proto-redir '=https' --output "${WORK_DIR}/ffmpeg.zip" "${BASE_URL}/ffmpeg.zip"
  curl --fail --location --retry 3 --proto '=https' --proto-redir '=https' --output "${WORK_DIR}/ffprobe.zip" "${BASE_URL}/ffprobe.zip"
  verify_sha256 "${FFMPEG_SHA256}" "${WORK_DIR}/ffmpeg.zip"
  verify_sha256 "${FFPROBE_SHA256}" "${WORK_DIR}/ffprobe.zip"
  mkdir -p "${WORK_DIR}/ffmpeg" "${WORK_DIR}/ffprobe" "${DESTINATION}"
  unzip -q "${WORK_DIR}/ffmpeg.zip" -d "${WORK_DIR}/ffmpeg"
  unzip -q "${WORK_DIR}/ffprobe.zip" -d "${WORK_DIR}/ffprobe"
  cp "${WORK_DIR}/ffmpeg/ffmpeg" "${DESTINATION}/ffmpeg"
  cp "${WORK_DIR}/ffprobe/ffprobe" "${DESTINATION}/ffprobe"
  chmod +x "${DESTINATION}/ffmpeg" "${DESTINATION}/ffprobe"
  "${DESTINATION}/ffmpeg" -version | head -n 1 | grep -F "ffmpeg version 9.0.1"
  exit 0
fi

case "${PLATFORM}:${ARCH}" in
  windows:x86_64) ASSET="ffmpeg-${BUILD}-win64-gpl-9.0.zip"; SHA256="af971817c209439bb0374b5e623aca894042aa435426217d0dd5cfd15fb69d1b" ;;
  windows:aarch64) ASSET="ffmpeg-${BUILD}-winarm64-gpl-9.0.zip"; SHA256="8961216fe1fea620fefe893ae8b00f215b3351c3baa7705f7855d61c968296b1" ;;
  linux:x86_64) ASSET="ffmpeg-${BUILD}-linux64-gpl-9.0.tar.xz"; SHA256="2bb135a418f23049e7e2321f95a731cbb45f68bbc5b2d2fc78e8a4c1e4cfa54d" ;;
  linux:aarch64) ASSET="ffmpeg-${BUILD}-linuxarm64-gpl-9.0.tar.xz"; SHA256="64d40fb6708eeaecdb68907d67c54227d5e772db9458fd8fd2d12515d9dcc743" ;;
  *) echo "unsupported FFmpeg target: ${PLATFORM}:${ARCH}" >&2; exit 2 ;;
esac

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT
ARCHIVE="${WORK_DIR}/${ASSET}"
URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/${RELEASE}/${ASSET}"

curl --fail --location --retry 3 --proto '=https' --proto-redir '=https' --output "${ARCHIVE}" "${URL}"
verify_sha256 "${SHA256}" "${ARCHIVE}"

mkdir -p "${WORK_DIR}/unpacked" "${DESTINATION}"
if [[ "${ASSET}" == *.zip ]]; then
  unzip -q "${ARCHIVE}" -d "${WORK_DIR}/unpacked"
  SUFFIX=".exe"
else
  tar -xJf "${ARCHIVE}" -C "${WORK_DIR}/unpacked"
  SUFFIX=""
fi

FFMPEG_SOURCE="$(find "${WORK_DIR}/unpacked" -type f -path "*/bin/ffmpeg${SUFFIX}" -print -quit)"
FFPROBE_SOURCE="$(find "${WORK_DIR}/unpacked" -type f -path "*/bin/ffprobe${SUFFIX}" -print -quit)"
[[ -n "${FFMPEG_SOURCE}" && -n "${FFPROBE_SOURCE}" ]]
cp "${FFMPEG_SOURCE}" "${DESTINATION}/ffmpeg${SUFFIX}"
cp "${FFPROBE_SOURCE}" "${DESTINATION}/ffprobe${SUFFIX}"
chmod +x "${DESTINATION}/ffmpeg${SUFFIX}" "${DESTINATION}/ffprobe${SUFFIX}"

LICENSE_SOURCE="$(find "${WORK_DIR}/unpacked" -type f \( -iname 'LICENSE.txt' -o -iname 'COPYING.GPLv3' -o -iname 'COPYING.GPLv2' \) -print -quit)"
if [[ -n "${LICENSE_SOURCE}" ]]; then cp "${LICENSE_SOURCE}" "${DESTINATION}/FFMPEG_LICENSE.txt"; fi
"${DESTINATION}/ffmpeg${SUFFIX}" -version | head -n 1

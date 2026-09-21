#!/usr/bin/env bash
# Diagnostic only: fresh synthetic inputs; never reads application logs.
# The normal packaged-engine media contract remains the acceptance gate.
set -euo pipefail
FF="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
TEMP="$(mktemp -d)"; trap 'rm -rf "$TEMP"' EXIT
"$FF" -v error -f lavfi -i testsrc2=size=160x160 -frames:v 1 "$TEMP/image.ppm"
"$FF" -v error -f lavfi -i sine=duration=1 "$TEMP/audio.wav"
GRAPH='[0:v]hflip,vflip,split=2[bgsrc0][fgsrc0];[bgsrc0]scale=90:160:force_original_aspect_ratio=increase,crop=90:160,gblur=sigma=20[bg0];[fgsrc0]scale=90:90:force_original_aspect_ratio=decrease,pad=90:90:(ow-iw)/2:(oh-ih)/2[fg0];[bg0][fg0]overlay=(W-w)/2:(H-h)/2,trim=duration=1,setpts=PTS-STARTPTS,format=yuv420p[v0];[1:a:0]atrim=duration=1,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a0];[v0][a0]concat=n=1:v=1:a=1[outv][outa]'
INPUT=(-loop 1 -framerate 60 -t 1 -i "$TEMP/image.ppm" -t 1 -i "$TEMP/audio.wav" -filter_complex "$GRAPH" -map '[outv]' -map '[outa]')
ENCODE=(-c:v libx264 -tune stillimage -pix_fmt yuv420p -r 60 -c:a aac -b:a 192k -shortest -f mp4 "$TEMP/out.mp4")
failures=0
probe() {
  local name="$1"; shift
  local status=0
  "$FF" -nostdin -hide_banner -loglevel warning -y "$@" || status=$?
  printf 'SYNTHETIC_RESULT %s exit=%s\n' "$name" "$status"
  if [[ "$status" != 0 ]]; then failures=$((failures + 1)); fi
}
probe normal "${INPUT[@]}" "${ENCODE[@]}"
probe x264-scalar "${INPUT[@]}" -x264-params asm=0 "${ENCODE[@]}"
probe both-scalar -cpuflags 0 "${INPUT[@]}" -x264-params asm=0 "${ENCODE[@]}"
probe filter-threads-one -filter_complex_threads 1 "${INPUT[@]}" "${ENCODE[@]}"
probe x264-threads-one "${INPUT[@]}" -threads:v 1 "${ENCODE[@]}"
probe graph-without-x264 "${INPUT[@]}" -c:v rawvideo -c:a pcm_s16le -f null -
probe simple-x264 -f lavfi -i testsrc2=size=90x160:rate=60:duration=1 -c:v libx264 -f null -
probe simple-x264-scalar -f lavfi -i testsrc2=size=90x160:rate=60:duration=1 -c:v libx264 -x264-params asm=0 -f null -
probe blur-only -f lavfi -i testsrc2=size=90x160:rate=60:duration=1 -vf gblur=sigma=20 -c:v rawvideo -f null -
printf 'SYNTHETIC_SUMMARY failures=%s\n' "$failures"
[[ "$failures" == 0 ]]

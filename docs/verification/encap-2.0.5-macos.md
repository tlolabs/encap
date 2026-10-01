# EnCAP 2.0.5 macOS ARM64 verification

Verified September 30, 2026 on the local Apple-silicon Mac.

## Runtime ownership

EnCAP consumes AVID Core 0.3.0 at
`25d19098a22936638b0e2a70616083d929fe409c`. The bundled FFmpeg/FFprobe pair
comes from published Core runtime `ffmpeg-9.0.1-r7.1`, promotion revision
`2e137df692aa612e0dd62ebd93b5fff26c61663a`. The release manifest SHA-256 is
`ef7eb4e2b62f656aa3cb6808dc2d227eb035be2050367d596e1f79a6d6d45779`.
Core owns source builds, codec configuration and runtime verification.
EnCAP downloads the release through Core's unchanged pinned acquisition script;
no FFmpeg source compilation or sibling Core checkout is needed.

## Results

- `bash script/build_and_run.sh --verify`: passed; app built and launch verified.
- Five packaged Audio, Transcript and Video media contracts: passed.
- Runtime identity, package relocation, missing/damaged metadata and binary
  rejection, and no PATH fallback: passed.
- Packaged save and audio-edit protocol tests, including the unchanged save
  latency limits: passed.
- Native Swift suite: 26 tests passed.
- `cargo fmt --all --check`: passed.
- `cargo clippy --workspace --all-targets --locked -- -D warnings`: passed.
- `cargo test --workspace --locked`: 50 tests passed; 6 ignored in the
  default suite. The five ignored packaged media tests ran separately above.
- `python3 script/test_runtime_ownership.py`: two tests passed.
- `bash script/check_no_python.sh`: passed.

The local app is `dist/EnCap.app`; the ZIP is
`dist/EnCap-2.0.5-macos-arm64.zip` (SHA-256 `ffce0062b6c4ab632a222f0e6fea019968a05fe8475307d1661f2caf640e31cc`).
The app has local ad-hoc code signatures. This is a local build, not a newly
notarized or published end-user release. Other platforms have updated version
metadata and pinned Core runtime assets but were not rebuilt in this run.

Local logs (ignored build outputs):

- `build/core-release-2.0.5-macos-arm64.log`
- `build/core-release-2.0.5-clippy.log`
- `build/core-release-2.0.5-tests.log`

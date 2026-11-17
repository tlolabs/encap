# Helper verification record

Integration run: November 3, 2026 UTC (host local date November 2). Host:
Apple silicon, macOS 27.2, Xcode 27.2, Swift 6.4.2. These checks establish
behavior on this host; they do not qualify minimum macOS, Intel, Windows, Linux,
or every model/language.

The frozen Core packages and their dependency pins were used without source
modification. The helper's seven Swift Testing checks passed with:

```sh
env TMPDIR=/tmp/encap-avid-tmp \
  CLANG_MODULE_CACHE_PATH=/tmp/encap-avid-clang-cache \
  SWIFTPM_MODULECACHE_OVERRIDE=/tmp/encap-avid-module-cache \
  swift test --package-path helpers/avid_transcriber \
  --scratch-path /tmp/encap-avid-helper-build --build-system swiftbuild \
  --disable-sandbox --skip-update --force-resolved-versions -j 6
```

The checks cover snake_case roundtrip, source times and independent provenance,
full-manifest/source identities, preservation of pre-alignment recognition,
untimed text without invented words, malformed timing rejection, literal path
arguments and invalid options, language-capability validation, shared catalog
metadata, SRT/WebVTT grouping, and rejection of captions without word alignment.

Native functional checks used the debug product plus its adjacent resource
bundles. They used the previously verified models in
`/tmp/desktop-transcription-20261102-e8b98234/models` and the 5.511-second
`speech.m4a` fixture from that task. No new models were downloaded.

| Check | Result |
| --- | --- |
| `models` against existing cache | JSON array; no stdout diagnostic contamination |
| Missing input | Nonzero exit and one JSON error |
| Parakeet v3, English | 17 native-timed words; expected sample text |
| Full Whisper large-v3, `EN_us`, source offset 12.5 | Language `en`; 17 words at approximately 12.52–17.62; full model/source identity |
| Qwen3-ASR plus separate forced aligner, `EN_us`, offset 12.5 | Language `en`; 17 aligned words at 12.50–17.86; original untimed recognition retained separately; independent model/source identities |
| Corrected-text Qwen realignment, offset 12.5 | Edited punctuation/text retained exactly; 17 newly aligned words; original recognition identity unchanged |
| Core WebVTT export from aligned record | Four subtitle cues; first cue starts 12.500; recognition file unchanged |
| SIGTERM after verification starts | Exit 130 and one JSON cancellation error in approximately 0.003 seconds; no callback-isolation warning |
| Original parent terminated | Own operation cancelled and returned JSON cancellation error after approximately 1.53 seconds; temporary Qwen staging removed |

The signal/watchdog smoke initially exposed main-actor callback warnings.
Explicit `@Sendable` callbacks fixed them; the repeated cancellation, parent
death, and inference checks emitted no such warning. Parent-death cancellation
was tested during verification/loading, not during the longest possible Metal
kernel. Kernel cancellation latency is still bounded by the active backend work.

The initial fresh dependency resolution could not reach GitHub under the task
sandbox. Exact pinned dependencies were reused from the reviewed Core build
cache. Sandboxed compiler/native inference attempts also encountered unavailable
Metal toolchain/GPU access; the successful native checks used the approved host
toolchain execution environment. These environment failures are not counted as
passing checks. The initial sandbox parent-death run aborted before producing
JSON because MLX could not access a Metal device; its successful native repeat
is the result recorded above.

Captured command output and result JSON are under
`/tmp/encap-avid-helper-*.json`, `*.stderr`, and
`/tmp/encap-avid-helper-build.log`. The top-level integration report owns packaged
application qualification and independent review. These short synthesized
English samples are functional smoke checks, not an accuracy, multilingual,
performance, or memory benchmark. Turbo inference and broad language coverage
remain unrun here.

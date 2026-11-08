# AVID local transcription for Mac

Two additive Swift packages provide local transcription without changing the Rust
crate, its desktop media runtime, or its immutable FFmpeg release contract:

- **AVIDTranscription**: model catalog, verified direct downloads, shared transcript
  types, provider protocols, caption grouping, and SRT/WebVTT export. Swift 6.0+,
  macOS 14+, no third-party package dependencies.
- **AVIDTranscriptionEngines**: WhisperKit, FluidAudio Parakeet, and MLX Qwen ASR /
  forced-alignment adapters plus `avid-transcribe`. Apple silicon, macOS 14+,
  Swift 6.3+ and the Xcode Metal toolchain. Upstream dependencies are pinned to
  immutable revisions; commit `Package.resolved` when changing them.

Phones and iPads are deferred. These packages do not add UI, modify app project
formats, or burn animated captions into AVID Core exports. A host renders timed
words separately; SRT/WebVTT exports are ordinary caption cues, not animation.

## Models come from upstream

The bundled [catalog](AVIDTranscription/Sources/AVIDTranscription/Resources/models.json)
contains exact public Hugging Face revisions, files, byte counts, SHA-256 digests,
recognition languages, timing languages, and license notices. The default model
is **full Whisper large-v3** (~3.1 GB); Turbo (~1.6 GB), Parakeet (~632 MB), Qwen3-ASR
1.7B 4-bit (~1.6 GB), and Qwen3-ForcedAligner (~976 MB) are selectable. Download size
is not peak runtime memory or a guarantee of relative accuracy.

Models download anonymously from Argmax, FluidInference, and MLX Community
repositories on Hugging Face, including their HTTPS storage redirects. No AVID
server, account, API key, hosted inference, or audio upload is involved. After
installation, the inference adapters use local files only. Whisper's separately
pinned tokenizer assets are included to prevent an implicit tokenizer download.

The default cache is `~/Library/Application Support/AVID/Transcription/Models`.
Installations are identified by the primary revision plus a digest of the complete
manifest, so independently updated tokenizer pins cannot collide. Incomplete
files are kept outside published installations and resumed with HTTP Range.
Every artifact is size- and SHA-256-checked before publication; hash failures are
reported rather than accepted. Model operations use per-model OS locks shared by
all hosts. Cached models still work when upstream is unavailable. Installation of
an uncached model requires access to upstream; public availability is not an AVID
service guarantee.

See [model notices](AVIDTranscription/MODEL_NOTICES.md) and
[engine notices](AVIDTranscriptionEngines/THIRD_PARTY_NOTICES.md). SDK licenses and
model licenses are tracked separately; free distribution still requires the
applicable attribution/notices.

## Commands

Run from the repository root:

```sh
swift run --package-path apple/AVIDTranscription avid-transcription models
swift run --package-path apple/AVIDTranscription avid-transcription install whisper-large-v3
swift run --package-path apple/AVIDTranscription avid-transcription verify whisper-large-v3

swift run --package-path apple/AVIDTranscriptionEngines avid-transcribe transcribe \
  recording.m4a transcript.json --model whisper-large-v3 --offline
swift run --package-path apple/AVIDTranscription avid-transcription captions transcript.json captions.srt
```

`avid-transcribe` installs the selected model when needed unless `--offline` is
set. `--language en` fixes the language instead of autodetection. Regional tags such
as `pt-BR` and `pt_BR` normalize to the supported base language; unsupported
explicit languages fail before model loading. Select
`--model whisper-large-v3-turbo`, `parakeet-tdt-v3`, or `qwen3-asr-1.7b-4bit` to change
the engine. Qwen recognition returns untimed text; add
`--align-model qwen3-forced-aligner-0.6b-4bit` to obtain supported word timings.

Text edits invalidate affected word alignment. Realign an edited JSON transcript
without recognizing its words again:

```sh
swift run --package-path apple/AVIDTranscriptionEngines avid-transcribe align \
  recording.m4a edited.json aligned.json --language en --offline
```

Qwen alignment supports Chinese, English, Cantonese, French, German, Italian,
Japanese, Korean, Portuguese, Russian, and Spanish. Recognition support is broader;
recognition alone does not imply timed-caption support. Alignment never silently
uses an unsupported language. Longer material is segmented for bounded model
windows; do not interpret numeric timestamp precision as verified acoustic accuracy.

Model commands accept `--cache DIRECTORY`. Use `import MODEL DIRECTORY` to import
an exact catalog-compatible local folder, or `--local-model DIRECTORY` during
transcription. Files are verified and only listed artifacts are copied into the
managed cache; unlisted local weight shards are not loaded. There is no network
fallback for missing local files. `remove MODEL` removes managed revisions and
partial downloads, not the original manual source. Ctrl-C cancels an operation;
a running Core ML / Metal kernel may complete before cancellation is observed.

The inference command writes a new JSON file and will not overwrite existing
transcripts. `--source-offset SECONDS` records an extracted clip's original source
position. Caption windows map original-source word times through trims and timeline
offsets; cue grouping and styling do not modify the recognition record. Delayed
audio tracks retain their initial silence. Decoded discontinuous or invalid audio
timestamps are rejected; export such a source to continuous audio before retrying.

## Host integration

Add local package dependencies from a pinned AVID Core source checkout. This Rust
monorepo has no root `Package.swift`, so SwiftPM cannot consume these subdirectories
as direct Git package URLs. Host dependency acquisition should pin the source
revision, keep both packages in the same checkout, and reference their local paths:

```swift
.package(path: "Vendor/avid-core/apple/AVIDTranscription"),
.package(path: "Vendor/avid-core/apple/AVIDTranscriptionEngines")
```

Import `AVIDTranscription` for the contract and `AVIDTranscriptionEngines` for providers.
All heavy work belongs off the UI thread. Forward progress callbacks to your UI,
and cancel the owning Swift task for cancellation. A host should offer models,
download size/progress, verification errors, and removal using `ModelStore`.

```swift
let catalog = try ModelCatalog.bundled()
let store = try ModelStore(catalog: catalog)
_ = try await store.install(id: catalog.defaultModelID) { progress in
    // Forward this Sendable value to the UI; keep the callback short.
}
let transcript = try await store.withInstalledModel(id: catalog.defaultModelID) { installed in
    try await WhisperKitProvider().transcribe(
        RecognitionRequest(audioURL: audioURL, modelID: installed.descriptor.id,
                           modelDirectory: installed.directory)
    ) { progress in
        // Forward transcription progress to the UI.
    }
}
let cues = try CaptionBuilder.cues(from: transcript)
let subtitles = try CaptionExporter.webVTT(cues)
```

Use `withInstalledModel` around loading, inference and unload so concurrent model
removal fails with `busy` while weights may still be mapped. `installedModel`
verifies and returns a snapshot but does not lease it after return. The adapters
release their model state before returning; do not keep a backend outside a scoped
operation. Requests passed directly to adapters must refer to a verified installation.

`Transcript`, `TranscriptSegment`, and `TranscriptWord` are Codable/Sendable.
Words keep original-source start/end seconds, optional confidence, and timing
provenance. Recognition and alignment model IDs are preserved independently.
Untimed text remains valid transcript data; attempting to generate word captions
from it fails explicitly. Missing word boundaries are never evenly interpolated.

See [recorded verification and its limits](VERIFICATION.md).

## Checks and catalog maintenance

```sh
swift test --package-path apple/AVIDTranscription
swift test --package-path apple/AVIDTranscriptionEngines
python3 script/test_transcription_catalog.py
python3 script/update_transcription_catalog.py --check
python3 script/update_transcription_catalog.py --verify-upstream
```

Core tests exercise integrity, resumable downloads, cancellation, shared-cache
locking, offline/manual provisioning, timestamp validation, Unicode grouping,
source offsets, trims, and subtitle export without downloading model weights.
Adapter contract tests exercise decoding and local-file constraints. Full inference
and accuracy require installed models and a representative language/media corpus;
synthetic tests are not accuracy benchmarks. If Xcode lacks `metal`, install the
Apple component with `xcodebuild -downloadComponent MetalToolchain`.

Catalog refreshes use the fixed publisher allowlist and immutable pins in
`script/update_transcription_catalog.py`. Update the pins deliberately, regenerate,
review notices and capabilities, and rerun the offline/upstream checks. Metadata
and small tokenizer/config files are fetched to derive/verify the manifest;
multi-gigabyte weight files are not downloaded by the catalog generator. Checks
remain diagnostic under repository policy, not release/merge approval gates.

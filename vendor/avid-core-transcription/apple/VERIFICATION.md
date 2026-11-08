# Transcription verification

Recorded on November 2, 2026 on an Apple silicon Mac using Apple Swift 6.4.2 / Xcode
27.2 with the Apple Metal toolchain installed. These are diagnostics, not required
CI status checks or downstream application qualification.

## Automated checks

- Core package: 24 passing XCTest tests, including actual URLSession delegate
  fixtures for HTTP resume, Range rejection, HTTP 200 restart, cancellation,
  oversized/truncated responses, corrupt artifacts, offline cache/import,
  cross-store locks, timestamp validation, Unicode grouping, trims and SRT/VTT.
- Engine package: 14 passing contract tests, including real AVFoundation stereo
  resampling, a delayed-audio MOV preserving its initial silence, independent
  recognition/alignment languages, preservation of edited
  punctuation, missing local models, exclusion of unlisted weight shards, regional
  language normalization, explicit automatic detection, and awaited cleanup on
  success, error, and cancellation; normalized Qwen output language and
  recognition/alignment provenance preservation.
- Catalog: 7 passing offline Python tests; bundled manifest validation passed.
  Upstream verification matched pinned metadata and small-file Git identities.

## Actual model execution

The new downloader installed and SHA-256-verified the full published artifacts
for Parakeet v3, Whisper large-v3, Qwen3-ASR 1.7B 4-bit, and the Qwen3 0.6B aligner.
No model weights are stored in this Git repository. Tests used a temporary cache.
Inference commands ran in `--offline` mode against those installed local files.

The fixture was a 5.511-second locally synthesized English recording:

> Hello. This is a local transcription test. Every word should have a start and an end time.

| Backend | Result |
| --- | --- |
| Parakeet v3 | 17 expected words, ordered native word times, 0.00–5.36 seconds; punctuation differs |
| Qwen3-ASR plus forced aligner | 17 expected words with original punctuation, ordered forced-alignment times, 0.00–5.28 seconds; separate recognition/alignment provenance retained |
| Whisper large-v3 | 17 expected timed words, ordered native times, approximately 0.02–5.12 seconds |

The Parakeet transcript exported successfully to three SRT cues; JSON retained the
individual word records. Core tests additionally check WebVTT and timeline mapping.
An additional real AAC inference check retained a 12.5-second source offset;
Qwen alignment also retained that offset without applying it twice.
Qwen's generated tokenizer file was confined to a temporary working directory;
the verified model installation was unchanged.

Final real-model checks additionally passed for regional `EN_us` input on Whisper
and Parakeet, automatic language detection on Whisper and Qwen, and automatic
Qwen alignment-language selection. These all returned English with 17 timed words.
A final real alignment check started with a transcript lacking language metadata,
used explicit `EN_us`, and returned normalized `en` with original text, all 17 word
times, and both recognition and alignment provenance preserved.

## Limits

These smoke tests demonstrate file installation, local loading, real recognition,
word timing, and caption export. They do not measure general transcription
accuracy, acoustic boundary error, multilingual quality, peak memory, long-form
accuracy, or comparative throughput. No manually timed acoustic ground truth was
used. The Turbo entry's immutable catalog artifacts were verified from upstream
metadata, but its weights were not installed or executed in these checks.

No iPhone/iPad inference or downstream ATIV/EnCAP UI integration was tested.
Caption styling and animated burn-in remain host/rendering work. Installing
uncached models remains dependent on the public upstream repositories.

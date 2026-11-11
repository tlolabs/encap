# AVID Core transcription integration and migration

This change replaces EnCAP's application-owned transcription stack with a thin
process adapter to AVID Core. Implementation task:
`encap-avid-integration-20261103`; baseline
`2c20da6c6499484c1141c3902d03c9f6afcefba2` (2.0.9).
Pre-existing audio, persistence, source-removal, Qt, update-test and qualification
edits were recorded before implementation and retained. No release publication,
push, platform-support removal, or shared sibling-checkout mutation is authorized
by this task.

## Dependency ownership and acquisition

EnCAP 2.0.10 refreshes the 34-file Swift snapshot from the published AVID Core
`v0.3.2` Git commit `8296a9e623c6924c12e456b5fe9e7c10b59dfbde`.
The deterministic archive has SHA-256
`a302200860bde5c47cd4aeabacefedefa30e6112248302925164589ce9f45937`.
Core 0.3.3 makes no changes under `apple/` relative to 0.3.2, so this
independently pinned Swift snapshot remains valid and unchanged.
The archive, manifest and unmodified source remain under `vendor/`;
`ruby script/verify_avid_snapshot.rb` verifies them before builds. Both original
Swift packages remain siblings under `vendor/avid-core-transcription/apple`.
`Package.resolved` retains the exact SDK dependencies. The manifest identifies
published source provenance; it does not transfer an earlier export's review
claims to this refreshed archive. The original integration history below remains
applicable unless superseded by the 2.0.10 release notes.

AVID Core owns catalog identities, artifact hashes/sizes, anonymous public model
downloads, resumption, imports, shared-cache locking, verification, scoped model
leases, inference, forced alignment, and caption grouping. EnCAP owns the typed
JSON sidecar (`helpers/avid_transcriber`), Rust adapter, user interface, editable
project projection, persistence and protected output routing. The independent
Rust `avid-core =0.3.3` and authenticated FFmpeg runtime pins remain separate.

The helper returns one snake_case JSON value on stdout; errors use a nonzero
exit and `{"error":"..."}`. SDK output is redirected to stderr, alongside
structured progress events. Rust owns and reaps the child, drains diagnostics,
and uses private operation files. Cancellation requests cooperative Swift task
cleanup; a running Metal/Core ML kernel can delay observation, so the host also
has a bounded grace period before terminating its owned helper. Previous project
state is applied only after successful complete output.

## Legacy removal and existing models

The old Apple Speech helper/permission, EnCAP WhisperKit wrapper, whisper.cpp
build/staging, GGML catalog/download/verification, fallback discovery, and
Superwhisper/MacWhisper scans are removed from the executable path. New shared
WhisperKit usage is provided by Core, not the deleted wrapper.

No migration deletes old EnCAP model files, verification files, third-party
caches, manual source directories, or project media. `ENCAP_MODEL_DIR` and old
verification-cache overrides no longer select an inference backend. Legacy GGML
`.bin` files are incompatible with the new manifests and require replacement
downloads. Exact compatible Core ML/MLX folders can be imported through the
shared verified store; removal deletes the managed installation, not its import
source. Old ignored build caches can remain on disk without becoming runtime
dependencies.

The default shared cache is
`~/Library/Application Support/AVID/Transcription/Models`. Models install only
through explicit acquisition/import, and inference uses local verified files.
There is no account/API key requirement or audio-upload path. Installed models
remain usable while upstream is unavailable. The full Whisper large-v3 is the
quality default; Turbo, Parakeet, Qwen recognition and separate Qwen alignment
retain their actual catalog sizes, languages and licenses. Recognition language
support does not imply alignment-language support.

## Project data, timing and editing

Schema-1/2 archive migration, opaque compatibility data, unknown extensions,
source media, stable segment/word IDs and manual speakers remain EnCAP data.
The project model is not replaced by Core's Codable contract. Opening/saving an
old transcript does not transcribe it again or rewrite its text.

New `avid_source_id` and segment `avid_core` extensions describe source identity,
immutable recognition/alignment records and reversible source-to-episode timing.
See [the project-format extension](project-format.md#avid-transcription-extensions).
Core source-clock timings are projected into the assembled episode exactly once;
source removal adjusts projected times while retaining the original record.
Untimed text is valid and visible, but cannot be exported as timed subtitles or
word captions. No evenly spaced word times are invented. Editing segment text
clears its word alignment; forced realignment uses the edited text while retaining
host IDs and speakers. A legacy transcript without reliable source provenance
must be rerecognized before automatic realignment can safely map it to audio.

Rerecognition matches identities using source, text and timing rather than segment
position. Ambiguous prior records are retained once in `previous_transcript`;
both clients display a persisted warning when manual speakers need review.
Realignment retains initial recognition separately from the latest alignment.
Each model provenance carries the complete shared manifest installation identity
and immutable SDK snapshot identity.
New imports use per-instance UUID identities, so reopening an archive and adding
the original file again cannot make the two instances share transcript identity.
Retained source-linked segments survive adjacent-source removal even if native
timing slightly overshoots; only projected bounds are clipped to playable media.
History follows a surviving carrier, or falls back to optional project-level
storage when retained audio has no active segment. Removing all audio clears
transcript/history explicitly.

TXT preserves the existing project projection. On supported helper platforms,
ordinary SRT and WebVTT formatting uses Core `CaptionExporter` with existing
segment boundaries and speaker labels. Core escapes markup, folds embedded
newlines, validates ordered positive-duration cues and rounds timestamps; these
are intentional export differences, without rewriting saved transcript records.
Other targets retain the existing SRT writer pending a portable Core exporter.
The small ordinary-WebVTT addition is available through
`encap-engine export-transcript PAYLOAD OUTPUT vtt`; ordinary segment export
does not require word timing, model installation or inference. Existing word-caption
SRT/WebVTT actions remain in both clients; no new ordinary-WebVTT UI is claimed.
Errors from an available Core helper never select the legacy writer. Shared
word-caption output requires actual usable word timings. Subtitle files do not
implement animated or burned-in social captions; no such renderer is claimed.

## Platform decision still required

The base app continues targeting macOS 13; Qt target configurations remain.
The new helper requires Apple silicon, macOS 14+, Swift 6.3+ and the Metal
toolchain. Intel Mac, macOS 13, Windows x64/ARM64 and Linux x64/ARM64 currently
have no qualified new inference backend. Their saved transcript editing/export
and ordinary Audio/Video paths remain independent.

The owner must decide whether those targets may ship with transcription
unavailable, or whether shared Core inference parity must be completed first.
That decision is pending. Removing legacy executable logic does not establish
replacement parity. Builds/tests remain diagnostic; only independently verified
functional target artifacts can publish. An unsupported or unverified artifact
must not be advertised as a complete transcription replacement.

## Verification record

Detailed commands, outcomes, independent-review results, and remaining unrun
checks are recorded in [the verification report](verification/transcription-avid-core.md).
Core's earlier 45-test clean review concerns the upstream source, not this app's
integration. EnCAP requires its own tests, real packaged inference and independent
review. Short synthesized speech runs are functional smoke tests, not an accuracy
benchmark or a minimum-OS qualification.

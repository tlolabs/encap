# Native application architecture

```text
SwiftUI/AppKit (production macOS) ----------> encap-engine (one JSON response)
Qt 6 Widgets (Windows/Linux/internal Mac) --> |
                        |-- encap-core: project model and ZIP persistence
                        |-- encap-audio -> encap-ffmpeg
                        |-- encap-transcript -> avid-transcriber JSON sidecar
                        |                         `-- AVIDTranscription / Engines
                        `-- encap-video adapter -> avid-core -> FFmpeg/ffprobe

All modes resolve the same Core-built FFmpeg/ffprobe pair.
```

`encap-core` contains platform-neutral data and long-term file compatibility.
The three user modes are separate crates and do not depend on one another.
`encap-ffmpeg` is deliberately narrow: it locates and validates bundled tools,
passes arguments without a shell, drains output without pipe deadlocks, records
diagnostics, and terminates child processes on cancellation for Audio export.
Core validates the complete original runtime directory before staging. Every mode
checks the pinned Core checksum manifest, metadata, source archive, target and
Core/application identity, plus original and post-sign hashes before using the pair.
Core's explicit `MediaTools::from_paths` validates both tools with the operation's
cancellation token. Video receives that same validated pair without rediscovery.
Release builds never use environment or PATH FFmpeg. Debug fixture overrides
require both absolute paths; invalid, partial or mismatched pairs fail.
AVID Core owns Video probing, capabilities, graphs and rendering, plus in-process
JPEG/PNG optimization and metadata removal. `optimize-artwork` passes a separate
output and protected project/media paths directly to Core; clients adopt the new
artwork path only after success. The original image remains intact.

Audio-only export, sample-layout parsing and waveform previews remain existing
EnCAP implementations because Core has no equivalent public operations. They are
outstanding **Core gaps**, not a completed ownership migration. Project archives,
episode metadata and schema migrations are EnCAP product logic. Core's Swift
packages own transcription catalog, verified model acquisition/cache leases,
recognition, alignment, and caption contracts. Production Transcript passes the
original media to those providers and has no separate FFmpeg conversion path.

Ordinary supported-host SRT/WebVTT export maps existing segment boundaries and
speakers to Core `CaptionCue`/`CaptionExporter`; word-caption grouping separately
uses `CaptionBuilder`. Core's Apple-only exporter cannot replace saved SRT export
on the other desktop targets, where the existing writer remains an explicit
portable-exporter gap. A supported helper failure is reported without fallback.
Core's subtitle escaping, newline folding and strict ordered positive-duration
cues are intentional differences; invalid legacy cues must be corrected to export
through Core. TXT remains EnCAP's plain-text project projection.

The signal handler cancels Core Rust tokens used by Audio/Video and the Transcript
sidecar adapter. Rust Core events/errors and Swift Core model/inference progress
are adapted at the JSON boundary; Core has no universal cross-language wire type.
EnCAP owns and reaps its audio-export and JSON-sidecar children. Acquisition uses
the pinned Core artifacts; a sibling checkout is unnecessary. Full file-level
ownership and remaining exceptions are recorded in [the audit](avid-core-audit.md).

Both presentation implementations use the `encap-engine` JSON process boundary.
JSON keys use
snake case, every invocation returns one JSON value on stdout, and failures
return `{ "error": "plain-language explanation" }` with a nonzero status.
Keeping the boundary identical makes the Qt and SwiftUI clients thin
and independently crash-isolated while the mode crates remain reusable.

The Apple transcription sidecar is a separately packaged higher-minimum-OS
executable; it does not raise the base app's macOS 13 deployment target. It
imports the verified immutable snapshot under `vendor/avid-core-transcription`,
with both Swift packages in their original sibling layout. It never parses
Core's display-oriented command output. Model and inference progress travels
as structured stderr events while stdout retains the final JSON contract.
Unsupported targets report unavailable transcription rather than advertising
an old backend as the new engine. See [migration details](transcription-avid-core.md).

UI layers delegate persistence, export construction, schema migration and
transcription routing to the engine. Qt retains a direct validated-FFmpeg PCM
preview decoder because Core has no public equivalent; this is a recorded gap. Platform code owns dialogs, windows, menus, accessibility,
appearance, drag/drop, playback, and lifecycle integration.

## Safety invariants

- Untrusted paths are process arguments, never shell text.
- Project archive extraction rejects traversal, duplicate paths, links, special
  files, extreme expansion, and oversized manifests before extraction.
- Deliverables are staged beside their destination and atomically replaced only
  after successful completion.
- Raw tool diagnostics stay in local logs; the UI receives concise errors.
- Unsupported future project schemas are never partially loaded or rewritten.
- No telemetry, analytics, or automatic diagnostic upload exists.

## Shared desktop presentation

`qt/` contains the Widgets view, interaction and lifecycle code for Windows
x64/ARM64, Linux x64/ARM64 and the internal Apple Silicon reference. Its
`EngineClient` invokes one JSON command per operation and keeps media work off
the UI thread. Rust owns project validation, persistence, transcription and
media production. Native miniaudio supplies recording preview; authenticated
bundled FFmpeg decodes PCM formats unsupported by that decoder. Narrow C/C++
adapters supply Linux MPRIS and Windows SMTC. GLib remains a Linux integration
dependency; GTK, libadwaita, GStreamer and WinUI are removed.

The reference bundle ID is `com.tlolabs.encap.qt-reference`. Qt running
on any Mac disables production update operations, even outside the app bundle.
Its updater executable/configuration and Sparkle are excluded from packaging.
Production update identity generation rejects that bundle ID. CI uploads its ZIP
only under an INTERNAL artifact name and never includes it in release inputs.

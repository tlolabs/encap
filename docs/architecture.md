# Native application architecture

```text
SwiftUI (production macOS) ----------------> encap-engine (one JSON response)
Avalonia AXAML -> EnCap.Application --------> |
                        |-- encap-core: project model and ZIP persistence
                        |-- encap-audio / encap-transcript -> encap-ffmpeg
                        `-- encap-video adapter -> avid-core -> FFmpeg/ffprobe

All modes resolve the same Core-built FFmpeg/ffprobe pair.
```

`encap-core` contains platform-neutral data and long-term file compatibility.
The three user modes are separate crates and do not depend on one another.
`encap-ffmpeg` is deliberately narrow: it locates and validates bundled tools,
passes arguments without a shell, drains output without pipe deadlocks, records
diagnostics, and terminates child processes on cancellation for Audio/Transcript.
Core validates the complete original runtime directory before staging. Every mode
checks the pinned Core checksum manifest, metadata, source archive, target and
Core/application identity, plus original and post-sign hashes before using the pair.
Core's explicit `MediaTools::from_paths` validates both tools with the operation's
cancellation token. Video receives that same validated pair without rediscovery.
Release builds never use environment or PATH FFmpeg. Debug fixture overrides
require both absolute paths; invalid, partial or mismatched pairs fail.
AVID Core owns Video probing, capabilities, graphs and rendering. Audio export,
Transcript providers, native WAV/AIFF parsing, waveform/editing and project archives
remain EnCAP responsibilities. One Core cancellation token connects the signal
handler to all three modes; EnCAP's Audio/Transcript runner still owns and reaps
its processes. Acquisition uses the pinned Core CI artifacts; a sibling checkout is unnecessary.

Both presentation implementations use the `encap-engine` JSON process boundary.
JSON keys use
snake case, every invocation returns one JSON value on stdout, and failures
return `{ "error": "plain-language explanation" }` with a nonzero status.
Keeping the boundary identical makes the Avalonia and SwiftUI clients thin
and independently crash-isolated while the mode crates remain reusable.

No UI layer owns persistence, media command construction, schema migration, or
transcription routing. Platform code owns dialogs, windows, menus, accessibility,
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

`desktop/EnCap.Application` owns observable presentation models, commands, dirty
state, recovery coordination and the existing Rust JSON client. It has no UI
framework dependency. `desktop/EnCap.Desktop` contains one AXAML tree, theme and
input routing implementation for Windows x64/ARM64, Linux x64/ARM64 and the
internal Apple Silicon reference. `desktop/EnCap.Tests` consumes the same shared
chapter/shuttle fixtures and exercises headless input, bindings and lifecycle.

`IEngineClient`, `IUserDialogs`, `IPlayback` and `IMediaSession` separate services
from presentation. Native miniaudio supplies recording preview; authenticated
bundled FFmpeg decodes PCM formats unsupported by that decoder. Narrow C/C++
adapters supply Linux MPRIS and Windows SMTC. GLib remains a Linux integration
dependency; GTK, libadwaita, GStreamer and WinUI are removed.

The reference bundle ID is `com.tlolabs.encap.avalonia-reference`. Avalonia running
on any Mac disables production update operations, even outside the app bundle.
Its updater executable/configuration and Sparkle are excluded from packaging.
Production update identity generation rejects that bundle ID. CI uploads its ZIP
only under an INTERNAL artifact name and never includes it in release inputs.

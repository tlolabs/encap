# Native application architecture

```text
SwiftUI / WinUI / GTK -> encap-engine (one JSON response)
                        |-- encap-core: project model and ZIP persistence
                        |-- encap-audio / encap-transcript -> encap-ffmpeg
                        `-- encap-video adapter -> avid-core -> FFmpeg/ffprobe

All modes resolve the same host-owned FFmpeg/ffprobe pair.
```

`encap-core` contains platform-neutral data and long-term file compatibility.
The three user modes are separate crates and do not depend on one another.
`encap-ffmpeg` is deliberately narrow: it locates and validates bundled tools,
passes arguments without a shell, drains output without pipe deadlocks, records
diagnostics, and terminates child processes on cancellation for Audio/Transcript.
Every mode verifies the host dependency record, recipe digest, target, Core identity,
original/post-sign hashes, and FFmpeg version before using the packaged pair.
Core's explicit `MediaTools::from_paths` validates both tools with the operation's
cancellation token. Video receives that same validated pair without rediscovery.
Release builds never use environment or PATH FFmpeg. Debug fixture overrides
require both absolute paths; invalid, partial or mismatched pairs fail.
AVID Core owns Video probing, capabilities, graphs and rendering. Audio export,
Transcript providers, native WAV/AIFF parsing, waveform/editing and project archives
remain EnCAP responsibilities. One Core cancellation token connects the signal
handler to all three modes; EnCAP's Audio/Transcript runner still owns and reaps
its processes. No Core runtime release, helper checkout or qualification app exists.

All three native applications use the `encap-engine` JSON process boundary.
JSON keys use
snake case, every invocation returns one JSON value on stdout, and failures
return `{ "error": "plain-language explanation" }` with a nonzero status.
Keeping the boundary identical makes the GTK, WinUI, and SwiftUI clients thin
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

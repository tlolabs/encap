# Native application architecture

```text
                         EnCap project model
                                  |
                            encap-core crate
                     (formats, persistence, models)
                       /                    \
        encap-assemble crate          encap-transcribe crate
       (ingest, chapters, encode)     (providers, local inference)
                       \                    /
                           encap-ffmpeg crate
                    (tool discovery and processes)
                                  |
                         encap-engine protocol
                       /          |           \
                 SwiftUI       WinUI 3     GTK 4/libadwaita
                  macOS         Windows         Linux
```

`encap-core` contains platform-neutral data and long-term file compatibility.
The two user modes are separate crates and do not depend on one another.
`encap-ffmpeg` is deliberately narrow: it locates and validates bundled tools,
passes arguments without a shell, drains output without pipe deadlocks, records
diagnostics, and terminates child processes on cancellation.

All three native applications use the `encap-engine` JSON process boundary.
JSON keys use
snake case, every invocation returns one JSON value on stdout, and failures
return `{ "error": "plain-language explanation" }` with a nonzero status.
Keeping the boundary identical makes the GTK, WinUI, and SwiftUI clients thin
and independently crash-isolated while the two mode crates remain reusable.

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

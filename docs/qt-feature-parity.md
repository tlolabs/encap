# Qt migration feature inventory

This inventory was made from the active 2.0.6 tree before removing any desktop
implementation. A row is complete only when the Qt client or existing Rust engine
provides the behavior and the listed verification is recorded. The historical
Avalonia migration report remains a record of the previous implementation.

| Capability | Previous owner and behavior | Final disposition | Verification |
| --- | --- | --- | --- |
| Application identity and launch | `AppIdentity.cs`, `App.axaml.cs`, `MainWindow.axaml.cs`; production Windows/Linux and isolated macOS reference | Qt launch and project argument; intentionally distinct internal macOS identity with no production updater | Package identity and launch tests |
| Engine process protocol | `EngineClient.cs`; one JSON reply per command, temporary payloads, errors on stdout, cancellation kills process tree | Qt `EngineClient` reuses Rust JSON verbs and snake case project JSON | Real engine contract and cancellation tests |
| Project lifecycle | `EditorViewModel.cs`; import, open, save, save as, dirty state, unsaved dialog, recovery, guarded close | Qt controls and state; Rust owns import, archive persistence, and recovery | Import/save/reopen/recovery tests |
| Recording editing | `EditorViewModel.cs`, `MainWindow.axaml`; WAV/AIFF import, add/remove multiple, source list, waveform, seek, J/K/L/Space shuttle | Qt editor and transport; Rust owns inspection/edit/waveform; native miniaudio owns playback | Audio edit protocol and device smoke test |
| Media integration | `SystemMediaSession.cs`, `desktop/native/media_*`; Windows SMTC and Linux MPRIS | Intentionally platform-specific native SMTC and MPRIS adapters reused by Qt | Native SMTC/MPRIS protocol tests |
| Episode metadata | `Models.cs`, `MainWindow.axaml`; podcast/episode/summary/artwork | Qt form and picker; Rust owns project JSON | Project round trip |
| Chapters | `EditorViewModel.cs`, `ChapterNaming.cs`; add/remove, title/link/duration/artwork, timeline recompute, Original/Numbered/Time/Custom naming | Qt table/editor and naming choice; Rust owns chapter/project semantics | Timestamp fixture and project round trip |
| Audio export | `EditorViewModel.cs`; MP3/AAC, bitrate, channels, compatible encoder | Qt settings and save dialog; Rust owns export and validation | Real MP3/AAC output tests |
| Transcription | `EditorViewModel.cs`; providers, model catalog/install/remove, word timestamps, editable speaker/text, TXT/SRT | Qt controls; Rust owns models, transcription, and export | Provider/model and TXT/SRT tests |
| Video | `EditorViewModel.cs`; chapter selection/order, presets, dimensions, FPS, codec/encoding, bitrate, flips, preview quality/artwork, MP4 | Qt controls and preview; Rust owns presets, validation, and render | Selection/order and MP4 media tests |
| Playback preview | `NativePlayback.cs`, `desktop/native/playback.c`; FFmpeg validated AIFF decode fallback, transport, rate, seek, volume | Qt transport; native miniaudio and authenticated FFmpeg reused | Native playback and cancellation tests |
| Interaction | `MainWindow.axaml.cs`; native dialogs, drag/drop, keyboard shortcuts, context menu, mode switch save rules | Qt Widgets dialogs, drag/drop, menus, focus, and state handling | UI automation and manual keyboard pass |
| Appearance and accessibility | `AppearancePreference.cs`, AXAML labels/live status; System/Light/Dark, scaling | Qt System/Light/Dark preference, accessible names/roles/status, high DPI | Qt automated and manual screen reader checks |
| Updates | `UpdateService.cs`, `windows/PortableUpdate`, Rust `encap-update`; stable check, authenticated download, Linux AppImage install, Windows staged/verified rollback | Qt update UI reuses Rust updater; new Rust Windows helper retains verification, Authenticode, identity, and rollback | Native updater contract and A-to-B tests |
| Packaging | `build_desktop.py`, `package_appimage.sh`, platform CI; self-contained .NET app and native adapters | Qt/CMake build and bundled runtime on four public targets; internal macOS reference is intentionally separate | Clean native package and launch on each target |

The production macOS SwiftUI/AppKit client and its Sparkle path are outside this
UI replacement. `desktop/native` is framework-neutral and remains useful.
No functional row was classified as obsolete or intentionally dropped. The
retired Avalonia/.NET implementation itself is archived by Git history.

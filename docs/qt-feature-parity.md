# Qt migration feature inventory

This inventory was made from the active 2.0.6 tree before removing any desktop
implementation. A row is complete only when the Qt client or existing Rust engine
provides the behavior and the listed verification is recorded. The historical
Avalonia migration report remains a record of the previous implementation.

| Capability | Current owner and behavior | Required Qt/Rust result | Verification |
| --- | --- | --- | --- |
| Application identity and launch | `AppIdentity.cs`, `App.axaml.cs`, `MainWindow.axaml.cs`; production Windows/Linux and isolated macOS reference | Distinct internal Qt Mac identity, same CLI project argument, production updates disabled on Mac | Package identity and launch tests |
| Engine process protocol | `EngineClient.cs`; one JSON reply per command, temporary payloads, errors on stdout, cancellation kills process tree | Reuse `encap-engine` verbs and snake case project JSON; preserve unknown fields | Real engine contract and cancellation tests |
| Project lifecycle | `EditorViewModel.cs`; import, open, save, save as, dirty state, unsaved dialog, recovery, guarded close | Same transitions and archive format; Rust remains the persistence owner | Import/save/reopen/recovery tests |
| Recording editing | `EditorViewModel.cs`, `MainWindow.axaml`; WAV/AIFF import, add/remove multiple, source list, waveform, seek, J/K/L/Space shuttle | Reuse Rust inspect/edit/waveform and native miniaudio ABI; retain original files | Audio edit protocol and device smoke test |
| Media integration | `SystemMediaSession.cs`, `desktop/native/media_*`; Windows SMTC and Linux MPRIS | Reuse native adapters with Qt native window handle and UI thread dispatch | Native SMTC/MPRIS protocol tests |
| Episode metadata | `Models.cs`, `MainWindow.axaml`; podcast/episode/summary/artwork | Editable form, native artwork picker, same JSON keys | Project round trip |
| Chapters | `EditorViewModel.cs`, `ChapterNaming.cs`; add/remove, title/link/duration/artwork, timeline recompute, Original/Numbered/Time/Custom naming | Same naming and preference paths; editor and list keyboard access | Timestamp fixture and project round trip |
| Audio export | `EditorViewModel.cs`; MP3/AAC, bitrate, channels, compatible encoder | Rust export with identical settings and save dialog | Real MP3/AAC output tests |
| Transcription | `EditorViewModel.cs`; providers, model catalog/install/remove, word timestamps, editable speaker/text, TXT/SRT | Reuse Rust provider/model/transcribe/export verbs and form behavior | Provider/model and TXT/SRT tests |
| Video | `EditorViewModel.cs`; chapter selection/order, presets, dimensions, FPS, codec/encoding, bitrate, flips, preview quality/artwork, MP4 | Reuse Rust presets and export; Qt controls and chapter preview | Selection/order and MP4 media tests |
| Playback preview | `NativePlayback.cs`, `desktop/native/playback.c`; FFmpeg validated AIFF decode fallback, transport, rate, seek, volume | Reuse native ABI and authenticated FFmpeg; Qt keeps UI responsive | Native playback and cancellation tests |
| Interaction | `MainWindow.axaml.cs`; native dialogs, drag/drop, keyboard shortcuts, context menu, mode switch save rules | Qt Widgets equivalents with logical focus and enabled states | UI automation and manual keyboard pass |
| Appearance and accessibility | `AppearancePreference.cs`, AXAML labels/live status; System/Light/Dark, scaling | Persist preference; Qt accessible names/roles/status; high DPI | Qt automated and manual screen reader checks |
| Updates | `UpdateService.cs`, `windows/PortableUpdate`, Rust `encap-update`; stable check, authenticated download, Linux AppImage install, Windows staged/verified rollback | Qt UI calls same Rust updater; replace C# portable helper without weakening package, Authenticode, identity or rollback checks | Native updater contract and A-to-B tests |
| Packaging | `build_desktop.py`, `package_appimage.sh`, platform CI; self-contained .NET app and native adapters | CMake Qt Widgets build, bundled Qt runtime, same four public Windows/Linux targets and internal Mac reference | Clean native package and launch on each target |

The production macOS SwiftUI/AppKit client and its Sparkle path are outside this
UI replacement. `desktop/native` is framework-neutral and remains useful.

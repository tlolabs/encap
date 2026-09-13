# Legacy application behavior

This record was produced before the Rust engine replaced the Python engine. It
combines source inspection, automated tests, Git history, and a launch of the
installed Python/PySide6 application on macOS.

Reference captures: [Process Audio](legacy-ui/process-audio.png) and
[Transcribe](legacy-ui/transcribe.png).
The configured GitHub repository had no open or closed issues at the time of
the audit, so no additional issue-only compatibility contracts were found.

## Product behavior

EnCap assembles a naturally sorted folder of WAV and AIFF recordings into one
chaptered podcast deliverable. The Process Audio workspace exposes podcast and
episode metadata, summary, artwork, output format, encoder, channel count,
bitrate, and a reorderable chapter table. The Transcribe workspace exposes
local transcription providers, editable time-coded segments, speakers, and
plain-text/SRT export.

The legacy empty state uses a top toolbar for import, project open/save,
artwork, media/transcript export, transcription, and optional AI suggestions.
Its main content has Process Audio and Transcribe tabs and a persistent status
bar. The native replacements preserve those recognizable workflows while using
platform-standard navigation, dialogs, menus, keyboard shortcuts, and focus.

## Compatibility contracts

- `.encap` is a ZIP document with `manifest.json`, `audio/`, `artwork/`, and
  `chapters/` members.
- Manifest schema version 1 stores metadata, ordered audio sources, chapters,
  transcript segments, and export settings.
- Historical output-format aliases (`m4a`) and encoder aliases
  (`ffmpeg_default`, `lame_mp3_advanced`) are accepted.
- Opening a project extracts media into a private session directory. Closing or
  replacing the document removes only directories owned by that session.
- Project saves, transcript exports, assembled WAVs, and final encodes use
  same-filesystem temporary files followed by atomic replacement.
- Unsupported future schemas are refused without modifying the project.

## Audio and transcription

The application accepts PCM/IEEE-float WAV and PCM AIFF/AIFC inputs, detects
malformed/truncated headers, converts mismatched sources through FFmpeg, and
preserves chapter timing. MP3 and AAC/M4A exports include episode metadata,
chapter titles/links, and artwork. FFmpeg/ffprobe remain required bundled tools.

Transcription is local. macOS can use Apple Speech. All platforms can use
verified whisper.cpp models; supported macOS installations may reuse verified
models already installed by compatible transcription applications. Model
weights are not bundled and automatic network fallback during inference is
disabled.

## Platform baselines

- macOS 13 is the documented minimum and is retained. WhisperKit reuse remains
  an optional macOS 14+ capability.
- The legacy repository did not state explicit Windows or Linux version
  minimums. The replacement retains Windows 10 version 1809 as the defensible
  WinUI baseline and targets currently supported GTK 4/libadwaita distributions.
- Source and runtime inspection found no persisted QSettings/preferences store
  to migrate. The rewrite therefore leaves the legacy installation untouched
  and uses native state facilities only for new UI state.

## Pre-rewrite verification

- Python unittest suite: 103 passed.
- Native macOS Swift suite: 8 passed.
- Installed Python application launched successfully and exposed the expected
  Process Audio empty state, controls, tab order, and accessible control names.

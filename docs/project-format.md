# EnCap project format

`.encap` is EnCap's long-term user-data contract. It is a ZIP document whose
root contains `manifest.json`; referenced audio and images are stored below
`audio/`, `artwork/`, and `chapters/`. The current manifest schema is version 2.
Schema 1 documents open transparently and are written as schema 2 on their next
normal atomic save.

## Manifest

The top-level object contains:

| Key | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | `2`; schema `1` is accepted and migrated in memory. |
| `project_title` | string | User-facing project name. |
| `metadata` | object | Podcast title, episode title, summary, and optional stored artwork path. |
| `audio_sources` | array | Ordered display name, duration, and archive path for every source. |
| `chapters` | array | Start, duration, number, title, link, and optional stored image path. |
| `transcript_segments` | array | Stable ID, start/end times, speaker, text, and optional word timings. |
| `transcript_settings` | object | Word-timestamp preference and optional recognition model, alignment model, and language selection. |
| `export_settings` | object | Output format, encoder, bitrate preset, and channel count. |
| `active_mode` | string | `audio`, `transcript`, or `video`; legacy mode aliases migrate. |
| `video` | object | Versioned current Video export state and future composition extension point. |

Stored archive paths use forward slashes and are always relative. Runtime-only
paths (`source_path`, `working_dir`, and `project_path`) never appear in the
manifest; the engine reconstructs them in an owned private extraction directory
when opening the document.

Historical aliases remain accepted: `m4a` is treated as AAC/M4A, and older encoder
names are normalized during migration. A native client carries
an opaque compatibility payload across its Rust process boundary. Unknown fields
at the manifest, metadata, audio-source, chapter, transcript-segment, and export
settings levels are merged back during save rather than silently discarded.

### AVID transcription extensions

The schema remains 2. New imports receive a per-instance UUID `avid_source_id`,
pinned before their paths change during save or extraction. Persisted IDs and
the deterministic legacy fallback remain compatible; reimporting original media
after extraction creates a distinct source instance. A new transcript segment carries
an optional `avid_core` version-1 extension with `source_id`,
`source_duration_seconds`, `source_timeline_offset_seconds`,
`source_offset_seconds`, `segment_index`, `timing_status`, and `transcript`.
The nested transcript envelope stores the original one-segment shared record,
including source-clock words, confidence, language and recognition/alignment
provenance. `alignment_record` holds the latest alignment separately; initial
recognition remains immutable. Model provenance includes complete manifest
installation identities and the frozen SDK source identity.
Storage stays linear in transcript length. Unknown extension fields
remain preserved.

Editable `start_time_seconds`/`end_time_seconds` and words use the assembled
episode clock. The reversible mapping is
`episode = original_source - source_offset + source_timeline_offset`.
Source edits change projected times and the timeline offset; they do not rewrite
the original recognition record. Text edits clear the affected word array and
mark alignment invalidated. Speakers and stable host IDs remain host data.
Source identity determines whether a segment survives removal. Slight native
timing overshoot is clipped to the retained source's playable interval while
original raw boundaries remain unchanged; collapsed timing remains untimed text.

Untimed recognition has `timing_status: "untimed"`; zero-length host positions
are placeholders for editing rather than speech boundaries. TXT export is
available, while timed subtitle/caption export requires usable real timing.
Old projects without `avid_core` retain their existing TXT/SRT interpretation.
Reopening an old project does not trigger recognition, model conversion, or
replacement of user-edited text.

Explicit rerecognition reuses IDs only for confidently matching source/text/time
records and transfers speakers only across unambiguous timing regions. Unmatched
prior editable segments are retained once in `avid_core.previous_transcript` on
the first replacement segment, including their IDs, speakers and unknown fields.
`reconciliation_warning` is shown by both clients if manual assignments need
review. This history does not silently apply an ambiguous speaker to a newly
segmented transcript.

Removing a history carrier transfers and deduplicates its archive onto a surviving
AVID segment. If audio remains with no suitable active segment, optional top-level
`avid_transcript_history` and `avid_reconciliation_warning` preserve that data and
keep its warning visible. Removing all audio intentionally clears the transcript
and archived history; explicit null values prevent opaque compatibility payloads
from restoring cleared history on save.

## Compatibility behavior

- Missing optional fields use documented defaults.
- Schema 1 is migrated without altering the source file. A schema newer than 2
  is rejected with an explicit compatibility
  error before media is extracted for use or the source document is changed.
- Unknown fields within supported schemas survive a native open/edit/save round trip.
- The original document is read-only. Opened media lives in a new session-owned
  directory, which only EnCap may clean up.
- Saving creates a complete temporary archive beside the destination, flushes
  it, and replaces the destination only after success.
- Replacing a destination on platforms without overwrite-by-rename uses a
  recovery backup and restores the known-good original if the final rename
  fails.

## Incremental saves

Opened media stays extracted throughout the session. Saves keep the same portable
ZIP/schema-2 format, with `manifest.json` last. An optional machine-local index in
the application cache records archive and media file identities, sizes, and
timestamps. Absolute source paths are confined to that disposable index; they
are not added to the project archive. Opening a project rebuilds the index for
its newly extracted media, including archives created by older versions.

When media is unchanged, saving copies the existing archive to a private staging
directory beside the destination and replaces only its manifest and ZIP directory.
The shared engine explicitly requests filesystem cloning: `fclonefileat` on macOS,
`FICLONE` on Linux, and block cloning on Windows. APFS, Linux reflink-capable
volumes such as Btrfs/XFS, and supported ReFS volumes can avoid copying all media
bytes. Windows clones complete, cluster-aligned ranges in chunks and copies only
the final partial cluster. See Microsoft's [block cloning requirements](https://learn.microsoft.com/en-us/windows/win32/fileio/block-cloning).
An unsupported or failed clone discards the partial staging file and falls back
to an ordinary copy. This keeps NTFS, ext4, removable, and network volumes working,
but their save time can still scale with archive size. Neither path recompresses
unchanged media or writes through a hard link to the original file. The staged
tail is truncated before replacement so repeated saves cannot accumulate old manifests.

If media is added, removed, or changed, the engine builds a fresh staged archive,
copies unchanged ZIP members without decompressing them, and writes changed media
using ZIP's Stored method. First saves also store media without deflate; WAV/PCM
projects can consequently be larger than in earlier versions. The small manifest
remains compressed. Missing, stale, or unreadable cache data safely falls back to
a full save. Source changes detected during saving abort before publication.
Every successful save remains a complete, flushed `.encap` document; transferring
the document does not require the index or the extracted working directory.

All three native clients save named projects through this shared path when
switching modes and retain the canonical path returned by the engine. Linux
also restores the saved mode on open, keeps unnamed mode changes in recovery
storage, and rolls back the mode selection on save failure without clearing
the previous recovery record.

## Archive safety limits

The loader rejects absolute paths, parent traversal, platform path prefixes,
duplicate member paths, symbolic links and other special files. It also applies
these current upper bounds before and during extraction:

| Limit | Value |
| --- | --- |
| Archive entries | 4,096 |
| Manifest size | 8 MiB |
| Individual expanded member | 32 GiB |
| Total expanded data | 64 GiB |
| Expanded/compressed ratio | 1,000:1 |

These are defensive implementation limits, not encouragement to create projects
near those sizes. Applications should surface the engine's plain-language error
and leave both the source document and any previous destination untouched.

## Evolution rules

Additive schema-2 fields must have safe defaults and must be preserved by older
schema-2 clients. A change that cannot be represented safely under those rules
requires a new `schema_version` and a deliberate migration path. Never reuse a
field with a different meaning and never partially open a newer unsupported
schema.

`video.schema_version` evolves independently. Video 2.0 persists one export
configuration and reserves `compositions` plus extension fields for future layers,
keyframes, caption styles, animation triggers, render variants, and queued exports;
2.0 neither interprets nor creates those future objects.

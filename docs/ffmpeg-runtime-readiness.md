# Managed FFmpeg runtime migration readiness

> Superseded scope (2026-09-15): Windows/Linux GPU parity and GPU machines are no longer requirements. Software encoding is authoritative, VideoToolbox is optional on macOS, and minimum-OS qualification remains required. See [current integration notes](ffmpeg-source-runtime.md). The audit below records the earlier state.

Checked 2026-09-15 at approximately 07:14 UTC. This is a prerequisite audit and
current-runtime baseline, not a completed migration or release qualification.

## Decision: preserve the current runtime

The requested migration requires a qualified Core mapping, complete runtime matrix,
matching published assets, and completed ATIV verification. Those prerequisites
remain incomplete. No EnCAP acquisition, discovery, dependency, signing, packaging,
or application-release behavior was changed during this audit.

### Remote evidence

- GitHub's authenticated `repos/tlolabs/avid-core/releases` API returned `[]`.
  There are no published runtime assets to authenticate or stage.
- The existing [v0.2.0 tag](https://github.com/tlolabs/avid-core/tree/v0.2.0)
  points to `b4649117683df49631ee3b3d4a2c792f18ea293b`, also remote main at
  inspection. Its FFmpeg specification is recipe 1, status `candidate`.
- The newer runtime work at
  [4825607d54b8b41d94b6d56dd99e5f0899c528b8](https://github.com/tlolabs/avid-core/commit/4825607d54b8b41d94b6d56dd99e5f0899c528b8)
  uses FFmpeg 9.0.1, source revision
  `bf1b838f2ab88b4f8fd83443325c782ea0e0f7fa`, recipe 2, status `candidate`.
  These are observed candidate identities, not an approved EnCAP pin.
- Its [runtime workflow](https://github.com/tlolabs/avid-core/actions/runs/34940148762)
  was in progress: all six native build jobs were still running. The specification
  job and baseline jobs completed successfully; the macOS baseline inventory steps
  were skipped. Baseline inventory success does not qualify new runtime binaries.
- Its [shared-core workflow](https://github.com/tlolabs/avid-core/actions/runs/34940148739)
  passed. This does not establish the runtime release matrix.
- The remote qualification file at that exact revision records `not_run` with
  empty evidence for hardware parity, minimum OS, toolchain and host packaging
  on each of macOS ARM64/x86_64, Windows ARM64/x86_64 and Linux ARM64/x86_64.
- Recipe 2 would derive tag `ffmpeg-9.0.1-r2` and runtime basename
  `avid-ffmpeg-9.0.1-r2-<target>`. No release asset digest or authenticated artifact
  mapping exists to select. Derive the eventual mapping from the qualified Core
  specification; do not turn these candidate names into host constants.

The four specification blockers cover the complete CI/repeat-build matrix,
Linux/Windows hardware parity and actual devices, qualified toolchain environments,
and host packaging/signing/minimum-OS/mode verification. Core owns resolving and
recording these gates; EnCAP must not bypass them or create a competing recipe.

### ATIV evidence

ATIV remote main and local HEAD were
`030c17809da14263a19705402ec95db428681d39`. Its committed
`docs/migration-avid-core.md` describes the earlier Rust-engine migration using
Core `0cce6ba838827d0bed540efc98731e74a1014456` and the third-party FFmpeg pair.
It is not a completed qualification report for the managed runtime.

Local ATIV has unfinished acquisition, packaging and discovery changes, including
`runtime/core-revision` pointing to `4825607d54b8b41d94b6d56dd99e5f0899c528b8`.
Those files were inspected without modification. Core also has uncommitted runtime
script changes; neither working tree is treated as immutable release evidence.

## EnCAP baseline

- EnCAP HEAD: `436346c0cc61e38fe8a9e1012a55e8cc26b75d70`, version 2.0.3.
- Existing dedicated branch: `codex/encap-managed-runtime-preflight`.
  The working tree was clean before this report.
- Local Cargo dependency uses sibling `../AVID Core`; all workflow checkout
  pins use `0cce6ba838827d0bed540efc98731e74a1014456`. A future migration must
  make local and CI revisions agree with the qualified runtime revision.
- Current acquisition uses Martin Riedl macOS artifacts and BtbN Windows/Linux
  artifacts. Windows repeats its asset/download table in `build-platforms.yml`.
- The host wrappers already delegate to `prepare_ffmpeg.sh`. Its cache directory
  contains a hard-coded version and its recipe key hashes the host fetch script.
- Audio and Transcript use `encap_ffmpeg::MediaTools::discover`; Video uses the
  same resolver through `discover_with_validator`, then Core validation with the
  resolved paths. There is one shared resolution policy, but it currently resolves
  tools independently and allows PATH fallback. It does not enforce an authenticated,
  matched managed pair for production.
- Distributed targets remain macOS ARM64/Intel, Windows x64/ARM64 and Linux x64.
  Core's six-target matrix also includes Linux ARM64 for ATIV.

### Existing local macOS ARM64 executable identities

Both available FFmpeg copies identify as
`9.0.1-https://www.martin-riedl.de`. These are hashes of the inspected executable
bytes, not archive hashes or evidence of a Core release.

| Location | Executable | SHA-256 |
| --- | --- | --- |
| `dist/EnCap.app/Contents/MacOS` | ffmpeg | `65948fb06823b2f6c2a95932b21c9abaa9d0e730f4dbbb7bcaa975eb87f31621` |
| same bundle | ffprobe | `2d0f252b6ceb0a8125d3f6d2eac8ce8204ef835b05498953323cb17ba161c9fb` |
| `.build-tools/ffmpeg-9.0.1-install-arm64/bin` | ffmpeg | `393e4c395020a1cb7cbd77fbe00599ce69d1c6466fee0dbd59d13f86a81a1611` |
| same cache | ffprobe | `7abc49fb2bdf2204f018e76dc6e0a8ae7643313bae09a9fa43e7eb12442271bc` |

### Verification performed in this audit

The existing media-contract suite passed **3/3** against the existing packaged
engine, FFmpeg and FFprobe, with explicit absolute `ENCAP_TEST_ENGINE`,
`ENCAP_FFMPEG`, and `ENCAP_FFPROBE` paths into `dist/EnCap.app/Contents/MacOS`:

```sh
cargo test --locked --offline -p encap-engine --test media_contract -- --ignored
```

The tests were `release_pair_has_complete_audio_transcript_video_capabilities`,
`whole_engine_media_persistence_recovery_and_reference_contract`, and
`artwork_flips_and_real_media_failures_preserve_sources`. Cargo compiled the harness
against the available sibling Core checkout; engine subprocesses explicitly used
the existing packaged engine. These results establish a current-package baseline.
They do not qualify the candidate or establish real GPU/driver, native UI,
minimum-OS, clean-install or other-platform behavior. No new package was built.

## Implementation boundaries after prerequisites pass

Use the selected Core checkout's `scripts/ffmpeg/acquire.py` and packaging helpers
through thin host entrypoints. Core acquisition already requires qualification,
a clean runtime mapping, an immutable release at the selected revision, trusted
GitHub asset digests, and source/workflow-bound attestations before staging verified
regular files. Keep that authentication and capability logic in Core. EnCAP's
native-only source check rejects host Python files, so invoke Core's utility without
copying it into EnCAP or bundling Python as an application dependency.

Update local/CI Core pins together; replace both acquisition tables and version
checks only after the applicable gates pass. Cache by Core specification/recipe,
target and authenticated artifact identity. Route all modes through the same
managed pair, retain deliberate development overrides, and make production fail
on a missing/damaged bundle without PATH fallback.

Bundle the actual manifests, licenses, source/provenance and acquisition receipt.
Verify original payloads before host signing and record signed hashes separately.
Keep installer, signing, update and release ownership in EnCAP.

Before retiring the old mechanisms, execute Core real-media and EnCAP media-contract
suites against the candidate packaged paths, plus the requested audio metadata,
AudioToolbox, artwork/chapters, PCM/AIFF/AIFC, concat/channels, transcript mono16k,
video/hardware/fallback, preview/lifecycle, playback/save and installer/startup gates.
Windows ARM64 requires native execution. Record each gate as passed, failed or
not run, with actual hardware evidence. No obsolete mechanisms or caches were
removed during this blocked prerequisite audit.

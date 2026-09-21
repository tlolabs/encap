# EnCAP source-runtime verification

Migration in progress on `codex/encap-source-ffmpeg`, starting from `860c408`.
FFmpeg 9.0.2 official source signature and SHA-256 verified locally.
First macOS ARM64 source build completed successfully. Workspace tests and
Clippy passed after replacing the runtime resolver. The native six-target
workflow and normal application packaging are being qualified; results below
will be updated with completed run evidence. No production release is authorized.

The older Core candidate results do not qualify this independent recipe.

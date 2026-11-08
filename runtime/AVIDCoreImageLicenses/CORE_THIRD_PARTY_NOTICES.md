# Third-party notices

AVID Core's Rust crate is a source library. Its image optimizer compiles and links
upstream native codecs from pinned source packages. Core also publishes separate
source-built FFmpeg/ffprobe runtimes under [the provider contract](docs/ffmpeg/provider-contract.md),
with their own build and license inventories. The crate does not ship Microsoft
runtime DLLs, fonts or third-party artwork. Its small synthetic audio and image
test fixtures were generated locally with FFmpeg; commands and hashes are in
[the fixture provenance record](tests/fixtures/ffmpeg/provenance.json).

The locked dependency graph is listed with exact versions, sources, checksums and
license expressions in [docs/dependency-inventory.json](docs/dependency-inventory.json).
Direct dependencies include `serde`, `serde_json`, `sha2` and `tempfile` (MIT or
Apache-2.0), `same-file` (Unlicense or MIT), and the image components below.
Support-crate copyright notices and full license texts remain in their Cargo
source packages; this file does not claim ownership of them.

| Image component | Applicable upstream license and preserved notice |
| --- | --- |
| `turbojpeg` 1.5.1 / `turbojpeg-sys` 1.2.0 | Unlicense or MIT Rust wrappers; [TurboJPEG MIT license](licenses/image-optimization/turbojpeg-LICENSE), [sys MIT license](licenses/image-optimization/turbojpeg-sys-LICENSE) |
| Vendored libjpeg-turbo 3.1.0 | IJG and BSD-3-Clause; Zlib terms on optional SIMD source are subsumed by IJG in the combined library; [native overview/BSD text](licenses/image-optimization/libjpeg-turbo/LICENSE.md), [full IJG README](licenses/image-optimization/libjpeg-turbo/README.ijg), [Zlib notice](licenses/image-optimization/libjpeg-turbo/ZLIB-NOTICE) |
| OxiPNG 9.1.5 | MIT, Copyright (c) 2016 Joshua Holmer; [license](licenses/image-optimization/oxipng-LICENSE) |
| `libdeflater` / `libdeflate-sys` 1.26.1 | Apache-2.0 Rust wrappers; [libdeflater license](licenses/image-optimization/libdeflater-LICENSE), [libdeflate-sys license](licenses/image-optimization/libdeflate-sys-LICENSE) |
| Vendored libdeflate 1.26 | MIT, Copyright 2016 Eric Biggers and Copyright 2024 Google LLC; [COPYING](licenses/image-optimization/libdeflate-COPYING) |
| Zopfli 0.8.2 | Apache-2.0; [COPYING](licenses/image-optimization/zopfli-COPYING) |
| `png` 0.17.16 | MIT or Apache-2.0; [MIT license](licenses/image-optimization/png-LICENSE-MIT), [Apache license](licenses/image-optimization/png-LICENSE-APACHE) |

This software is based in part on the work of the Independent JPEG Group.
Preserve that attribution and the applicable full license texts in host binary
distributions. [The source record](licenses/image-optimization/README.md) identifies
the exact native commit and files; Core's own GPL license does not replace these
notices. The native codecs and PNG decoder are compiled from pinned source,
including for host application builds.

Target-specific dependencies include Microsoft's `windows-sys` and `windows-link` (MIT or Apache-2.0) from [windows-rs](https://github.com/microsoft/windows-rs). These are open-source Rust crates, not Windows App SDK or proprietary redistributable binaries. Other transitive licenses include Unlicense, Unicode-3.0, and optional Apache-2.0 with LLVM exception or LGPL-2.1-or-later alternatives; the inventory records each package's exact expression. No dependency needs to be relicensed as GPL for AVID Core's own source to use GPL-3.0-or-later.

The source crate and the separately published FFmpeg runtime are distinct release
artifacts. Each binary or media release must carry its own applicable upstream
notices and exact component inventory.

`CODE_OF_CONDUCT.md` adapts [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) by replacing its reporting placeholder. The upstream 2.1 text is licensed [CC BY 4.0](https://github.com/EthicalSource/contributor_covenant/blob/2.1/LICENSE.md); its attribution is retained in that file. It is independent community documentation, not AVID Core library code or a Windows distribution component.

# Image optimization license texts

These files preserve upstream license notices for the image codecs linked into
Core consumers. They are independent upstream works; Core's GPL-3.0-or-later
declaration does not replace their licenses. Include these notices in ATIV and
EnCAP distributions that use the image optimizer.

| Component | Source evidence | Preserved text |
| --- | --- | --- |
| `turbojpeg` 1.5.1 Rust wrapper | Checksummed crates.io source; Unlicense or MIT | [MIT license](turbojpeg-LICENSE) |
| `turbojpeg-sys` 1.2.0 Rust wrapper | Source commit `05da705c6b6147baec1834a4c1f0de5e1df2614b`; Unlicense or MIT | [MIT license](turbojpeg-sys-LICENSE) |
| Native libjpeg-turbo 3.1.0 | `turbojpeg-sys` pins [native commit](https://github.com/libjpeg-turbo/libjpeg-turbo/tree/20ade4dea9589515a69793e447a6c6220b464535) `20ade4dea9589515a69793e447a6c6220b464535`; vendored CMakeLists.txt identifies version 3.1.0 | [native license overview/BSD text](libjpeg-turbo/LICENSE.md), [complete IJG README](libjpeg-turbo/README.ijg), [Zlib notice](libjpeg-turbo/ZLIB-NOTICE) |
| OxiPNG 9.1.5 | Checksummed crates.io source; MIT | [oxipng-LICENSE](oxipng-LICENSE) |
| `libdeflater` 1.26.1 | Checksummed crates.io Rust wrapper source; Apache-2.0 | [libdeflater-LICENSE](libdeflater-LICENSE) |
| `libdeflate-sys` 1.26.1 | Checksummed crates.io Rust wrapper source; Apache-2.0 | [libdeflate-sys-LICENSE](libdeflate-sys-LICENSE) |
| Native libdeflate 1.26 | `libdeflate-sys` vendored `libdeflate.h` identifies 1.26; native MIT notice | [libdeflate-COPYING](libdeflate-COPYING) |
| Zopfli 0.8.2 | Checksummed crates.io Rust source; Apache-2.0 | [COPYING](zopfli-COPYING) |
| `png` 0.17.16 | Checksummed crates.io Rust source; MIT or Apache-2.0 | [MIT](png-LICENSE-MIT), [Apache-2.0](png-LICENSE-APACHE) |

This software is based in part on the work of the Independent JPEG Group.

The native license overview and complete IJG README are preserved from the
vendored source in `turbojpeg-sys`'s package. Its wrapper license was retrieved from
the exact Rust source commit because the package omits the repository-root LICENSE.
The Zlib file is the unmodified opening copyright/license comment from vendored
`libjpeg-turbo/simd/nasm/jsimdext.inc`; Core's selected scalar build does not compile
the optional SIMD extension. No native codec source was modified here.

[sources.json](sources.json) records each preserved file's SHA-256 and source
path. `Cargo.lock` and [the dependency inventory](../../docs/dependency-inventory.json)
record package versions and acquisition checksums. The inventory also covers
Rust support crates. See
[third-party notices](../../THIRD_PARTY_NOTICES.md) and
[the image contract](../../docs/image-optimization.md).

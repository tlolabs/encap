# Building EnCap

The Rust workspace uses the toolchain in `rust-toolchain.toml` and locked
`Cargo.lock` dependencies. From the repository root:

```sh
cargo build --locked --workspace
```

On macOS, use `./script/build_and_run.sh` for the native app and local
media runtime. The macOS app requires macOS 13 or later and Xcode 26 for the
current icon build. On Windows, the WinUI 3 project requires the .NET 8 SDK,
Visual Studio 2022/Windows App SDK build tools, and a supported Windows SDK.
On Linux, use Meson with GTK 4, libadwaita, JSON-GLib, GStreamer and native
development packages. The pinned FFmpeg recipe is in
[ffmpeg-source-runtime.md](ffmpeg-source-runtime.md).

Clean builds fetch exact upstream source inputs and therefore require
network access. Ordinary app use can stay offline after dependencies and
optional speech models are installed. Detailed platform commands and engine
protocol examples remain in [development.md](development.md).

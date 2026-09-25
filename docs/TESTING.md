# Testing EnCap

Run the relevant checks before submitting changes:

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked --all-features
python3 script/test_ffmpeg_build.py
python3 script/test_runtime_ownership.py
python3 script/dependency_inventory.py --check
python3 script/check_project_metadata.py
./script/check_no_python.sh
```

The native CI workflow also builds and tests macOS (ARM64/x64),
Windows (x64/ARM64), and Linux (x64/ARM64), including platform UI and
packaged media checks where its jobs run. A passing CI build is distinct from
personal testing; Thomas Lothian primarily tests macOS (ARM64).
The supported target and OS baseline definitions are in
[`support-matrix.json`](support-matrix.json); the metadata check keeps build
files and documentation aligned with that definition.
See [development.md](development.md) for platform-specific commands.

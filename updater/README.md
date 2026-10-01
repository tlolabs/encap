# tlo-updater

Application-independent stable GitHub Releases update client. No AVID Core or host application dependency. See `../docs/automatic-updates.md` for the trust contract, platform adapters, adoption and qualification requirements.

Use `verify` before `select` or `download`. Production hosts should use `client::run`, which enforces that sequence, installed identity, host compatibility, scheduling and state locking. Native UIs execute the CLI asynchronously and own work preservation/installation consent. macOS continues to use Sparkle.

This reviewed source snapshot is vendored for independently buildable application checkouts. `SNAPSHOT.json` pins its source and companion release-only Python tooling. It is not yet a published standalone Git dependency. Changes must be synchronized as a complete reviewed snapshot; application-specific policy belongs in thin host adapters.

Run `cargo test -p tlo-updater`; `tlo-qualify` verifies staged/published release authentication and download, explicitly not native installation. No platform has been end-to-end qualified by this implementation work.

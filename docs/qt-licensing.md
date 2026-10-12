# Qt distribution and corresponding source

EnCap's shared Windows/Linux frontend and internal Apple Silicon reference use
Qt 6 Core, Gui and Widgets through dynamic libraries. The repository uses Qt's
GPL-3.0 option, compatible with EnCap's GPL-3.0-or-later license. It does not
use a commercial Qt license or a Qt Quick/QML module. The CMake module list is
checked by `script/check_desktop_dependencies.py` against
`qt/dependency-inventory.json`.

Each assembled package contains `qt-runtime.json`. It records the actual Qt
version, copied framework/library/plugin paths and SHA-256 hashes. The platform
plugin is required for launch: `qwindows` on Windows, `qxcb` and optional
Wayland integration on Linux, and `qcocoa` in the internal Mac reference.
Image-format plugins used for artwork include JPEG, GIF and ICO. `macdeployqt`
can copy transitive QtDBus and non-Qt runtime libraries; those copied files are
part of the inventory and their licenses must be reviewed for each release.
Qt's deployment tools are used on macOS and Windows; the Linux AppImage stages
the corresponding Qt libraries and plugins before `linuxdeploy` resolves system
dependencies.

The source corresponding to the Qt binaries, platform plugins, image plugins,
any distributor patches, and bundled third-party libraries must be available
with public binary releases. Match the exact `qt_version` in `qt-runtime.json`:

- Official Qt binary builds: fetch the `qtbase-everywhere-src-<version>` archive
  from [Qt's official source downloads](https://download.qt.io/official_releases/qt/)
  and preserve its `LICENSES/` directory and third-party attributions.
- Ubuntu Qt builds: fetch the matching distribution source package, including
  the Debian patches, from [Ubuntu's `qt6-base` source](https://packages.ubuntu.com/source/qt6-base).
  Use the package version installed on the build runner, which can differ from
  the upstream Qt version.
- Homebrew Qt builds: use the matching [Homebrew `qtbase` formula](https://formulae.brew.sh/formula/qtbase)
  and its referenced upstream source plus formula patches. Record the exact
  formula revision alongside the internal reference package.

For each public release, attach a source archive or an equivalent durable,
unrestricted download for these corresponding sources and the EnCap commit.
Retain exact license texts for every bundled Qt and non-Qt library. Verify the
package's `qt-runtime.json` against the extracted files. The source and license
record is a publication condition, separate from code signing and the runtime
update signature. See [Qt's open-source obligations](https://www.qt.io/licensing/open-source-lgpl-obligations)
and [Qt's license overview](https://doc.qt.io/qt-6/licensing.html).

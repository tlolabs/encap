# E.N.C.A.P.

Encoder with Chapter Assembly Protocol.

E.N.C.A.P. stitches multiple WAV files into a single WAV, adds cue markers at the
boundary between each source file, and exposes the workflow through both a CLI
and a desktop GUI.

## About

This tool was built to support my students' media workflow. I'm an instructor
first, and I write code when it solves a practical problem in my classes or
media environment.

The project is shared publicly under GPLv3 for transparency and educational
use. It works for my systems and use case.

The software is provided as-is, without warranty or guaranteed support. I
maintain it as needed for my own environment. Bug reports and pull requests are
welcome, but response times may vary during the academic term.

For a full application/tool, GPLv3 fits the intent here:

- Forces derivatives to remain open.
- Prevents incorporation into proprietary systems.
- Requires source distribution if redistributed.
- Is widely respected in academic and technical communities.
- Sends a clear message: reciprocity matters.

## Features

- Sorts source WAV files by filename before stitching.
- Writes RIFF `cue ` markers and `LIST/adtl` labels named `1`, `2`, `3`, ...
- Validates WAV format consistency before concatenation.
- Prompts before converting mismatched files with `ffmpeg`.
- Writes output to a user-selected destination folder.
- Optionally writes a troubleshooting text report with marker offsets.

## Install

```bash
python3 -m pip install -e .
```

For the GUI, use a Python build that includes `tkinter`/Tk support. Some
Homebrew Python builds on macOS omit Tk by default.

## CLI

```bash
encap /path/to/source_dir --output-dir /path/to/output_dir --output-name stitched.wav
```

Use `--write-report` to emit a text report next to the output WAV.

## GUI

```bash
encap-gui
```

## License

GNU General Public License v3.0. See [LICENSE](/Users/tlothian/Documents/Projects/encap/LICENSE).

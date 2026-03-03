from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from encap.service import create_stitched_wav
    from encap.wav_tools import EncapError
else:
    from .service import create_stitched_wav
    from .wav_tools import EncapError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="encap",
        description="Stitch WAV files and write cue markers between file boundaries.",
    )
    parser.add_argument("source_dir", type=Path, help="Folder containing WAV files to stitch.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Destination folder for the stitched WAV.",
    )
    parser.add_argument(
        "--output-name",
        default="encap-output.wav",
        help="Output WAV filename.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write a marker report text file next to the output WAV.",
    )
    return parser


def prompt_for_conversion(path: Path) -> bool:
    reply = input(
        f"{path.name} does not match the first WAV file. Convert it to the reference format with ffmpeg? [y/N]: "
    ).strip()
    return reply.lower() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        plan = create_stitched_wav(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            output_name=args.output_name,
            prompt_for_conversion=prompt_for_conversion,
            write_report=args.write_report,
        )
    except EncapError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote stitched WAV: {plan.output_path}")
    if plan.report_path is not None:
        print(f"Wrote marker report: {plan.report_path}")
    if plan.markers:
        print(f"Embedded {len(plan.markers)} cue markers.")
    else:
        print("Only one source WAV was found, so no cue markers were added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

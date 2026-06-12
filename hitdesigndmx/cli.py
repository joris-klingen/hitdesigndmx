"""Command-line entry point.

    hitdmxconvert in.als                       # → in_hitnote.als, auto source
    hitdmxconvert in.als -o out.als --source legacy --target-track dmx_note
    hitdmxconvert --gui                         # launch the small GUI
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import sources
from .convert import CURRENT_TARGET, TARGETS, convert


def default_out(in_path: Path, target: str) -> Path:
    return in_path.with_name(f"{in_path.stem}_{target}{in_path.suffix}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hitdmxconvert",
        description="Convert Ableton lighting clips into the current hitnotedmx "
        "note vocabulary.",
    )
    p.add_argument("input", nargs="?", type=Path, help="source .als")
    p.add_argument("-o", "--out", type=Path, help="output .als (default: <input>_<target>.als)")
    p.add_argument(
        "--source",
        default="auto",
        choices=["auto", *sources.SOURCES],
        help="source format (default: auto-detect)",
    )
    p.add_argument("--source-track", help="name of the source track (default: auto)")
    p.add_argument("--target-track", default="dmx_note", help="name of the track to write (default: dmx_note)")
    p.add_argument(
        "--target",
        default=CURRENT_TARGET,
        choices=list(TARGETS),
        help="target note mapping (default: current)",
    )
    p.add_argument("--gui", action="store_true", help="launch the GUI")
    args = p.parse_args(argv)

    if args.gui or args.input is None:
        from .gui import launch

        launch()
        return 0

    out = args.out or default_out(args.input, args.target)
    res = convert(
        args.input,
        out,
        source=args.source,
        source_track=args.source_track,
        target_track=args.target_track,
        target=args.target,
    )
    print(
        f"[{res.source} → {res.target}] {res.clips_written}/{res.clips_in} clips, "
        f"{res.notes_written} notes → {res.out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

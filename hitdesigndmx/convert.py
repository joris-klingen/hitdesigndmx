"""Orchestration: ``.als`` (any source) → ``.als`` with a hitnotedmx note track.

    read → decode (source → IR) → encode (IR → current target notes) → write

The target encoder is pinned to the *current* hitnotedmx mapping. When that
mapping is frozen/bumped, point ``TARGETS`` at the new vocab module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import als, sources
from .vocab import hitnote_v1

# name → vocab module exposing encode() + VERSION.
TARGETS = {
    "hitnote_v1": hitnote_v1,
}
CURRENT_TARGET = "hitnote_v1"


@dataclass
class ConvertResult:
    out_path: Path
    source: str
    target: str
    clips_in: int
    clips_written: int
    notes_written: int


def convert(
    in_path: str | Path,
    out_path: str | Path,
    *,
    source: str = "auto",
    source_track: str | None = None,
    target_track: str = "dmx_note",
    target: str = CURRENT_TARGET,
) -> ConvertResult:
    in_path, out_path = Path(in_path), Path(out_path)
    root = als.read_als(in_path)

    source_name = sources.autodetect(root) if source == "auto" else source
    decoder = sources.get(source_name)
    encoder = TARGETS[target]

    src_track_el = (
        als.find_track(root, name=source_track) if source_track else None
    )
    clip_irs = decoder.decode(root, track=src_track_el)
    src_track_el = src_track_el or als.find_legacy_track(root)

    notes_by_slot = {ir.slot: encoder.encode(ir) for ir in clip_irs}
    total_notes = sum(len(n) for n in notes_by_slot.values())
    written = als.add_note_track(root, src_track_el, target_track, notes_by_slot)

    als.write_als(root, out_path)
    return ConvertResult(
        out_path=out_path,
        source=source_name,
        target=encoder.VERSION,
        clips_in=len(clip_irs),
        clips_written=written,
        notes_written=total_notes,
    )

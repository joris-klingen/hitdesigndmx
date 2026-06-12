"""Target vocabulary: the **current** hitnotedmx MIDI-note mapping (``v1``).

This module is the single source of truth for how IR intent becomes notes for
the live hitnotedmx VST. Every note number, palette index, and expressive
mapping lives here and *only* here — when hitnotedmx's mapping gets frozen /
versioned, you copy this file to ``hitnote_v2.py``, change the constants, and
point the converter at it. Nothing else in the codebase knows a note number.

Constants mirror ``hitnotedmx/Source`` (``Composition.cpp``, ``Recipes.h``,
``Palette.h``) as of this writing — octave-aligned, C3 = MIDI 60:

    0        blackout
    1..4     spots   (L-WW, L-sec, R-WW, R-sec)
    5..8     bar selectors (bar 1..4)
    12..23   pixel-zone statics
    24..35   chases
    36..47   breathes
    48..59   wild      (48 = strobe shutter)
    60..83   multicolor (self-coloured)
    84..107  primary palette   (24 colours)
    108..119 secondary palette (12 accents)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..semantic import ClipIR, LightSegment

VERSION = "hitnote_v1"

# ---- note map (mirrors hitnotedmx/Source) --------------------------------
BLACKOUT = 0
SPOT_L_WW, SPOT_L_SEC, SPOT_R_WW, SPOT_R_SEC = 1, 2, 3, 4
BAR_SELECTOR = {1: 5, 2: 6, 3: 7, 4: 8}  # physical bar (1..4) → selector note
CHASES_START, NUM_CHASES = 24, 12
BREATHES_START = 36
WILD_START = 48
STROBE = WILD_START  # 48
COLOR_DYN_START = 60
PRIMARY_PALETTE_START = 84
SECONDARY_PALETTE_START = 108
VELOCITY_THRESHOLD = 64  # hitnotedmx routes vel>=64 → primary, else secondary

# 24-colour primary palette, copied from Palette.h. Index → note is
# PRIMARY_PALETTE_START + index.
PRIMARY_PALETTE: list[tuple[float, float, float]] = [
    (0.000, 0.000, 0.000),  # 0  Black
    (1.000, 0.000, 0.000),  # 1  Red
    (1.000, 0.235, 0.000),  # 2  Orange-red
    (1.000, 0.471, 0.000),  # 3  Orange
    (1.000, 0.706, 0.000),  # 4  Amber
    (1.000, 0.902, 0.000),  # 5  Yellow
    (0.706, 1.000, 0.000),  # 6  Lime
    (0.000, 1.000, 0.000),  # 7  Green
    (0.000, 1.000, 0.471),  # 8  Mint
    (0.000, 0.784, 0.706),  # 9  Teal
    (0.000, 0.863, 1.000),  # 10 Cyan
    (0.000, 0.549, 1.000),  # 11 Sky
    (0.000, 0.000, 1.000),  # 12 Blue
    (0.235, 0.000, 0.902),  # 13 Royal
    (0.392, 0.000, 0.784),  # 14 Indigo
    (0.627, 0.000, 0.863),  # 15 Violet
    (0.745, 0.000, 0.745),  # 16 Purple
    (1.000, 0.000, 0.784),  # 17 Magenta
    (1.000, 0.392, 0.706),  # 18 Pink
    (1.000, 0.157, 0.471),  # 19 Hot pink
    (0.706, 0.000, 0.157),  # 20 Crimson
    (1.000, 0.706, 0.431),  # 21 Warm white
    (0.863, 0.902, 1.000),  # 22 Cool white
    (0.784, 0.706, 1.000),  # 23 Lavender
]
RED_INDEX = 1

# ---- expressive defaults (all freely tunable) ----------------------------
SELECTOR_VEL = 100.0  # bar/spot selectors: a fixed >=64 so the route is primary
MERGE_VEL_TOL = 6.0   # contiguous same-pitch holds merge if velocity within this


@dataclass
class Note:
    pitch: int
    start: float
    dur: float
    velocity: float = SELECTOR_VEL


# ---- colour policy (single swap point) -----------------------------------
def pick_color_index(rgb: tuple[float, float, float]) -> int:
    """Map a linear-RGB colour to a primary-palette index.

    *For now* this always returns red, per the project decision to keep colour
    trivial until the hitnotedmx mapping is frozen. When you want real colour
    matching, swap this for a nearest-neighbour search over ``PRIMARY_PALETTE``
    — nothing else changes.
    """
    return RED_INDEX


def _palette_note(rgb: tuple[float, float, float]) -> int:
    return PRIMARY_PALETTE_START + pick_color_index(rgb)


def _vel(level: float, lo: float = VELOCITY_THRESHOLD, hi: float = 127.0) -> float:
    """Map a 0..1 level onto a velocity in ``[lo, hi]`` (clamped, min 1)."""
    level = max(0.0, min(1.0, level))
    return max(1.0, round(lo + (hi - lo) * level, 3))


def _chase_for_clip(name: str) -> int:
    """Pick a chase note for this clip — varied but reproducible.

    barmode in the legacy set is "a red chase"; rather than always the same
    chase we spread across the 12-chase bank by hashing the clip name, so the
    converted set has visual variety. Deterministic, so re-runs are stable.
    """
    h = int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16)
    return CHASES_START + (h % NUM_CHASES)


def _bar_holds(bars: frozenset[int]) -> list[tuple[int, float]]:
    """Selector holds for a bar subset. Empty / all-four → none (rig default
    is 'all bars', so we only emit selectors to *restrict*)."""
    if not bars or len(bars) >= 4:
        return []
    return [(BAR_SELECTOR[b], SELECTOR_VEL) for b in sorted(bars) if b in BAR_SELECTOR]


def _segment_holds(seg: LightSegment, chase_note: int) -> list[tuple[int, float]]:
    """The (pitch, velocity) pairs held for the duration of one segment."""
    holds: list[tuple[int, float]] = []

    if seg.strobe > 0.0:
        holds.append((STROBE, _vel(seg.strobe, lo=1.0)))

    if seg.chase:
        holds.append((chase_note, _vel(seg.chase_intensity, lo=1.0)))
        holds.append((_palette_note((1.0, 0.0, 0.0)), _vel(1.0)))
        holds += _bar_holds(seg.bars)
    elif seg.color is not None and seg.brightness > 0.0:
        holds.append((_palette_note(seg.color), _vel(seg.brightness)))
        holds += _bar_holds(seg.bars)

    if seg.spots_warm:
        holds.append((SPOT_L_WW, SELECTOR_VEL))
        holds.append((SPOT_R_WW, SELECTOR_VEL))

    # A segment with no intent at all is an explicit blackout (the legacy
    # "dark" clips), so the rig actually goes dark rather than holding nothing.
    if not holds and not seg.lit:
        holds.append((BLACKOUT, SELECTOR_VEL))

    return holds


def encode(ir: ClipIR) -> list[Note]:
    """Lower one clip's IR into hitnotedmx notes.

    Contiguous same-pitch holds across adjacent segments are coalesced into a
    single sustained note (a colour held over many breakpoints becomes one
    long note, not a stutter of identical notes) — cleaner clips, same timing.
    """
    chase_note = _chase_for_clip(ir.name)

    # pitch → list of (t0, t1, vel) holds, in time order.
    holds: dict[int, list[list[float]]] = {}
    for seg in ir.segments:
        if seg.t1 <= seg.t0:
            continue
        for pitch, vel in _segment_holds(seg, chase_note):
            runs = holds.setdefault(pitch, [])
            if (
                runs
                and abs(runs[-1][1] - seg.t0) < 1e-6
                and abs(runs[-1][2] - vel) <= MERGE_VEL_TOL
            ):
                runs[-1][1] = seg.t1  # extend the open run
            else:
                runs.append([seg.t0, seg.t1, vel])

    notes: list[Note] = []
    for pitch, runs in holds.items():
        for t0, t1, vel in runs:
            t0c = max(0.0, min(t0, ir.length_beats))
            t1c = max(0.0, min(t1, ir.length_beats))
            if t1c - t0c > 1e-6:
                notes.append(Note(pitch=pitch, start=t0c, dur=t1c - t0c, velocity=vel))

    notes.sort(key=lambda n: (n.start, n.pitch))
    return notes

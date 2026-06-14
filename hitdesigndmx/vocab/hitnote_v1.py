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
    12..23   pixel-zone statics (… 21 Even, 22 Odd, 23 Thirds)
    24..35   chases
    36..47   breathes
    48..59   wild      (48 = strobe shutter)
    60..83   multicolor (self-coloured)
    84..107  primary palette   (24 colours)
    108..119 secondary palette (12 accents)

How the encoding stays faithful to the legacy intent (see the verified
composition model in ``hitnotedmx/Source/Composition.cpp``):

* **Colour** — a held primary-palette note lights the whole rig in that colour;
  ``pick_color_index`` matches the segment's hue on *normalised* RGB so a dim
  red maps to *Red* (dim), not the dark *Crimson* swatch. Intensity rides the
  note's velocity.
* **Timing** — one palette note per colour segment, onset exactly at the
  segment start. The decoder already collapsed micro-ripple, so every surviving
  boundary is a real jump and lands on the beat.
* **Dynamics** — a *bold* per-clip creative layer (chase / breathe / wild /
  multicolor + optional pixel-zone comb), chosen deterministically from the
  clip name and held only over lit spans. Brightness recipes don't touch hue,
  so they layer cleanly over the faithful colour; multicolor (which *does*
  override hue) is reserved for washed-out clips with no strong colour to keep.
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
PIXEL_EVEN, PIXEL_ODD, PIXEL_THIRDS = 21, 22, 23  # spatial combs (pixel zones)
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
BLACK_INDEX = 0
AMBER_INDEX = 4
WARM_WHITE_INDEX = 21
COOL_WHITE_INDEX = 22

# ---- expressive defaults (all freely tunable) ----------------------------
SELECTOR_VEL = 100.0   # bar/zone/spot selectors: a fixed >=64 so the route is primary
DYN_VEL = 64.0         # self-coloured Multicolor recipes (velocity → speed)
BREATHE_VEL = 56.0     # gentle Breathes: soft = patchy islands + half speed (subtle)
CHASE_VEL = 70.0       # chase tail length (soft = longer comet)
VEL_FLOOR = 50.0       # palette intensity floor → dim stays dim, fades stay short
MERGE_VEL_TOL = 6.0    # contiguous same-pitch holds merge if velocity within this
WHITE_SAT = 0.18       # below this saturation a colour is treated as white

# Curated recipe pools — kept deliberately *gentle* (Breathes / soft movers,
# no Sparkles) so the grid reads calm. They give a *calm* clip some life where
# the music isn't pumping; an energetic clip needs none (its colour does the
# work). Picked per clip by seed so re-runs are identical and each clip keeps
# its character.
CHASES = list(range(CHASES_START, CHASES_START + NUM_CHASES))      # 24..35
SUSTAINED_TEXTURE = [36, 37, 46, 47, 44]   # Breathe, Sine, Shimmer, Sway, Drift
MEDIUM_TEXTURE = [36, 37, 46, 47]          # Breathe, Sine, Shimmer, Sway
MULTICOLOR_TEXTURE = [60, 69, 70, 72, 74, 79]  # Rainbow, Ocean, Forest, Sunset, Borealis, Plasma

# Energy, not motion. The legacy rig had no spatial movement: a rhythmic clip
# is *beat-synced colour flashing* — the bars pump the matched colour on the
# beat. The decoder already segments each pulse, so the per-segment colour
# notes encode that flashing directly. ``_attacks`` is therefore an *energy*
# signal (how hard a clip pumps), used only to tell an energetic colour-pump
# clip from a calm wash — never to invent travelling regions. Bars come from
# the pan (a left/right pair); the only programmed motion is barmode → chase.
ATTACK_DELTA = 0.20   # a brightness rise this big counts as a rhythmic attack
ATTACK_MIN = 4        # clips with at least this many attacks read as energetic

# Section coherence (Phase 2). Ableton scenes name the song/section a clip
# lives under (carried into ``ClipIR.section``). We seed a clip's *shared*
# character — which recipe / chase it picks — by that section, not by the clip
# name, so a song's clips read coherently instead of each rolling independently.
#
# Section type → energy: a named section can hint how hard it should pump. This
# is a *small, explicit* table you grow as your scene-naming convention settles
# — deliberately empty for now (no guessing meaning from this set's names). Each
# entry is ``substring (lowercased) → delta on the attack threshold``: negative
# reads energetic sooner (pumps), positive stays calmer. Examples to enable once
# the vocabulary is confirmed: {"drop": -2, "tutti": -2, "chorus": -1,
# "intro": +2, "break": +2, "bass only": +2}.
SECTION_ENERGY: dict[str, int] = {}

MIN_NOTE_BEATS = 1.0 / 32.0  # drop sub-perceptual slivers (clip-edge artifacts)

# Named-cue overrides. Some clips are specific show moments whose intent the
# automation doesn't capture. "App(lause) Warm" is the calm-down moment after a
# song — a steady, not-too-bright warm wash, no movement and no fade dynamics.
APP_WARM_NOTE = PRIMARY_PALETTE_START + AMBER_INDEX  # warm yellow (Amber)
APP_WARM_VEL = 64.0  # "not so bright" — moderate, steady intensity


@dataclass
class Note:
    pitch: int
    start: float
    dur: float
    velocity: float = SELECTOR_VEL


# ---- colour policy (single swap point) -----------------------------------
def pick_color_index(rgb: tuple[float, float, float]) -> int:
    """Map a linear-RGB colour to a primary-palette index.

    Hue is matched on the *normalised* colour (divided by its max channel) so
    brightness never pulls the match toward an intrinsically dark swatch — a
    dim red resolves to *Red* (carried dim by velocity), not *Crimson*.
    Near-grey colours resolve to warm/cool white by their red/blue balance.
    Black (index 0) is never returned; darkness is handled by the caller
    gating on brightness.
    """
    hi = max(rgb)
    if hi <= 1e-6:
        return BLACK_INDEX
    if (hi - min(rgb)) / hi < WHITE_SAT:
        return WARM_WHITE_INDEX if rgb[0] >= rgb[2] else COOL_WHITE_INDEX

    cr, cg, cb = rgb[0] / hi, rgb[1] / hi, rgb[2] / hi
    best, best_d = RED_INDEX, 9.0
    for i in range(1, len(PRIMARY_PALETTE)):
        if i in (WARM_WHITE_INDEX, COOL_WHITE_INDEX):
            continue  # whites belong to the desaturated branch above
        pr, pg, pb = PRIMARY_PALETTE[i]
        pm = max(pr, pg, pb) or 1.0
        d = (cr - pr / pm) ** 2 + (cg - pg / pm) ** 2 + (cb - pb / pm) ** 2
        if d < best_d:
            best_d, best = d, i
    return best


def _palette_note(rgb: tuple[float, float, float]) -> int:
    return PRIMARY_PALETTE_START + pick_color_index(rgb)


def _vel(level: float, lo: float = VEL_FLOOR, hi: float = 127.0) -> float:
    """Map a 0..1 level onto a velocity in ``[lo, hi]`` (clamped, min 1)."""
    level = max(0.0, min(1.0, level))
    return max(1.0, round(lo + (hi - lo) * level, 3))


def _bar_holds(bars: frozenset[int]) -> list[tuple[int, float]]:
    """Selector holds for a bar subset. Empty / all-four → none (rig default
    is 'all bars', so we only emit selectors to *restrict*)."""
    if not bars or len(bars) >= 4:
        return []
    return [(BAR_SELECTOR[b], SELECTOR_VEL) for b in sorted(bars) if b in BAR_SELECTOR]


# ---- per-clip creative layer ---------------------------------------------
@dataclass
class _Plan:
    """How a clip's grid is brought to life.

    ``mode`` selects the treatment: ``static`` (one steady wash, named cues),
    ``chase`` (barmode program), ``flash`` (energetic — the per-segment colour
    notes pump on the beat under the pan bars, no invented motion), ``wash``
    (calm — pan bars + a gentle held recipe for life), or ``none``.
    """

    mode: str
    chase_note: int | None = None              # 'chase': held over barmode runs
    span_notes: list[tuple[int, float]] = None  # held over lit spans (recipe / static wash)


def _seed(name: str) -> int:
    """Deterministic seed — same name → same character every run."""
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16)


def _character_seed(ir: ClipIR) -> int:
    """Seed the clip's shared creative character. Keyed on the *section* (the
    song/section the clip lives under) so a song's clips pick a coherent recipe/
    chase family; falls back to the clip name when there's no section."""
    return _seed(ir.section or ir.name)


def _attack_threshold(ir: ClipIR) -> int:
    """How many attacks read as 'energetic' for this clip, biased by its
    section's energy (``SECTION_ENERGY``). Clamped to at least 1."""
    return max(1, ATTACK_MIN + _section_energy(ir.section))


def _section_energy(section: str) -> int:
    low = section.lower()
    for key, delta in SECTION_ENERGY.items():
        if key in low:
            return delta
    return 0


def _pick(seq: list[int], seed: int, salt: int) -> int:
    return seq[(seed >> salt) % len(seq)]


def _attacks(ir: ClipIR) -> int:
    """Count significant brightness rises across the clip (dark = 0). A single
    fade/swell scores ~0 (its staircase steps are below ATTACK_DELTA); a
    pulsing clip scores one per hit — our 'active movement' signal."""
    n = 0
    prev = 0.0
    for s in ir.segments:
        b = s.brightness if s.color is not None else 0.0
        if b - prev >= ATTACK_DELTA:
            n += 1
        prev = b
    return n


def _is_app_warm(name: str) -> bool:
    return "app warm" in name.lower()


def _clip_plan(ir: ClipIR) -> _Plan:
    """Decide the clip's bold grid character from its shape — deterministically.

    Named cues win first (e.g. App Warm → a static warm wash). Then: barmode →
    a chase; else an energetic clip (oscillating brightness) → ``flash``, where
    the per-segment colour notes pump on the beat with no invented motion; else
    a calm clip → ``wash``, a gentle held recipe for life (a self-coloured
    Multicolor recipe when washed-out, else a brightness texture sized to pace).
    """
    if _is_app_warm(ir.name):
        # Calm applause moment: steady warm wash, no movement, no fade dynamics.
        return _Plan("static", span_notes=[(APP_WARM_NOTE, APP_WARM_VEL)])

    seed = _character_seed(ir)  # shared per section, so a song coheres
    if any(s.chase for s in ir.segments):
        return _Plan("chase", chase_note=_pick(CHASES, seed, 4))

    lit = [s for s in ir.segments if s.color is not None]
    if not lit:
        return _Plan("none")

    if _attacks(ir) >= _attack_threshold(ir):
        # Energetic: let the matched colour pump on the beat under the pan bars.
        return _Plan("flash")

    # Calm clip: a gentle held recipe gives life where the music isn't pumping.
    if sum(1 for s in lit if s.is_washed_out) / len(lit) > 0.6:
        recipe = (_pick(MULTICOLOR_TEXTURE, seed, 4), DYN_VEL)
    else:
        avg_len = sum(s.t1 - s.t0 for s in lit) / len(lit)
        pool = SUSTAINED_TEXTURE if avg_len >= 2.0 else MEDIUM_TEXTURE
        recipe = (_pick(pool, seed, 4), BREATHE_VEL)
    return _Plan("wash", span_notes=[recipe])


# ---- segment + span → hold intervals -------------------------------------
def _segment_intervals(seg: LightSegment) -> list[tuple[int, float, float, float]]:
    """Per-segment holds that don't depend on the clip's plan: strobe and
    singer spots. Colour and the pan bars are emitted in ``encode``."""
    out: list[tuple[int, float, float, float]] = []
    if seg.strobe > 0.0:
        out.append((STROBE, seg.t0, seg.t1, _vel(seg.strobe, lo=1.0)))
    if seg.spots_warm:
        out.append((SPOT_L_WW, seg.t0, seg.t1, SELECTOR_VEL))
        out.append((SPOT_R_WW, seg.t0, seg.t1, SELECTOR_VEL))
    return out


def _runs(segments: list[LightSegment], pred) -> list[tuple[float, float]]:
    """Maximal contiguous time ranges where ``pred(seg)`` holds."""
    spans: list[list[float]] = []
    for s in segments:
        if not pred(s):
            continue
        if spans and abs(spans[-1][1] - s.t0) < 1e-6:
            spans[-1][1] = s.t1
        else:
            spans.append([s.t0, s.t1])
    return [(a, b) for a, b in spans]


def _emit(intervals: list[tuple[int, float, float, float]], length: float) -> list[Note]:
    """Coalesce hold intervals into notes: per pitch, sort by start and merge
    abutting runs whose velocity is within ``MERGE_VEL_TOL`` (a colour held
    across micro-segments becomes one sustained note, not a stutter)."""
    by_pitch: dict[int, list[tuple[float, float, float]]] = {}
    for pitch, t0, t1, vel in intervals:
        by_pitch.setdefault(pitch, []).append((t0, t1, vel))

    notes: list[Note] = []
    for pitch, runs in by_pitch.items():
        runs.sort()
        merged: list[list[float]] = []
        for t0, t1, vel in runs:
            if (
                merged
                and abs(merged[-1][1] - t0) < 1e-6
                and abs(merged[-1][2] - vel) <= MERGE_VEL_TOL
            ):
                merged[-1][1] = t1
            else:
                merged.append([t0, t1, vel])
        for t0, t1, vel in merged:
            t0c = max(0.0, min(t0, length))
            t1c = max(0.0, min(t1, length))
            if t1c - t0c >= MIN_NOTE_BEATS:
                notes.append(Note(pitch=pitch, start=t0c, dur=t1c - t0c, velocity=vel))

    notes.sort(key=lambda n: (n.start, n.pitch))
    return notes


def encode(ir: ClipIR) -> list[Note]:
    """Lower one clip's IR into hitnotedmx notes.

    A faithful, strictly-timed colour wash per segment composes with one bold
    layer chosen by ``_clip_plan``: a barmode chase, a beat-flashing colour
    pump (the colour notes carry it; the decoder already split each pulse), or
    a held recipe. Bars always come from the pan (a left/right pair); the only
    programmed motion is the chase. Everything is coalesced so sustained intent
    is single long notes, and no blackout note 0 is emitted (darkness = absence
    of notes, leaving singer spots untouched).
    """
    plan = _clip_plan(ir)
    intervals: list[tuple[int, float, float, float]] = []

    for seg in ir.segments:
        if seg.t1 <= seg.t0:
            continue
        intervals += _segment_intervals(seg)
        if plan.mode == "static" or seg.color is None or seg.brightness <= 0.0:
            # 'static' replaces the per-segment colour wash with a single steady
            # span note (emitted below), so skip the faithful colour here.
            continue
        intervals.append((_palette_note(seg.color), seg.t0, seg.t1, _vel(seg.brightness)))
        # Bars come from the pan in every active mode — no invented motion.
        for pitch, vel in _bar_holds(seg.bars):
            intervals.append((pitch, seg.t0, seg.t1, vel))

    if plan.span_notes:
        for a, b in _runs(ir.segments, lambda s: s.color is not None):
            for pitch, vel in plan.span_notes:
                intervals.append((pitch, a, b, vel))
    if plan.chase_note is not None:
        for a, b in _runs(ir.segments, lambda s: s.chase):
            intervals.append((plan.chase_note, a, b, CHASE_VEL))

    return _emit(intervals, ir.length_beats)

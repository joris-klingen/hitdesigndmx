"""Source decoder: the hand-programmed legacy "RGB" set (clip automation).

The legacy format is an Instrument-Rack-driven MIDI track: each clip automates
the rack's Macro Controls, and the rack is mapped (opaquely, inside Live) to a
DMX plugin. So a clip is really per-macro automation. The macros are named by
the user:

    BAR Switch        → continuous L↔R pan across the bars
    VOX SPOT white    → singer spots, warm-white
    Red / Green / Blue→ bar pixel colour level
    Strobe            → strobe
    barmode def 0 !   → red chase overlay (when raised)
    mode speed        → effect speed

This decoder reuses the proven parsing approach from the original
``hitmixdmx/lightgen/legacy_convert.py`` (macro reading, envelope sampling,
segment boundaries) but lowers to the neutral IR instead of DMXIS automation.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .. import als
from ..semantic import ClipIR, LightSegment

# MacroDisplayNames value → role
MACRO_ROLES = {
    "BAR Switch": "bar_pan",
    "VOX SPOT white": "vox",
    "Red": "r",
    "Green": "g",
    "Blue": "b",
    "Strobe": "strobe",
    "barmode def 0 !": "barmode",
    "mode speed": "barspeed",
}
OPTIONAL_ROLES = {"barspeed"}  # absent in older racks → defaults to manual knob
REQUIRED_ROLES = set(MACRO_ROLES.values()) - OPTIONAL_ROLES

LIVE_PREROLL_TIME = -63072000.0  # sentinel Live writes for "value at clip start"
MACRO_FULL_SCALE = 127.0

# Thresholds carried over from the original converter so behaviour matches.
BARMODE_THRESHOLD = 0.05  # barmode above this → chase overlay on the wash
COLOR_ON = 0.02           # brightness above this → bars are considered lit
SPOT_ON = 0.02            # vox above this → singer spots on
PAN_LEFT = 0.35           # pan below → left bars only
PAN_RIGHT = 0.65          # pan above → right bars only

# Significance thresholds for collapsing micro-ripple while keeping strict
# timing on real jumps. Two adjacent segments merge only when every structural
# attribute matches AND the colour barely moved: brightness within TAU_L and
# normalised-chroma direction within TAU_CHROMA. A jump bigger than either,
# or any on↔off / structural change, stays a hard boundary.
TAU_L = 0.12       # brightness step below this is "not a real jump"
TAU_CHROMA = 0.20  # normalised-RGB direction change below this is "same hue"


@dataclass
class _Env:
    """Sorted (time, value) automation for one macro, normalised to 0..1.

    Ableton clip envelopes are piecewise **linear** between breakpoints, with an
    instantaneous step encoded as two breakpoints at the same time. ``sample``
    therefore interpolates and, at a step, returns the value *after* the jump
    (the right-hand limit) — so a segment whose start coincides with a step sees
    the post-step value, and a ramp is read as the ramp, not held flat."""

    points: list[tuple[float, float]] = field(default_factory=list)

    def sample(self, t: float) -> float:
        pts = self.points
        if not pts:
            return 0.0
        if t >= pts[-1][0]:
            return pts[-1][1]
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if t1 <= t:          # interval ends at/before t → step past it
                continue
            if t0 > t:           # t precedes the first interval → clamp left
                return v0
            if t1 > t0:          # t0 <= t < t1, real (non-zero-width) interval
                return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        return pts[-1][1]


def _read_macros(rack: ET.Element) -> tuple[dict[int, str], dict[str, float]]:
    """({AutomationTarget Id → role}, {role → manual knob value 0..1})."""
    roles: dict[int, str] = {}
    defaults: dict[str, float] = {}
    for idx in range(16):
        name_el = rack.find(f"MacroDisplayNames.{idx}")
        macro_el = rack.find(f"MacroControls.{idx}")
        if name_el is None or macro_el is None:
            continue
        role = MACRO_ROLES.get(name_el.get("Value", ""))
        if role is None:
            continue
        at = macro_el.find("AutomationTarget")
        if at is None:
            continue
        roles[int(at.get("Id"))] = role
        manual = macro_el.find("Manual")
        if manual is not None:
            defaults[role] = _clamp01(float(manual.get("Value")) / MACRO_FULL_SCALE)
    return roles, defaults


def _parse_envelopes(clip: ET.Element, roles: dict[int, str]) -> dict[str, _Env]:
    out: dict[str, _Env] = {}
    for env in clip.findall(".//Envelopes/Envelopes/ClipEnvelope"):
        pid_el = env.find("EnvelopeTarget/PointeeId")
        if pid_el is None:
            continue
        role = roles.get(int(pid_el.get("Value")))
        if role is None:
            continue
        points: list[tuple[float, float]] = []
        for fe in env.findall("Automation/Events/FloatEvent"):
            t = float(fe.get("Time"))
            v = _clamp01(float(fe.get("Value")) / MACRO_FULL_SCALE)
            if t <= LIVE_PREROLL_TIME + 1:  # preroll sentinel → clip start
                t = 0.0
            points.append((t, v))
        points.sort(key=lambda p: p[0])
        out[role] = _Env(points=points)
    return out


# Ramp resolution: between breakpoints, sample on this beat grid so a linear
# fade is broken into a staircase the encoder can render as climbing-velocity
# notes (Ableton fades are linear, not stepped). The significance merge then
# collapses the flats back, so only genuine ramps keep the extra steps.
SUBGRID_BEATS = 0.5

# Quantize every segment boundary to this grid (1/16 note) so all emitted notes
# land on-grid; sub-grid noise between two boundaries that round together is
# dropped. Snapping here (rather than at note time) keeps segments contiguous,
# so notes never overlap after quantizing.
QUANTIZE_BEATS = 0.25


def _boundaries(macros: dict[str, _Env], length: float) -> list[float]:
    def q(t: float) -> float:
        return round(round(t / QUANTIZE_BEATS) * QUANTIZE_BEATS, 6)

    times = {0.0, q(length)}
    for env in macros.values():
        for pt, _ in env.points:
            if 0.0 <= pt <= length:
                times.add(q(pt))
    g = SUBGRID_BEATS
    n = 1
    while n * g < length:
        times.add(q(n * g))
        n += 1
    return sorted(t for t in times if t <= length)


def _pan_to_bars(pan: float) -> frozenset[int]:
    if pan < PAN_LEFT:
        return frozenset({1, 2})
    if pan > PAN_RIGHT:
        return frozenset({3, 4})
    return frozenset()  # centred → all bars


def _chroma(rgb: tuple[float, float, float] | None) -> tuple[float, float, float]:
    """Normalised colour direction (unit by max channel); black → origin."""
    if rgb is None:
        return (0.0, 0.0, 0.0)
    m = max(rgb)
    if m <= 1e-6:
        return (0.0, 0.0, 0.0)
    return (rgb[0] / m, rgb[1] / m, rgb[2] / m)


def _structural_key(seg: LightSegment) -> tuple:
    """Everything that, if changed, forces a hard segment boundary regardless
    of how small the colour move is."""
    return (seg.bars, seg.chase, seg.spots_warm, seg.strobe > 0.0)


def _mergeable(a: LightSegment, b: LightSegment) -> bool:
    """True if b is just micro-ripple on top of a — same structure, both lit
    (or both dark), and colour barely moved."""
    if _structural_key(a) != _structural_key(b):
        return False
    if (a.color is None) != (b.color is None):
        return False
    if a.color is None:  # both dark, same structure → same segment
        return True
    if abs(a.brightness - b.brightness) >= TAU_L:
        return False
    ca, cb = _chroma(a.color), _chroma(b.color)
    dist = sum((x - y) ** 2 for x, y in zip(ca, cb)) ** 0.5
    return dist < TAU_CHROMA


def _merge(segs: list[LightSegment]) -> list[LightSegment]:
    """Collapse runs of micro-ripple into single held segments. The first
    segment of a run defines the held value (curves are stepped), so the kept
    onset time is exact — strict timing on every surviving (real) jump."""
    out: list[LightSegment] = []
    for seg in segs:
        if out and _mergeable(out[-1], seg):
            out[-1].t1 = seg.t1  # extend the held segment over the ripple
        else:
            out.append(seg)
    return out


def _interpret(name: str, length: float, macros: dict[str, _Env]) -> list[LightSegment]:
    bnds = _boundaries(macros, length)
    segs: list[LightSegment] = []
    for t0, t1 in zip(bnds, bnds[1:]):
        if t1 <= t0:
            continue
        r = macros["r"].sample(t0)
        g = macros["g"].sample(t0)
        b = macros["b"].sample(t0)
        pan = macros["bar_pan"].sample(t0)
        vox = macros["vox"].sample(t0)
        strobe = macros["strobe"].sample(t0)
        barmode = macros["barmode"].sample(t0)
        barspeed = macros["barspeed"].sample(t0)

        seg = LightSegment(
            t0=t0,
            t1=t1,
            bars=_pan_to_bars(pan),
            strobe=strobe if strobe > 0.0 else 0.0,
            spots_warm=vox > SPOT_ON,
        )
        # Keep the wash colour whether or not barmode is raised — barmode adds
        # a chase *on top of* the colour rather than replacing it.
        if max(r, g, b) >= COLOR_ON:
            seg.color = (r, g, b)
        if barmode > BARMODE_THRESHOLD:
            seg.chase = True
            # speed knob drives the chase if present, else fall back to barmode.
            seg.chase_intensity = barspeed if barspeed > 0.0 else barmode
        segs.append(seg)
    return _merge(segs)


def decode(root: ET.Element, *, track: ET.Element | None = None) -> list[ClipIR]:
    """Lower every populated clip on the legacy track into a ``ClipIR``."""
    src = track if track is not None else als.find_legacy_track(root)
    rack = src.find(".//InstrumentGroupDevice")
    if rack is None:
        raise RuntimeError("selected track has no Instrument Rack — not a legacy set")
    roles, defaults = _read_macros(rack)
    missing = REQUIRED_ROLES - set(roles.values())
    if missing:
        raise RuntimeError(
            f"legacy rack is missing macro(s) for {sorted(missing)}; "
            f"expected named macros {sorted(MACRO_ROLES)}"
        )

    scenes = als.scene_names(root)
    sections = _inherit_sections(scenes)  # slot → song/section it belongs to

    out: list[ClipIR] = []
    for slot_idx, slot in enumerate(als.clip_slots(src)):
        clip = als.slot_clip(slot)
        if clip is None:
            continue
        name = clip.find("Name").get("Value")
        length = float(clip.find("Loop/LoopEnd").get("Value"))
        macros = _parse_envelopes(clip, roles)
        for role in MACRO_ROLES.values():
            macros.setdefault(role, _Env(points=[(0.0, defaults.get(role, 0.0))]))
        out.append(
            ClipIR(
                name=name,
                slot=slot_idx,
                length_beats=length,
                segments=_interpret(name, length, macros),
                scene=scenes[slot_idx] if slot_idx < len(scenes) else "",
                section=sections[slot_idx] if slot_idx < len(sections) else "",
                source_clip=copy.deepcopy(clip),
            )
        )
    return out


def _inherit_sections(scene_names: list[str]) -> list[str]:
    """Carry each named scene forward over the unnamed scenes beneath it, so
    every slot resolves to the song/section marker it lives under (the standard
    Ableton convention: a name marks a start, blank scenes belong to it)."""
    out: list[str] = []
    current = ""
    for name in scene_names:
        if name:
            current = name
        out.append(current)
    return out


def detect(root: ET.Element) -> bool:
    """True if this document looks like a legacy macro set."""
    try:
        als.find_legacy_track(root)
        return True
    except RuntimeError:
        return False


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))

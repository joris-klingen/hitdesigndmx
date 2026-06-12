"""Convert a hand-programmed "RGB" Ableton set into a pixel-based lightgen Spec.

The source format is a different rig than DMXIS-direct: a MIDI track whose clip
envelopes automate the Macro Controls of an Instrument Rack, and the rack is
mapped (inside Live, opaquely to us) to a DMX plugin. Each clip therefore
boils down to per-macro automation. The macros are named by the user:

    Macro 0  Master Dim       (ignored — driven from hardware knob)
    Macro 1  BAR Switch       → continuous L↔R pan across the two bars
    Macro 2  WASH Warm        (ignored)
    Macro 3  VOX SPOT white   → singer spots, warm-white
    Macro 4  Red              → bar pixel red
    Macro 5  Green            → bar pixel green
    Macro 6  Blue             → bar pixel blue
    Macro 7  Strobe           → wild random RGB chase on bars
    Macro 9,10,11             (ignored)

Macro values are 0..127 in the source; we normalise to 0..1.

Output: a `Spec` against the standard `hitmix` rig, expressing each segment of
constant macro values as `Fade` events with equal start/end (i.e. clean stepped
automation) on each pixel, plus per-clip seeded pattern masks so the pixel
distribution varies per clip.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .als_io import TemplateInfo
from .spec import (
    Breathe,
    Chase,
    Clip,
    ColorHold,
    ColorStab,
    Comet,
    Fade,
    PulsePattern,
    Pulse,
    Sparkle,
    Spec,
)


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
"""Mapping from MacroDisplayNames.N value → semantic role used by the converter."""

OPTIONAL_ROLES = {"barspeed"}
"""Roles that may be absent in older legacy racks without raising. Their
clip envelopes simply default to 0 / the rack's manual knob position."""

LIVE_PREROLL_TIME = -63072000.0
"""Sentinel time value Live writes for the "value at clip start" event."""

MACRO_FULL_SCALE = 127.0


@dataclass
class MacroEnvelope:
    """Sorted (time, value) list for one macro on one clip, in 0..1 space."""

    role: str
    points: list[tuple[float, float]] = field(default_factory=list)

    def sample(self, t: float) -> float:
        """Value at time `t` — rightmost point with point_time <= t (post-jump)."""
        if not self.points:
            return 0.0
        chosen = self.points[0][1]
        for pt, pv in self.points:
            if pt <= t + 1e-9:
                chosen = pv
            else:
                break
        return chosen


@dataclass
class LegacyClip:
    name: str
    slot: int
    length_beats: float
    color_index: int
    macros: dict[str, MacroEnvelope]
    source_xml: ET.Element | None = None
    """Deep-copy of the source <MidiClip> XML, kept so we can carry forward
    TimeSignature / Loop / CurrentStart / CurrentEnd into the rendered output."""

    def segment_boundaries(self) -> list[float]:
        """Union of all macro event times in [0, length_beats], inclusive of 0 and end."""
        times = {0.0, self.length_beats}
        for env in self.macros.values():
            for pt, _ in env.points:
                if 0.0 <= pt <= self.length_beats:
                    times.add(pt)
        return sorted(times)


def _read_macros(rack: ET.Element) -> tuple[dict[int, str], dict[str, float]]:
    """Return ({AT_id → role}, {role → manual_value_normalized}) for the role macros.

    The manual value is the rack's "current knob position" and is used by Live
    when a clip has no envelope for that macro. We capture it so clips that
    don't automate (say) BAR Switch still get a sensible default rather than 0.
    """
    roles: dict[int, str] = {}
    defaults: dict[str, float] = {}
    for idx in range(16):
        name_el = rack.find(f"MacroDisplayNames.{idx}")
        macro_el = rack.find(f"MacroControls.{idx}")
        if name_el is None or macro_el is None:
            continue
        display_name = name_el.get("Value", "")
        role = MACRO_ROLES.get(display_name)
        if role is None:
            continue
        at = macro_el.find("AutomationTarget")
        if at is None:
            continue
        roles[int(at.get("Id"))] = role
        manual = macro_el.find("Manual")
        if manual is not None:
            v = max(0.0, min(1.0, float(manual.get("Value")) / MACRO_FULL_SCALE))
            defaults[role] = v
    return roles, defaults


def _parse_clip_envelopes(
    clip_xml: ET.Element, roles: dict[int, str]
) -> dict[str, MacroEnvelope]:
    """Pull out the subset of envelopes whose target is one of our role macros."""
    out: dict[str, MacroEnvelope] = {}
    for env in clip_xml.findall(".//Envelopes/Envelopes/ClipEnvelope"):
        pid_el = env.find("EnvelopeTarget/PointeeId")
        if pid_el is None:
            continue
        at_id = int(pid_el.get("Value"))
        role = roles.get(at_id)
        if role is None:
            continue
        points: list[tuple[float, float]] = []
        for fe in env.findall("Automation/Events/FloatEvent"):
            t = float(fe.get("Time"))
            v = float(fe.get("Value")) / MACRO_FULL_SCALE
            v = max(0.0, min(1.0, v))
            # Live's preroll sentinel: treat as t=0 for our segmentation purposes.
            if t <= LIVE_PREROLL_TIME + 1:
                t = 0.0
            points.append((t, v))
        points.sort(key=lambda p: p[0])
        out[role] = MacroEnvelope(role=role, points=points)
    return out


def read_legacy_clips(path: str | Path, *, track_index: int = 0) -> list[LegacyClip]:
    """Read all populated clips from the given track in a legacy .als."""
    with gzip.open(Path(path), "rb") as f:
        root = ET.fromstring(f.read())
    tracks = list(root.find("LiveSet/Tracks"))
    track = tracks[track_index]
    rack = track.find(".//InstrumentGroupDevice")
    if rack is None:
        raise RuntimeError(
            f"track {track_index} has no InstrumentGroupDevice — "
            "is this the legacy macro-driven track?"
        )
    roles, defaults = _read_macros(rack)
    missing = set(MACRO_ROLES.values()) - OPTIONAL_ROLES - set(roles.values())
    if missing:
        raise RuntimeError(
            f"could not resolve macros for roles {sorted(missing)} — "
            f"check that MacroDisplayNames match: {sorted(MACRO_ROLES)}"
        )
    clips: list[LegacyClip] = []
    for slot_idx, slot in enumerate(track.findall(".//ClipSlotList/ClipSlot")):
        clip_xml = slot.find("ClipSlot/Value/MidiClip")
        if clip_xml is None:
            continue
        name = clip_xml.find("Name").get("Value")
        length = float(clip_xml.find("Loop/LoopEnd").get("Value"))
        color = int(clip_xml.find("Color").get("Value"))
        macros = _parse_clip_envelopes(clip_xml, roles)
        for role in MACRO_ROLES.values():
            if role not in macros:
                macros[role] = MacroEnvelope(
                    role=role, points=[(0.0, defaults.get(role, 0.0))]
                )
        clips.append(
            LegacyClip(
                name=name,
                slot=slot_idx,
                length_beats=length,
                color_index=color,
                macros=macros,
                source_xml=copy.deepcopy(clip_xml),
            )
        )
    return clips


CLIP_PROPS_TO_COPY = ("TimeSignature", "Loop", "CurrentStart", "CurrentEnd")
"""Top-level <MidiClip> sub-elements we replace with the source's copy after
render, so the output preserves the user's time signature and loop layout
instead of inheriting them from the template's clone source."""


def patch_clip_properties(
    template: TemplateInfo,
    legacy_clips: list[LegacyClip],
    *,
    slot_offset: int = 0,
) -> None:
    """Carry source-clip properties (time sig, loop) into the rendered output."""
    for lc in legacy_clips:
        if lc.source_xml is None:
            continue
        slot = template.clip_slots[slot_offset + lc.slot]
        out_clip = slot.find("ClipSlot/Value/MidiClip")
        if out_clip is None:
            continue
        for tag in CLIP_PROPS_TO_COPY:
            src_el = lc.source_xml.find(tag)
            out_el = out_clip.find(tag)
            if src_el is None or out_el is None:
                continue
            idx = list(out_clip).index(out_el)
            out_clip.remove(out_el)
            out_clip.insert(idx, copy.deepcopy(src_el))


# --- Output layouts -------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """Maps the legacy converter's logical concepts onto a target rig.

    Two `mode`s are supported:

      - "pixel": bars are RGB pixel strips. BAR Switch pans L↔R; per-pixel
        masks decorate each segment; barmode triggers a red chase; the
        strobe macro fires random RGB stabs across pixels.

      - "ledbar7": bars are single-RGB-unit 7-channel fixtures (R/G/B/Dim/
        Strobe/Mode/Speed). BAR Switch hard-switches between bar-selection
        patterns (single/cycle, pairs, odd/even, all). Barmode → Mode
        channel of all bars; mode speed → Speed; strobe → Strobe (all
        applied to every bar, color is only driven on selected bars).

    `pixels_per_bar` is ignored when mode == "ledbar7".
    """

    rig_name: str
    bar_fixtures: tuple[str, ...]
    spot_fixtures: tuple[str, str]
    pixels_per_bar: int = 1
    mode: str = "pixel"


HITMIX_LAYOUT = Layout(
    rig_name="hitmix",
    bar_fixtures=("left_bar", "right_bar"),
    spot_fixtures=("singer_left", "singer_right"),
    pixels_per_bar=18,
    mode="pixel",
)

HITMIX_EXTENDED_4X2_LAYOUT = Layout(
    rig_name="hitmix_extended",
    bar_fixtures=("bar_1", "bar_2", "bar_3", "bar_4"),
    spot_fixtures=("spot_l", "spot_r"),
    pixels_per_bar=2,
    mode="pixel",
)

HITMIX_4BAR_7CH_LAYOUT = Layout(
    rig_name="hitmix_4bar_7ch",
    bar_fixtures=("bar_1", "bar_2", "bar_3", "bar_4"),
    spot_fixtures=("spot_l", "spot_r"),
    mode="ledbar7",
)

HITMIX_EXTENDED_SPARSE_9X4_LAYOUT = Layout(
    rig_name="hitmix_extended",
    bar_fixtures=("bar_1", "bar_2", "bar_3", "bar_4"),
    spot_fixtures=("spot_l", "spot_r"),
    pixels_per_bar=9,
    mode="sparse_grid",
)

HITMIX_EXTENDED_REDESIGN_9X4_LAYOUT = Layout(
    rig_name="hitmix_extended",
    bar_fixtures=("bar_1", "bar_2", "bar_3", "bar_4"),
    spot_fixtures=("spot_l", "spot_r"),
    pixels_per_bar=9,
    mode="redesign",
)

LAYOUTS: dict[str, Layout] = {
    "hitmix": HITMIX_LAYOUT,
    "hitmix-extended-4x2": HITMIX_EXTENDED_4X2_LAYOUT,
    "hitmix-4bar-7ch": HITMIX_4BAR_7CH_LAYOUT,
    "hitmix-extended-sparse-9x4": HITMIX_EXTENDED_SPARSE_9X4_LAYOUT,
    "hitmix-extended-redesign-9x4": HITMIX_EXTENDED_REDESIGN_9X4_LAYOUT,
}


# --- Pattern masks --------------------------------------------------------

PATTERN_NAMES = [
    "solid",
    "blocks_3",
    "blocks_6",
    "alternating",
    "every_third",
    "every_fourth",
    "halves",
    "thirds",
    "edges",
    "center",
    "random_50",
    "random_30",
    "ramp_up",
    "ramp_down",
]


def _pattern_mask(name: str, rng: random.Random, n: int) -> list[float]:
    """Per-pixel multiplier in [0, 1] for the named pattern. Length `n`."""
    if name == "solid":
        return [1.0] * n
    if name == "blocks_3":
        return [1.0 if ((p - 1) // 3) % 2 == 0 else 0.0 for p in range(1, n + 1)]
    if name == "blocks_6":
        return [1.0 if ((p - 1) // 6) % 2 == 0 else 0.0 for p in range(1, n + 1)]
    if name == "alternating":
        return [1.0 if (p - 1) % 2 == 0 else 0.0 for p in range(1, n + 1)]
    if name == "every_third":
        return [1.0 if (p - 1) % 3 == 0 else 0.0 for p in range(1, n + 1)]
    if name == "every_fourth":
        return [1.0 if (p - 1) % 4 == 0 else 0.0 for p in range(1, n + 1)]
    if name == "halves":
        return [1.0 if p <= n // 2 else 0.0 for p in range(1, n + 1)]
    if name == "thirds":
        return [1.0 if (p - 1) < n // 3 or (p - 1) >= 2 * n // 3 else 0.0 for p in range(1, n + 1)]
    if name == "edges":
        return [1.0 if p <= 3 or p > n - 3 else 0.0 for p in range(1, n + 1)]
    if name == "center":
        return [1.0 if (n // 2 - 3) < p <= (n // 2 + 3) else 0.0 for p in range(1, n + 1)]
    if name == "random_50":
        return [1.0 if rng.random() < 0.5 else 0.0 for _ in range(n)]
    if name == "random_30":
        return [1.0 if rng.random() < 0.3 else 0.0 for _ in range(n)]
    if name == "ramp_up":
        return [p / n for p in range(1, n + 1)]
    if name == "ramp_down":
        return [(n - p + 1) / n for p in range(1, n + 1)]
    raise ValueError(f"unknown pattern {name!r}")


def _seeded_rng(clip_name: str) -> random.Random:
    """Deterministic per-clip RNG. Same name → same pattern."""
    h = hashlib.sha1(clip_name.encode("utf-8")).digest()
    seed = int.from_bytes(h[:8], "big")
    return random.Random(seed)


# --- Conversion -----------------------------------------------------------

# Warm-white tint for the singer spots — paired with the white channel at full.
WARM_R = 0.4
WARM_G = 0.15
STROBE_COLOR: tuple[float, float, float] = (1.0, 1.0, 1.0)
"""Strobe is always white — the user's lights handle hue elsewhere."""
STROBE_MAX_RATE_PER_BEAT = 24.0
STROBE_FLASH_DUR = 0.04

# Sparse-grid strobe cadence: stabs lock to a 1/16-note grid (max 4 per
# beat). Probability of firing on each tick scales with the macro value.
SPARSE_STROBE_TICK_BEATS = 0.25  # 1/16 note in beats
SPARSE_STROBE_FLASH_DUR = 0.06

BARMODE_THRESHOLD = 0.05
"""barmode macro value above which the red chase replaces the static bar color."""
BARMODE_CHASE_STEP = 0.08
"""Beats between adjacent pixels in the chase sweep."""
BARMODE_CHASE_DURATION = 0.18
"""Beats each pixel stays lit during the chase — slight overlap for a smooth trail."""
BARMODE_CHASE_PERIOD = 1.5
"""Beats between consecutive sweep starts."""
BARMODE_RED_TINT: tuple[float, float, float] = (1.0, 0.15, 0.0)
"""Predominantly red, mild orange — multiplied by the live barmode value for intensity."""


def _bar_gains(bar_pan: float, n_bars: int) -> tuple[float, ...]:
    """Linear L↔R pan across `n_bars` bars.

    The bar list is split into a left half (first n_bars // 2) and a right
    half (remaining). All left bars get gain `1 - bar_pan`; all right bars
    get `bar_pan`. Reduces to the original 2-bar case when n_bars == 2.
    With an odd count the extra middle bar joins the right half.
    """
    half = n_bars // 2
    left_gain = 1.0 - bar_pan
    right_gain = bar_pan
    return tuple(left_gain if i < half else right_gain for i in range(n_bars))


COLOR_SWITCH_COSINE = 0.7
"""Cosine similarity below this triggers a new pattern — a "large color switch"."""

PAN_SWITCH_THRESHOLD = 0.15
"""BAR Switch delta in normalised (0..1) space that counts as a flip."""

INTENSITY_PULSE_THRESHOLD = 0.8
"""Single-step brightness delta that counts as a "pulse" even within one color."""


def _color_similarity(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Cosine similarity between two RGB triples. Returns 1.0 if either is off,
    so on↔off transitions don't count as a color switch — the same hue pulsing
    keeps its pattern."""
    ma = (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5
    mb = (b[0] * b[0] + b[1] * b[1] + b[2] * b[2]) ** 0.5
    if ma < 1e-6 or mb < 1e-6:
        return 1.0
    return (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (ma * mb)


def _clip_to_events(clip: LegacyClip, layout: Layout, *, hint=None) -> list:
    # Hint wins over everything (including App Warm name) when it carries
    # pre-rendered LLM-generated events. See `Hint.rendered_events`.
    if hint is not None and getattr(hint, "rendered_events", None) is not None:
        return list(hint.rendered_events)

    # In-between-songs clip overrides — apply to pixel-grid layouts only.
    # These trigger only when no hint exists for the slot.
    if layout.mode in ("pixel", "sparse_grid", "redesign"):
        name = clip.name.strip().lower()
        if name == "app warm":
            return _app_warm_events(clip, layout, intensity=0.20, coverage=0.50)
        if name == "app warm low":
            return _app_warm_events(clip, layout, intensity=0.10, coverage=0.30)
        if name == "app warm full":
            return _app_warm_events(clip, layout, intensity=0.40, coverage=0.75)
        if name == "warm":
            return _plain_warm_events(clip, layout)
    if layout.mode == "ledbar7":
        return _clip_to_events_ledbar7(clip, layout)
    if layout.mode == "sparse_grid":
        return _clip_to_events_sparse_grid(clip, layout)
    if layout.mode == "redesign":
        return _clip_to_events_redesign(clip, layout, hint=hint)
    return _clip_to_events_pixel(clip, layout)


# --- in-between-songs overrides ------------------------------------------
#
# `App Warm` (and its low/full variants): hold black for 2 beats, then
# fade to dim warm yellow on ~50% of pixels over 1 bar, then hold. Spots
# stay full warm-white throughout. Loop bounds carried from source XML.
# `Warm` (no App prefix): mellow warm color from t=0, no blackout, no fade.

APP_WARM_BLACKOUT_BEATS = 2.0
APP_WARM_FADE_BEATS = 4.0  # one bar at 4/4
WARM_YELLOW_BASE: tuple[float, float, float] = (1.0, 0.6, 0.15)
WARM_CELL_SEED = 0xAB05E
"""Fixed seed for the cell-selection RNG so every App Warm clip lights
the same recognizable pattern — feels like the same light cue."""


def _select_warm_cells(layout: Layout, coverage: float) -> set[tuple[int, int]]:
    """Deterministic ~`coverage` fraction of grid cells (0-indexed bar, 1-9 pixel)."""
    rng = random.Random(WARM_CELL_SEED)
    n_bars = len(layout.bar_fixtures)
    n_px = layout.pixels_per_bar
    all_cells = [(b, p) for b in range(n_bars) for p in range(1, n_px + 1)]
    n_lit = max(1, int(round(len(all_cells) * coverage)))
    return set(rng.sample(all_cells, n_lit))


def _full_warm_spot_events(t0: float, t1: float, layout: Layout) -> list:
    """Spots forced full warm-white (Dim=1, White=1, R=WARM_R, G=WARM_G)."""
    out: list = []
    for spot in layout.spot_fixtures:
        for comp, val in (
            ("dimmer", 1.0),
            ("white", 1.0),
            ("red", WARM_R),
            ("green", WARM_G),
        ):
            out.append(
                Fade(
                    type="fade",
                    fixture=spot,
                    component=comp,
                    t_start=t0,
                    t_end=t1,
                    value_start=val,
                    value_end=val,
                )
            )
    return out


def _app_warm_events(
    clip: LegacyClip,
    layout: Layout,
    *,
    intensity: float,
    coverage: float,
) -> list:
    """Blackout → 1-bar fade up → hold. Spots full warm-white throughout.

    `intensity` scales the final brightness (e.g. 0.20 for the standard
    App Warm); `coverage` controls what fraction of the grid is lit.
    """
    length = clip.length_beats
    bo_end = min(APP_WARM_BLACKOUT_BEATS, length)
    fade_end = min(bo_end + APP_WARM_FADE_BEATS, length)
    target = tuple(c * intensity for c in WARM_YELLOW_BASE)
    lit = _select_warm_cells(layout, coverage)

    out: list = []
    for bar_idx, fixture in enumerate(layout.bar_fixtures):
        for p in range(1, layout.pixels_per_bar + 1):
            if (bar_idx, p) in lit:
                if bo_end > 0:
                    out.append(Fade(
                        type="fade", fixture=fixture, pixel=p, component="rgb",
                        t_start=0.0, t_end=bo_end,
                        color_start=(0.0, 0.0, 0.0), color_end=(0.0, 0.0, 0.0),
                    ))
                if fade_end > bo_end:
                    out.append(Fade(
                        type="fade", fixture=fixture, pixel=p, component="rgb",
                        t_start=bo_end, t_end=fade_end,
                        color_start=(0.0, 0.0, 0.0), color_end=target,
                    ))
                if length > fade_end:
                    out.append(Fade(
                        type="fade", fixture=fixture, pixel=p, component="rgb",
                        t_start=fade_end, t_end=length,
                        color_start=target, color_end=target,
                    ))
            else:
                out.append(Fade(
                    type="fade", fixture=fixture, pixel=p, component="rgb",
                    t_start=0.0, t_end=length,
                    color_start=(0.0, 0.0, 0.0), color_end=(0.0, 0.0, 0.0),
                ))
    out.extend(_full_warm_spot_events(0.0, length, layout))
    return out


def _plain_warm_events(clip: LegacyClip, layout: Layout) -> list:
    """Instant mellow warm color from t=0. No blackout, no fade."""
    length = clip.length_beats
    target = tuple(c * 0.25 for c in WARM_YELLOW_BASE)
    lit = _select_warm_cells(layout, 0.50)

    out: list = []
    for bar_idx, fixture in enumerate(layout.bar_fixtures):
        for p in range(1, layout.pixels_per_bar + 1):
            color = target if (bar_idx, p) in lit else (0.0, 0.0, 0.0)
            out.append(Fade(
                type="fade", fixture=fixture, pixel=p, component="rgb",
                t_start=0.0, t_end=length,
                color_start=color, color_end=color,
            ))
    out.extend(_full_warm_spot_events(0.0, length, layout))
    return out


def _clip_to_events_pixel(clip: LegacyClip, layout: Layout) -> list:
    boundaries = clip.segment_boundaries()
    rng = _seeded_rng(clip.name)
    n_bars = len(layout.bar_fixtures)

    # Pattern re-rolls on any of:
    #  - BAR Switch swing
    #  - large color-identity change (cosine-similarity drop)
    #  - large brightness pulse (delta > threshold) even within one color
    # Smooth modulation of a single hue at steady intensity keeps the same LEDs.
    masks: list[list[float]] | None = None
    last_nonzero_color: tuple[float, float, float] | None = None
    last_pan: float | None = None
    last_brightness = 0.0

    events: list = []
    for t0, t1 in zip(boundaries, boundaries[1:]):
        if t1 <= t0:
            continue
        r = clip.macros["r"].sample(t0)
        g = clip.macros["g"].sample(t0)
        b = clip.macros["b"].sample(t0)
        bar_pan = clip.macros["bar_pan"].sample(t0)
        vox = clip.macros["vox"].sample(t0)
        strobe = clip.macros["strobe"].sample(t0)
        barmode = clip.macros["barmode"].sample(t0)
        color = (r, g, b)
        brightness = max(r, g, b)
        color_is_on = brightness >= 0.02

        trigger = masks is None
        if not trigger and last_pan is not None and abs(bar_pan - last_pan) > PAN_SWITCH_THRESHOLD:
            trigger = True
        if (
            not trigger
            and color_is_on
            and last_nonzero_color is not None
            and _color_similarity(color, last_nonzero_color) < COLOR_SWITCH_COSINE
        ):
            trigger = True
        if not trigger and abs(brightness - last_brightness) > INTENSITY_PULSE_THRESHOLD:
            trigger = True

        if trigger:
            pattern_name = rng.choice(PATTERN_NAMES)
            masks = [
                _pattern_mask(pattern_name, rng, layout.pixels_per_bar)
                for _ in range(n_bars)
            ]

        if color_is_on:
            last_nonzero_color = color
        last_pan = bar_pan
        last_brightness = brightness

        if barmode > BARMODE_THRESHOLD:
            # Suppress the static bar color and overlay a red chase. The 0-fades
            # ensure the previous segment's color doesn't bleed through.
            events.extend(_bar_segment_events(t0, t1, 0.0, 0.0, 0.0, bar_pan, masks, layout))
            events.extend(_barmode_chase_events(t0, t1, barmode, layout))
        else:
            events.extend(_bar_segment_events(t0, t1, r, g, b, bar_pan, masks, layout))
        events.extend(_spot_segment_events(t0, t1, vox, layout))
        if strobe > 0:
            events.extend(_strobe_segment_events(t0, t1, strobe, rng, layout))
    return events


# --- ledbar7 mode --------------------------------------------------------

BAR_PATTERN_SETS: dict[str, tuple[int, ...]] = {
    "two_left":  (0, 1),
    "two_right": (2, 3),
    "odd":       (0, 2),
    "even":      (1, 3),
    "outer":     (0, 3),
    "inner":     (1, 2),
    "all":       (0, 1, 2, 3),
}
"""Fixed bar-index sets a `BarSelector` can pick on a hard switch."""

BAR_PATTERN_NAMES: tuple[str, ...] = (
    "next",          # advance through singles, one per switch
    "single_random", # one random bar
    "two_left",
    "two_right",
    "odd",
    "even",
    "outer",
    "inner",
    "all",
)


@dataclass
class BarSelector:
    """Stateful chooser: which bars are active on a hard switch.

    Each `pick()` returns a fresh set of 0-based bar indices, drawn from
    `BAR_PATTERN_NAMES`. `next` cycles through individual bars one at a
    time (so successive `next` picks walk 0 → 1 → 2 → 3 → 0); the others
    map to fixed pairs/groups. RNG is the same clip-seeded one used for
    pixel-mode pattern masks, so output is deterministic per clip.
    """

    rng: random.Random
    n_bars: int = 4
    _cycle_index: int = 0

    def pick(self) -> set[int]:
        choice = self.rng.choice(BAR_PATTERN_NAMES)
        if choice == "next":
            chosen = {self._cycle_index % self.n_bars}
            self._cycle_index += 1
            return chosen
        if choice == "single_random":
            return {self.rng.randrange(self.n_bars)}
        return {i for i in BAR_PATTERN_SETS[choice] if i < self.n_bars}


def _clip_to_events_ledbar7(clip: LegacyClip, layout: Layout) -> list:
    """Convert a clip for the ledbar7 layout: hard-switched bar selection +
    direct Mode/Speed/Strobe channel drive."""
    boundaries = clip.segment_boundaries()
    rng = _seeded_rng(clip.name)
    selector = BarSelector(rng=rng, n_bars=len(layout.bar_fixtures))

    active_bars: set[int] | None = None
    last_pan: float | None = None
    last_nonzero_color: tuple[float, float, float] | None = None
    last_brightness = 0.0

    events: list = []
    for t0, t1 in zip(boundaries, boundaries[1:]):
        if t1 <= t0:
            continue
        r = clip.macros["r"].sample(t0)
        g = clip.macros["g"].sample(t0)
        b = clip.macros["b"].sample(t0)
        bar_pan = clip.macros["bar_pan"].sample(t0)
        vox = clip.macros["vox"].sample(t0)
        strobe = clip.macros["strobe"].sample(t0)
        barmode = clip.macros["barmode"].sample(t0)
        barspeed = clip.macros["barspeed"].sample(t0)
        color = (r, g, b)
        brightness = max(r, g, b)
        color_is_on = brightness >= 0.02

        # Same triggers as pixel mode: BAR Switch swing, big color change,
        # or a brightness pulse — any of these picks a new bar set.
        trigger = active_bars is None
        if (
            not trigger
            and last_pan is not None
            and abs(bar_pan - last_pan) > PAN_SWITCH_THRESHOLD
        ):
            trigger = True
        if (
            not trigger
            and color_is_on
            and last_nonzero_color is not None
            and _color_similarity(color, last_nonzero_color) < COLOR_SWITCH_COSINE
        ):
            trigger = True
        if (
            not trigger
            and abs(brightness - last_brightness) > INTENSITY_PULSE_THRESHOLD
        ):
            trigger = True

        if trigger:
            active_bars = selector.pick()
        assert active_bars is not None  # set above on first iteration

        if color_is_on:
            last_nonzero_color = color
        last_pan = bar_pan
        last_brightness = brightness

        events.extend(
            _bar_ledbar7_segment_events(
                t0, t1, r, g, b, active_bars, barmode, barspeed, strobe, layout
            )
        )
        events.extend(_spot_segment_events(t0, t1, vox, layout))
    return events


def _bar_ledbar7_segment_events(
    t0: float,
    t1: float,
    r: float,
    g: float,
    b: float,
    active: set[int],
    barmode: float,
    barspeed: float,
    strobe: float,
    layout: Layout,
) -> list:
    """One stepped segment of RGB + mode/speed/strobe across all bars.

    Color and dimmer go only to `active` bars (the BAR Switch pattern
    selects which). Mode/Speed/Strobe go to every bar — when the macro
    user sweeps mode or strobe, all 4 fixtures respond identically.
    """
    out: list = []
    for i, fixture in enumerate(layout.bar_fixtures):
        is_on = 1.0 if i in active else 0.0
        bar_color = (r * is_on, g * is_on, b * is_on)
        out.append(
            Fade(
                type="fade",
                fixture=fixture,
                component="rgb",
                t_start=t0,
                t_end=t1,
                color_start=bar_color,
                color_end=bar_color,
            )
        )
        for component, value in (
            ("dimmer", is_on),
            ("strobe", strobe),
            ("mode", barmode),
            ("speed", barspeed),
        ):
            out.append(
                Fade(
                    type="fade",
                    fixture=fixture,
                    component=component,
                    t_start=t0,
                    t_end=t1,
                    value_start=value,
                    value_end=value,
                )
            )
    return out


# --- pixel mode helpers --------------------------------------------------


def _bar_segment_events(
    t0: float,
    t1: float,
    r: float,
    g: float,
    b: float,
    bar_pan: float,
    masks: list[list[float]],
    layout: Layout,
) -> list:
    gains = _bar_gains(bar_pan, len(layout.bar_fixtures))
    out: list = []
    for fixture, gain, mask in zip(layout.bar_fixtures, gains, masks):
        for p in range(1, layout.pixels_per_bar + 1):
            m = mask[p - 1] * gain
            color = (r * m, g * m, b * m)
            out.append(
                Fade(
                    type="fade",
                    fixture=fixture,
                    pixel=p,
                    component="rgb",
                    t_start=t0,
                    t_end=t1,
                    color_start=color,
                    color_end=color,
                )
            )
    return out


def _spot_segment_events(t0: float, t1: float, vox: float, layout: Layout) -> list:
    """Warm-white singers, brightness scaled by vox. Color channels held at warm tint."""
    out: list = []
    for fixture in layout.spot_fixtures:
        for component, value in (
            ("dimmer", vox),
            ("white", 1.0 if vox > 0 else 0.0),
            ("red", WARM_R if vox > 0 else 0.0),
            ("green", WARM_G if vox > 0 else 0.0),
        ):
            out.append(
                Fade(
                    type="fade",
                    fixture=fixture,
                    component=component,
                    t_start=t0,
                    t_end=t1,
                    value_start=value,
                    value_end=value,
                )
            )
    return out


def _barmode_chase_events(t0: float, t1: float, intensity: float, layout: Layout) -> list:
    """Predominantly-red sweep across all bars while barmode is on.

    Emits per-pixel `color_stab`s staggered by `BARMODE_CHASE_STEP` beats and
    repeating every `BARMODE_CHASE_PERIOD` beats. Stabs are bounded to the
    segment so they don't leak into adjacent (barmode-off) segments.
    """
    tr, tg, tb = BARMODE_RED_TINT
    color = (tr * intensity, tg * intensity, tb * intensity)
    out: list = []
    sweep_t = t0
    while sweep_t < t1 - 1e-6:
        for p in range(1, layout.pixels_per_bar + 1):
            stab_t = sweep_t + (p - 1) * BARMODE_CHASE_STEP
            if stab_t >= t1 - 1e-6:
                break
            dur = min(BARMODE_CHASE_DURATION, t1 - stab_t - 1e-6)
            if dur <= 0:
                continue
            for fixture in layout.bar_fixtures:
                out.append(
                    ColorStab(
                        type="color_stab",
                        fixture=fixture,
                        pixel=p,
                        time=stab_t,
                        duration=dur,
                        color=color,
                    )
                )
        sweep_t += BARMODE_CHASE_PERIOD
    return out


def _strobe_segment_events(
    t0: float, t1: float, strobe: float, rng: random.Random, layout: Layout
) -> list:
    """Wild random RGB chase across bar pixels. Density scales with strobe value."""
    duration = t1 - t0
    n_stabs = max(1, int(round(strobe * STROBE_MAX_RATE_PER_BEAT * duration)))
    out: list = []
    for _ in range(n_stabs):
        t = t0 + rng.uniform(0.0, duration)
        fixture = rng.choice(layout.bar_fixtures)
        pixel = rng.randint(1, layout.pixels_per_bar)
        dur = min(STROBE_FLASH_DUR, t1 - t - 1e-6)
        if dur <= 0:
            continue
        out.append(
            ColorStab(
                type="color_stab",
                fixture=fixture,
                pixel=pixel,
                time=t,
                duration=dur,
                color=STROBE_COLOR,
            )
        )
    return out


# --- sparse_grid mode ----------------------------------------------------
#
# Treats the 4-column × 9-row pixel grid as a 2-D canvas. Picks small grid
# segments (≤25% of cells) and alternates between them on every beat (and
# at every source automation boundary). The result is much darker and
# "alive" rather than the floodlit pixel-mode output.

SPARSE_COLOR_DELTA_THRESHOLD = 0.4
"""Max per-component RGB delta needed to trigger a fresh segment shape.
Smaller deltas keep the current segment so source automation rhythm is
preserved without forcing the grid pattern to flicker on every event."""

SPARSE_MIN_DWELL_BEATS = 2.0
"""Minimum beats a segment shape persists before another shape switch is
allowed. Throttles dense automation into a calmer visual rhythm."""

BARMODE_CHASE_COLOR: tuple[float, float, float] = (1.0, 0.05, 0.0)
"""Red-only chase color. Multiplied by the barmode macro intensity."""

BARMODE_CHASE_STEP = 0.25
"""Beats between successive chase pixel hits (1/16 note)."""

BARMODE_CHASE_DUR = 0.4
"""Beats each chase pixel stays lit. Slight overlap with the next cell."""

BARMODE_CHASE_STYLES = (
    "serpentine_col",   # walk column 1 bottom→top, column 2 top→bottom, ...
    "serpentine_row",   # row 1 L→R, row 2 R→L, ...
    "columns_bottom_up",# all columns bottom→top in lockstep, col by col
    "rows_left_right",  # all rows L→R in lockstep, row by row
)


def _grid_segments() -> dict[str, list[tuple[int, int]]]:
    """Pre-baked grid segments. Each is a list of (bar_idx 0..3, pixel 1..9).

    Sized for sparseness — most cover 4-9 cells (~11-25% of the 36-cell
    grid), with a few smaller "accent" sets in the 3-4 cell range.
    """
    s: dict[str, list[tuple[int, int]]] = {}
    s["lower_left"]  = [(b, p) for b in (0, 1) for p in (1, 2, 3, 4)]
    s["lower_right"] = [(b, p) for b in (2, 3) for p in (1, 2, 3, 4)]
    s["upper_left"]  = [(b, p) for b in (0, 1) for p in (5, 6, 7, 8, 9)]
    s["upper_right"] = [(b, p) for b in (2, 3) for p in (5, 6, 7, 8, 9)]
    s["bottom_2"]    = [(b, p) for b in range(4) for p in (1, 2)]
    s["top_2"]       = [(b, p) for b in range(4) for p in (8, 9)]
    s["middle_2"]    = [(b, p) for b in range(4) for p in (5, 6)]
    s["row_1"]       = [(b, 1) for b in range(4)]
    s["row_3"]       = [(b, 3) for b in range(4)]
    s["row_5"]       = [(b, 5) for b in range(4)]
    s["row_7"]       = [(b, 7) for b in range(4)]
    s["row_9"]       = [(b, 9) for b in range(4)]
    s["col_1_lower"] = [(0, p) for p in range(1, 6)]
    s["col_1_upper"] = [(0, p) for p in range(5, 10)]
    s["col_2_lower"] = [(1, p) for p in range(1, 6)]
    s["col_2_upper"] = [(1, p) for p in range(5, 10)]
    s["col_3_lower"] = [(2, p) for p in range(1, 6)]
    s["col_3_upper"] = [(2, p) for p in range(5, 10)]
    s["col_4_lower"] = [(3, p) for p in range(1, 6)]
    s["col_4_upper"] = [(3, p) for p in range(5, 10)]
    s["corners"]     = [(0, 1), (0, 9), (3, 1), (3, 9)]
    s["center_box"]  = [(1, 4), (2, 4), (1, 5), (2, 5), (1, 6), (2, 6)]
    s["outer_cols"]  = [(0, p) for p in range(2, 9)] + [(3, p) for p in range(2, 9)]
    s["inner_cols"]  = [(1, p) for p in range(3, 8)] + [(2, p) for p in range(3, 8)]
    s["diag_down"]   = [(0, 8), (1, 6), (2, 4), (3, 2)]
    s["diag_up"]     = [(0, 2), (1, 4), (2, 6), (3, 8)]
    s["vee_low"]     = [(0, 5), (1, 2), (2, 2), (3, 5)]
    s["vee_high"]    = [(0, 4), (1, 7), (2, 7), (3, 4)]
    s["zigzag"]      = [(0, 1), (1, 3), (2, 1), (3, 3), (0, 5), (2, 5)]
    s["odd_cols_lo"] = [(0, p) for p in range(1, 5)] + [(2, p) for p in range(1, 5)]
    s["even_cols_hi"]= [(1, p) for p in range(6, 10)] + [(3, p) for p in range(6, 10)]
    s["scatter_a"]   = [(0, 3), (1, 7), (2, 2), (3, 8), (1, 5)]
    s["scatter_b"]   = [(0, 7), (1, 2), (2, 8), (3, 3), (2, 5)]
    s["accent_4"]    = [(0, 5), (1, 1), (2, 9), (3, 5)]
    return s


SPARSE_SEGMENTS = _grid_segments()
SPARSE_SEGMENT_NAMES = tuple(SPARSE_SEGMENTS)


def _color_delta(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Max per-component RGB delta between two colors (∈ [0, 1])."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _pick_sparse_segment(
    rng: random.Random, last_name: str | None
) -> tuple[str, list[tuple[int, int]]]:
    """Pick a fresh segment, biased away from repeating last_name."""
    candidates = [n for n in SPARSE_SEGMENT_NAMES if n != last_name]
    name = rng.choice(candidates)
    return name, SPARSE_SEGMENTS[name]


def _clip_to_events_sparse_grid(clip: LegacyClip, layout: Layout) -> list:
    """Source-driven sparse grid conversion.

    Iterates source automation intervals (no forced beat-switching).
    Segment shape is re-rolled only when the source RGB color changes by
    more than `SPARSE_COLOR_DELTA_THRESHOLD` per component AND at least
    `SPARSE_MIN_DWELL_BEATS` have passed since the last switch. Within a
    held segment, the color value still tracks every source interval —
    only the lit-cell layout is sticky. Per-cell brightness and halo
    selection are fixed for the entire clip so the lit pattern doesn't
    shimmer between sub-segments.

    Barmode → sparse multi-color chase. Strobe → grid-wide scatter +
    spot Strobe channel.
    """
    rng = _seeded_rng(clip.name)
    boundaries = clip.segment_boundaries()

    # Per-clip stable cell gain + halo. Computed once so the lit pattern
    # has a consistent texture throughout the clip.
    n_bars = len(layout.bar_fixtures)
    n_px = layout.pixels_per_bar
    all_cells = [(b, p) for b in range(n_bars) for p in range(1, n_px + 1)]
    cell_gain_map: dict[tuple[int, int], float] = {
        c: rng.uniform(SPARSE_CELL_GAIN_MIN, SPARSE_CELL_GAIN_MAX) for c in all_cells
    }
    halo_gain_map: dict[tuple[int, int], float] = {
        c: rng.uniform(SPARSE_HALO_GAIN_MIN, SPARSE_HALO_GAIN_MAX)
        for c in all_cells
        if rng.random() < SPARSE_HALO_PROB
    }

    last_segment_name: str | None = None
    last_segment_cells: list[tuple[int, int]] = []
    last_segment_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    last_switch_t: float = float("-inf")

    events: list = []
    for t0, t1 in zip(boundaries, boundaries[1:]):
        if t1 <= t0:
            continue
        r = clip.macros["r"].sample(t0)
        g = clip.macros["g"].sample(t0)
        b = clip.macros["b"].sample(t0)
        vox = clip.macros["vox"].sample(t0)
        strobe = clip.macros["strobe"].sample(t0)
        barmode = clip.macros["barmode"].sample(t0)
        color = (r, g, b)

        # Change-gated re-roll: only switch shape if the source color has
        # moved meaningfully AND the previous shape has been held long
        # enough. Otherwise: keep the shape, let color follow source.
        delta = _color_delta(color, last_segment_color)
        dwell = t0 - last_switch_t
        should_switch = last_segment_name is None or (
            delta > SPARSE_COLOR_DELTA_THRESHOLD and dwell >= SPARSE_MIN_DWELL_BEATS
        )
        if should_switch:
            seg_name, cells = _pick_sparse_segment(rng, last_segment_name)
            last_segment_name = seg_name
            last_segment_cells = cells
            last_switch_t = t0
        last_segment_color = color

        events.extend(_sparse_bar_segment_events(
            t0, t1, r, g, b, last_segment_cells, layout,
            cell_gain_map, halo_gain_map,
        ))
        events.extend(_spot_segment_events(t0, t1, vox, layout))
        if strobe > 0:
            events.extend(_sparse_strobe_events(t0, t1, strobe, rng, layout))
        if barmode > BARMODE_THRESHOLD:
            events.extend(_sparse_barmode_chase_events(t0, t1, barmode, rng, layout))
    return events


SPARSE_CELL_GAIN_MIN = 0.55
SPARSE_CELL_GAIN_MAX = 1.0
"""Per-cell brightness range (tightened — was 0.35..1.0 before). Lit cells
are mostly bright, with mild variation, instead of a wide-range shimmer."""

SPARSE_HALO_PROB = 0.05
SPARSE_HALO_GAIN_MIN = 0.08
SPARSE_HALO_GAIN_MAX = 0.18
"""Small fraction of out-of-segment cells get a faint "halo" glow. Lowered
probability (was 0.15) — fewer stray dim pixels for a cleaner look."""


def _sparse_bar_segment_events(
    t0: float,
    t1: float,
    r: float,
    g: float,
    b: float,
    cells: list[tuple[int, int]],
    layout: Layout,
    cell_gain_map: dict[tuple[int, int], float],
    halo_gain_map: dict[tuple[int, int], float],
) -> list:
    """Light cells in `cells` using pre-computed per-cell brightness; the
    rest are dark, except halo cells (also pre-computed) at low brightness.

    Per-cell maps come from the caller and are FIXED for the entire clip,
    so the lit pattern doesn't shimmer between sub-segments. Within a
    segment span, every pixel gets a Fade — active cells at source color
    × cell_gain, halo cells at source color × halo_gain, others black.
    Emitting all pixels (not just the active ones) is required so that
    previously-lit pixels turn off cleanly at the boundary.
    """
    on = set(cells)
    out: list = []
    for bar_idx, fixture in enumerate(layout.bar_fixtures):
        for p in range(1, layout.pixels_per_bar + 1):
            cell = (bar_idx, p)
            if cell in on:
                m = cell_gain_map.get(cell, 1.0)
            elif cell in halo_gain_map:
                m = halo_gain_map[cell]
            else:
                m = 0.0
            color = (r * m, g * m, b * m)
            out.append(
                Fade(
                    type="fade",
                    fixture=fixture,
                    pixel=p,
                    component="rgb",
                    t_start=t0,
                    t_end=t1,
                    color_start=color,
                    color_end=color,
                )
            )
    return out


def _sparse_strobe_events(
    t0: float, t1: float, strobe: float, rng: random.Random, layout: Layout
) -> list:
    """Plain white sparkles on a 1/16-note grid + spot Strobe channel.

    Stabs are bound to integer multiples of `SPARSE_STROBE_TICK_BEATS`
    (0.25 = 1/16 note), giving a safe ~4 stabs/beat upper limit. On each
    tick, a stab fires with probability ∝ `strobe` macro value (so at
    full strobe every tick fires; at half, ~50% of ticks). Each stab
    lights a random (bar, pixel) for `SPARSE_STROBE_FLASH_DUR` beats in
    pure white. The spots' Strobe DMX channel is held at the macro value.
    """
    out: list = []
    n_bars = len(layout.bar_fixtures)
    n_px = layout.pixels_per_bar

    # Snap up to the first 1/16 tick at or after t0.
    first_tick_index = int((t0 + 1e-9) / SPARSE_STROBE_TICK_BEATS)
    if first_tick_index * SPARSE_STROBE_TICK_BEATS < t0 - 1e-9:
        first_tick_index += 1
    t = first_tick_index * SPARSE_STROBE_TICK_BEATS

    while t < t1 - 1e-6:
        if rng.random() < strobe:
            bar_idx = rng.randrange(n_bars)
            pixel = rng.randint(1, n_px)
            dur = min(SPARSE_STROBE_FLASH_DUR, t1 - t - 1e-6)
            if dur > 0:
                out.append(
                    ColorStab(
                        type="color_stab",
                        fixture=layout.bar_fixtures[bar_idx],
                        pixel=pixel,
                        time=t,
                        duration=dur,
                        color=STROBE_COLOR,
                    )
                )
        t += SPARSE_STROBE_TICK_BEATS

    # Spot strobe channel held at the macro value for the segment.
    for spot in layout.spot_fixtures:
        out.append(
            Fade(
                type="fade",
                fixture=spot,
                component="strobe",
                t_start=t0,
                t_end=t1,
                value_start=strobe,
                value_end=strobe,
            )
        )
    return out


def _barmode_chase_path(style: str, n_bars: int, n_px: int) -> list[tuple[int, int]]:
    """Ordered list of (bar_idx, pixel) cells defining the chase trajectory.

    Each style traces all cells of the grid in a different geometric order
    (serpentine, lockstep columns, lockstep rows). The chase walks this
    list step by step; when it reaches the end it wraps to the beginning,
    so a long barmode-on span loops cleanly.
    """
    cells: list[tuple[int, int]] = []
    if style == "serpentine_col":
        for b in range(n_bars):
            rows = range(1, n_px + 1) if b % 2 == 0 else range(n_px, 0, -1)
            for p in rows:
                cells.append((b, p))
    elif style == "serpentine_row":
        for p in range(1, n_px + 1):
            cols = range(n_bars) if p % 2 == 0 else range(n_bars - 1, -1, -1)
            for b in cols:
                cells.append((b, p))
    elif style == "columns_bottom_up":
        for b in range(n_bars):
            for p in range(1, n_px + 1):
                cells.append((b, p))
    elif style == "rows_left_right":
        for p in range(1, n_px + 1):
            for b in range(n_bars):
                cells.append((b, p))
    else:
        raise ValueError(f"unknown chase style {style!r}")
    return cells


def _sparse_barmode_chase_events(
    t0: float, t1: float, intensity: float, rng: random.Random, layout: Layout
) -> list:
    """Structured red chase across the full grid.

    One of `BARMODE_CHASE_STYLES` is chosen per call (deterministic via the
    clip RNG). The chase walks the grid one cell per `BARMODE_CHASE_STEP`
    beats, each cell lit for `BARMODE_CHASE_DUR` beats. Color is fixed red
    × macro intensity — no multi-color cycling. Wraps to the start once it
    exhausts the cell list, so long barmode-on spans loop continuously.
    """
    style = rng.choice(BARMODE_CHASE_STYLES)
    n_bars = len(layout.bar_fixtures)
    n_px = layout.pixels_per_bar
    cells = _barmode_chase_path(style, n_bars, n_px)
    cr, cg, cb = BARMODE_CHASE_COLOR
    color = (cr * intensity, cg * intensity, cb * intensity)

    out: list = []
    t = t0
    i = 0
    while t < t1 - 1e-6:
        bar_idx, pixel = cells[i % len(cells)]
        dur = min(BARMODE_CHASE_DUR, t1 - t - 1e-6)
        if dur > 0:
            out.append(
                ColorStab(
                    type="color_stab",
                    fixture=layout.bar_fixtures[bar_idx],
                    pixel=pixel,
                    time=t,
                    duration=dur,
                    color=color,
                )
            )
        t += BARMODE_CHASE_STEP
        i += 1
    return out


# --- redesign mode -------------------------------------------------------
#
# A fresh-design pass that ignores the source RGB segment shapes entirely
# and instead picks one movement-focused design per clip (chases, breathes,
# comets, etc.), tinted with the source's dominant color. Source VOX SPOT,
# strobe, and barmode envelopes are tracked precisely as overlays on top.
# Switches are kept to a minimum — the design plays continuously across
# the whole clip and just loops naturally if the clip is long.


REDESIGN_DARK_BRIGHTNESS_THRESHOLD = 0.05
"""Per-segment brightness below this counts as 'dark' for color averaging."""

REDESIGN_FALLBACK_COLOR: tuple[float, float, float] = (0.0, 0.0, 0.0)
"""Color emitted when source was completely dark — rule 8: stay dark."""

SCATTER_SPARKLE_FRACTION = 0.10
"""Fraction of grid cells lit at any 1/16 tick at full strobe macro.
~10% of 36 cells = 3-4 cells flashing at once, refreshed each tick."""


def _dominant_color(clip: LegacyClip) -> tuple[float, float, float]:
    """Duration-weighted average of the source's non-dark color samples.

    Iterates each source automation interval, samples RGB at its start,
    and accumulates time-weighted color contributions from intervals
    brighter than `REDESIGN_DARK_BRIGHTNESS_THRESHOLD`. If the whole clip
    is dark, returns the fallback (also dark) so the redesign respects
    rule 8: never invent light when the source had none.
    """
    boundaries = clip.segment_boundaries()
    if len(boundaries) < 2:
        return REDESIGN_FALLBACK_COLOR
    sum_r = sum_g = sum_b = 0.0
    weight = 0.0
    for t0, t1 in zip(boundaries, boundaries[1:]):
        if t1 <= t0:
            continue
        r = clip.macros["r"].sample(t0)
        g = clip.macros["g"].sample(t0)
        b = clip.macros["b"].sample(t0)
        if max(r, g, b) <= REDESIGN_DARK_BRIGHTNESS_THRESHOLD:
            continue
        dt = t1 - t0
        sum_r += r * dt
        sum_g += g * dt
        sum_b += b * dt
        weight += dt
    if weight < 1e-6:
        return REDESIGN_FALLBACK_COLOR
    return (sum_r / weight, sum_g / weight, sum_b / weight)


def _macro_intervals(
    clip: LegacyClip, role: str
) -> list[tuple[float, float, float]]:
    """List of (t_start, t_end, value) intervals for a macro envelope.

    Spans the full [0, length] range. Within each interval the macro
    value is constant (matches Live's stepped automation semantics that
    `MacroEnvelope.sample` already implements)."""
    env = clip.macros[role]
    times: set[float] = {0.0, clip.length_beats}
    for t, _ in env.points:
        if 0 <= t <= clip.length_beats:
            times.add(t)
    sorted_t = sorted(times)
    out: list[tuple[float, float, float]] = []
    for t0, t1 in zip(sorted_t, sorted_t[1:]):
        if t1 > t0:
            out.append((t0, t1, env.sample(t0)))
    return out


def _redesign_spot_events(clip: LegacyClip, layout: Layout) -> list:
    """Spot Fades tracking the source VOX SPOT envelope precisely."""
    out: list = []
    for t0, t1, vox in _macro_intervals(clip, "vox"):
        out.extend(_spot_segment_events(t0, t1, vox, layout))
    return out


def _redesign_strobe_overlay(
    clip: LegacyClip, layout: Layout, rng: random.Random
) -> list:
    """Scattered white sparkles during strobe-active spans.

    Uses the on/off timing of the source strobe macro envelope only; the
    visual is always the same scatter pattern (~`SCATTER_SPARKLE_FRACTION`
    of grid cells lit at any 1/16 tick, refreshed each tick).
    """
    out: list = []
    for t0, t1, strobe in _macro_intervals(clip, "strobe"):
        if strobe > 0:
            out.extend(_scatter_sparkle_events(t0, t1, strobe, rng, layout))
    return out


def _scatter_sparkle_events(
    t0: float, t1: float, strobe: float, rng: random.Random, layout: Layout
) -> list:
    """About `SCATTER_SPARKLE_FRACTION * strobe` of the grid is lit at any
    1/16 tick, refreshed each tick. Plain white, safe DMX rate. Also
    drives the spots' Strobe channel from the macro value.
    """
    n_bars = len(layout.bar_fixtures)
    n_px = layout.pixels_per_bar
    n_cells = n_bars * n_px
    cells_per_tick = max(1, int(round(SCATTER_SPARKLE_FRACTION * strobe * n_cells)))

    first_tick = int((t0 + 1e-9) / SPARSE_STROBE_TICK_BEATS)
    if first_tick * SPARSE_STROBE_TICK_BEATS < t0 - 1e-9:
        first_tick += 1
    t = first_tick * SPARSE_STROBE_TICK_BEATS

    out: list = []
    while t < t1 - 1e-6:
        # rng.sample is uniform without replacement → no double-hits on the
        # same cell within one tick.
        picks = rng.sample(range(n_cells), min(cells_per_tick, n_cells))
        for idx in picks:
            bar_idx, off = divmod(idx, n_px)
            pixel = off + 1
            dur = min(SPARSE_STROBE_TICK_BEATS, t1 - t - 1e-6)
            if dur > 0:
                out.append(
                    ColorStab(
                        type="color_stab",
                        fixture=layout.bar_fixtures[bar_idx],
                        pixel=pixel, time=t, duration=dur,
                        color=STROBE_COLOR,
                    )
                )
        t += SPARSE_STROBE_TICK_BEATS

    for spot in layout.spot_fixtures:
        out.append(
            Fade(type="fade", fixture=spot, component="strobe",
                 t_start=t0, t_end=t1,
                 value_start=strobe, value_end=strobe)
        )
    return out


# --- Design library ------------------------------------------------------
#
# Each design is a function (length, color, layout, rng) → list[Event].
# Designs prefer movement (chase / comet / breathe / pulse) over color
# switching — within one clip, the color stays the same throughout. Beat-
# aligned periods (1.0, 2.0, 4.0) keep the motion locked to the clip's
# musical pulse.


def _is_dark_color(color: tuple[float, float, float]) -> bool:
    return max(color) <= REDESIGN_DARK_BRIGHTNESS_THRESHOLD


def _dim(color: tuple[float, float, float], k: float) -> tuple[float, float, float]:
    return (color[0] * k, color[1] * k, color[2] * k)


def _design_bottom_up_chase(length, color, layout, rng):
    return [
        Chase(type="chase", fixture=bar, t_start=i * 0.25, step=0.5,
              duration=0.6, color=color, period=4.0, t_end=length)
        for i, bar in enumerate(layout.bar_fixtures)
    ]


def _design_top_down_rain(length, color, layout, rng):
    return [
        Comet(type="comet", fixture=bar, t_start=i * 0.25, step=0.35,
              tail_beats=1.2, color=color, reverse=True,
              period=4.0, t_end=length)
        for i, bar in enumerate(layout.bar_fixtures)
    ]


def _design_diagonal_sweep(length, color, layout, rng):
    return [
        Comet(type="comet", fixture=bar, t_start=i * 1.0, step=0.4,
              tail_beats=1.5, color=color, period=8.0, t_end=length)
        for i, bar in enumerate(layout.bar_fixtures)
    ]


def _design_heartbeat_pulse(length, color, layout, rng):
    return [
        PulsePattern(type="pulse_pattern", fixture=bar, pixel="*",
                     component="rgb", t_start=0, t_end=length, period=4.0,
                     pulses=[Pulse(offset=0.0, duration=0.25),
                             Pulse(offset=0.6, duration=0.25)],
                     color=color)
        for bar in layout.bar_fixtures
    ]


def _design_slow_breath(length, color, layout, rng):
    cycles = max(1, int(round(length / 8.0)))  # ~1 cycle per 2 bars
    return [
        Breathe(type="breathe", fixture=bar, pixel="*", component="rgb",
                t_start=0, t_end=length, v_min=0.05, v_max=0.8,
                cycles=cycles, color=color)
        for bar in layout.bar_fixtures
    ]


def _design_inhale_exhale(length, color, layout, rng):
    out: list = []
    half = length / 2
    for bar in layout.bar_fixtures:
        out.append(Fade(type="fade", fixture=bar, pixel="*", component="rgb",
                        t_start=0, t_end=half,
                        color_start=(0, 0, 0), color_end=color))
        out.append(Fade(type="fade", fixture=bar, pixel="*", component="rgb",
                        t_start=half, t_end=length,
                        color_start=color, color_end=(0, 0, 0)))
    return out


def _design_quarter_pulse(length, color, layout, rng):
    return [
        PulsePattern(type="pulse_pattern", fixture=bar, pixel="*",
                     component="rgb", t_start=0, t_end=length, period=1.0,
                     pulses=[Pulse(offset=0.0, duration=0.25)],
                     color=color)
        for bar in layout.bar_fixtures
    ]


def _design_corner_pulses(length, color, layout, rng):
    out: list = []
    pixels = (1, layout.pixels_per_bar)
    for bar in (layout.bar_fixtures[0], layout.bar_fixtures[-1]):
        for p in pixels:
            out.append(PulsePattern(
                type="pulse_pattern", fixture=bar, pixel=p,
                component="rgb", t_start=0, t_end=length, period=2.0,
                pulses=[Pulse(offset=0.0, duration=0.6)], color=color,
            ))
    return out


def _design_center_glow(length, color, layout, rng):
    cycles = max(1, int(round(length / 8.0)))
    center_pixels = (layout.pixels_per_bar // 2,
                     layout.pixels_per_bar // 2 + 1)
    return [
        Breathe(type="breathe", fixture=bar, pixel=p, component="rgb",
                t_start=0, t_end=length, v_min=0.1, v_max=0.7,
                cycles=cycles, color=color)
        for bar in layout.bar_fixtures
        for p in center_pixels
    ]


def _design_horizon(length, color, layout, rng):
    out: list = []
    n_px = layout.pixels_per_bar
    cycles = max(1, int(round(length / 8.0)))
    half = n_px // 2
    for bar in layout.bar_fixtures:
        for p in range(1, half + 1):
            out.append(Breathe(type="breathe", fixture=bar, pixel=p,
                               component="rgb", t_start=0, t_end=length,
                               v_min=0.1, v_max=0.6, cycles=cycles, color=color))
        for p in range(half + 1, n_px + 1):
            out.append(Breathe(type="breathe", fixture=bar, pixel=p,
                               component="rgb", t_start=0, t_end=length,
                               v_min=0.05, v_max=0.3, cycles=cycles,
                               color=_dim(color, 0.6)))
    return out


def _design_ambient_chase(length, color, layout, rng):
    out: list = [
        ColorHold(type="color_hold", fixture=bar, pixel="*",
                  t_start=0, t_end=length, color=_dim(color, 0.15))
        for bar in layout.bar_fixtures
    ]
    out.extend([
        Chase(type="chase", fixture=bar, t_start=i * 0.5, step=0.4,
              duration=0.5, color=color, period=4.0, t_end=length)
        for i, bar in enumerate(layout.bar_fixtures)
    ])
    return out


def _design_glittering_stars(length, color, layout, rng):
    return [
        Sparkle(type="sparkle", fixture=bar, t_start=0, t_end=length,
                density=0.5, duration=0.5, color=color,
                seed=rng.randint(0, 2**31 - 1))
        for bar in layout.bar_fixtures
    ]


def _design_alternating_columns(length, color, layout, rng):
    out: list = []
    for i, bar in enumerate(layout.bar_fixtures):
        period = 4.0 if i % 2 == 0 else 2.0
        out.append(PulsePattern(
            type="pulse_pattern", fixture=bar, pixel="*",
            component="rgb", t_start=0, t_end=length, period=period,
            pulses=[Pulse(offset=0.0, duration=period * 0.4)],
            color=color if i % 2 == 0 else _dim(color, 0.6),
        ))
    return out


def _design_serpentine_walk(length, color, layout, rng):
    """Single cell travels across the grid in serpentine order, 1/8 per cell."""
    n_bars = len(layout.bar_fixtures)
    n_px = layout.pixels_per_bar
    cells: list[tuple[int, int]] = []
    for b in range(n_bars):
        rows = range(1, n_px + 1) if b % 2 == 0 else range(n_px, 0, -1)
        for p in rows:
            cells.append((b, p))
    step = 0.5
    out: list = []
    t = 0.0
    i = 0
    while t < length - 1e-6:
        bar_idx, pixel = cells[i % len(cells)]
        dur = min(0.6, length - t - 1e-6)
        if dur > 0:
            out.append(ColorStab(
                type="color_stab", fixture=layout.bar_fixtures[bar_idx],
                pixel=pixel, time=t, duration=dur, color=color,
            ))
        t += step
        i += 1
    return out


def _design_drone_with_pulse(length, color, layout, rng):
    """Very dim hold + bright pulse on each downbeat."""
    out: list = [
        ColorHold(type="color_hold", fixture=bar, pixel="*",
                  t_start=0, t_end=length, color=_dim(color, 0.08))
        for bar in layout.bar_fixtures
    ]
    out.extend([
        PulsePattern(type="pulse_pattern", fixture=bar, pixel="*",
                     component="rgb", t_start=0, t_end=length, period=4.0,
                     pulses=[Pulse(offset=0.0, duration=0.15)], color=color)
        for bar in layout.bar_fixtures
    ])
    return out


def _design_outside_in(length, color, layout, rng):
    """Outer columns pulse on beat 1, inner columns on beat 3."""
    out: list = []
    outers = (layout.bar_fixtures[0], layout.bar_fixtures[-1])
    inners = (layout.bar_fixtures[1], layout.bar_fixtures[2])
    for bar in outers:
        out.append(PulsePattern(
            type="pulse_pattern", fixture=bar, pixel="*", component="rgb",
            t_start=0, t_end=length, period=4.0,
            pulses=[Pulse(offset=0.0, duration=0.5)], color=color,
        ))
    for bar in inners:
        out.append(PulsePattern(
            type="pulse_pattern", fixture=bar, pixel="*", component="rgb",
            t_start=0, t_end=length, period=4.0,
            pulses=[Pulse(offset=2.0, duration=0.5)], color=color,
        ))
    return out


REDESIGN_DESIGNS = {
    "bottom_up_chase":    _design_bottom_up_chase,
    "top_down_rain":      _design_top_down_rain,
    "diagonal_sweep":     _design_diagonal_sweep,
    "heartbeat":          _design_heartbeat_pulse,
    "slow_breath":        _design_slow_breath,
    "inhale_exhale":      _design_inhale_exhale,
    "quarter_pulse":      _design_quarter_pulse,
    "corner_pulses":      _design_corner_pulses,
    "center_glow":        _design_center_glow,
    "horizon":            _design_horizon,
    "ambient_chase":      _design_ambient_chase,
    "glittering_stars":   _design_glittering_stars,
    "alt_columns":        _design_alternating_columns,
    "serpentine_walk":    _design_serpentine_walk,
    "drone_with_pulse":   _design_drone_with_pulse,
    "outside_in":         _design_outside_in,
}
REDESIGN_DESIGN_NAMES = tuple(REDESIGN_DESIGNS)

# Calm-biased subset used for auto-fallback (no hint clip). Excludes the
# busier designs (heartbeat, quarter_pulse, alt_columns, outside_in,
# serpentine_walk, diagonal_sweep) — those are reserved for explicit
# hints. The user asked for "scarce and slow" movement by default.
AUTO_REDESIGN_DESIGN_NAMES = (
    "slow_breath",
    "drone_with_pulse",
    "ambient_chase",
    "center_glow",
    "corner_pulses",
    "horizon",
    "inhale_exhale",
    "glittering_stars",
    "top_down_rain",
    "bottom_up_chase",
)


def _clip_to_events_redesign(
    clip: LegacyClip,
    layout: Layout,
    *,
    hint=None,  # lightgen.hints.Hint | None
) -> list:
    """Redesign: hinted or calm-auto bar design + VOX SPOT + scatter strobe.

    Hint precedence:
      * No hint, or hint says 'auto'  → calm-biased auto-redesign
      * Hint says 'dark'              → bar events skipped (spots/sparkles still fire)
      * Hint has design + optional color/intensity → that design wins

    Source automation contribution (only these survive in redesign mode):
      * VOX SPOT envelope → warm-white spots tracking the envelope
      * Strobe envelope   → scattered white sparkles at 1/16 cadence
    """
    rng = _seeded_rng(clip.name)

    events: list = []
    if hint is None or hint.design is None or hint.design == "auto":
        events = _auto_redesign_events(clip, layout, rng)
    elif hint.design == "dark":
        events = []  # skip bar design; spots/sparkles still run
    else:
        color = hint.color if hint.color is not None else _dominant_color(clip)
        if hint.intensity is not None:
            color = _dim(color, hint.intensity)
        if _is_dark_color(color):
            events = []
        else:
            design_name = _hint_design_name(hint)
            design_fn = REDESIGN_DESIGNS.get(design_name, _design_slow_breath)
            events = design_fn(clip.length_beats, color, layout, rng)

    events.extend(_redesign_spot_events(clip, layout))
    events.extend(_redesign_strobe_overlay(clip, layout, rng))
    return events


def _hint_design_name(hint) -> str:
    """Resolve a hint into a canonical design name, honoring direction."""
    name = hint.design
    if name == "bottom_up_chase" and hint.direction == "down":
        return "top_down_rain"
    if name == "top_down_rain" and hint.direction == "up":
        return "bottom_up_chase"
    return name


def _auto_redesign_events(clip, layout, rng):
    """Calm-biased auto-fallback when no hint clip is present.

    Picks deterministically from `AUTO_REDESIGN_DESIGN_NAMES`. Skips the
    bar design entirely when the source was completely dark — rule 8.
    """
    color = _dominant_color(clip)
    if _is_dark_color(color):
        return []
    design_name = rng.choice(AUTO_REDESIGN_DESIGN_NAMES)
    design_fn = REDESIGN_DESIGNS[design_name]
    return design_fn(clip.length_beats, color, layout, rng)


# --- main entry point ----------------------------------------------------


def convert_to_spec(
    legacy_clips: list[LegacyClip],
    *,
    limit: int | None = None,
    slot_offset: int = 0,
    layout: Layout = HITMIX_LAYOUT,
    hints: dict[int, "object"] | None = None,
) -> Spec:
    """Build a Spec from legacy clips, optionally limited to the first `limit`.

    Output slot indices preserve the source's slot positions (shifted by
    `slot_offset`), so empty source slots remain empty in the destination —
    keeping the grid layout intact for paste-back into the original set.

    `hints` (used only by `mode="redesign"`) is a `{source_slot → Hint}`
    map. Slots without an entry fall back to auto-redesign. `Hint` comes
    from `lightgen.hints.parse_hint`; the dict type is loose here to
    avoid importing the hints module at conversion time.
    """
    selected = legacy_clips[:limit] if limit is not None else legacy_clips
    hint_map = hints or {}
    spec_clips: list[Clip] = []
    for lc in selected:
        events = _clip_to_events(lc, layout, hint=hint_map.get(lc.slot))
        spec_clips.append(
            Clip(
                name=lc.name or f"legacy_{lc.slot}",
                slot=slot_offset + lc.slot,
                length_beats=lc.length_beats,
                color_index=lc.color_index if 0 <= lc.color_index <= 69 else 1,
                events=events,
            )
        )
    return Spec(version=1, rig=layout.rig_name, clips=spec_clips)

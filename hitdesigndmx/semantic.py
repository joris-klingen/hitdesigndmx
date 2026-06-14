"""The neutral intermediate representation (IR).

Every source decoder lowers its native format into a timeline of
`LightSegment`s — vocabulary-neutral "what the rig should be doing" intent —
and every target encoder raises that timeline back into concrete MIDI notes.

Keeping a format-agnostic middle means a new source (a future hitnotedmx
note-mapping vN, say) only needs a decoder, and freezing/bumping the target
mapping only needs a new encoder. Neither touches the other.

A segment is *stepwise*: it holds one constant intent over ``[t0, t1)``. The
legacy macro automation is naturally stepwise (constant between breakpoints),
and held MIDI notes express stepwise intent directly, so this is the natural
shared shape.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class LightSegment:
    """One constant interval of lighting intent, in a neutral vocabulary.

    Colours are linear 0..1 RGB. ``bars`` is a subset of the four physical
    bars (1..4); an empty set means "all bars" (no restriction). All the
    "how bright / how fast" knobs are 0..1 so an encoder can map them onto
    whatever expressive axis the target uses (velocity, tail, rate, …).
    """

    t0: float
    t1: float
    color: tuple[float, float, float] | None = None  # bar colour; None = bars dark
    bars: frozenset[int] = field(default_factory=frozenset)  # subset of {1,2,3,4}; empty = all
    chase: bool = False           # bars run a moving chase instead of a flat wash
    chase_intensity: float = 0.0  # 0..1 → tail length / speed
    strobe: float = 0.0           # 0..1 strobe rate; 0 = off
    spots_warm: bool = False      # singer spots lit warm-white

    @property
    def brightness(self) -> float:
        return max(self.color) if self.color else 0.0

    @property
    def saturation(self) -> float:
        """0 = grey/white, 1 = a fully saturated hue. (max-min)/max."""
        if not self.color:
            return 0.0
        hi = max(self.color)
        if hi <= 1e-6:
            return 0.0
        return (hi - min(self.color)) / hi

    @property
    def is_washed_out(self) -> bool:
        """True when there is no strong hue to be faithful to — near-white or
        broadly full-RGB. Such segments are fair game for a self-coloured
        Multicolor recipe, which would otherwise destroy a real hue."""
        return bool(self.color) and self.brightness > 0.0 and self.saturation < 0.35

    @property
    def lit(self) -> bool:
        """True if anything at all is happening in this segment."""
        return bool(self.color) or self.chase or self.strobe > 0.0 or self.spots_warm


@dataclass
class ClipIR:
    """One clip's worth of intent, plus the bits we carry into the output clip."""

    name: str
    slot: int
    length_beats: float
    segments: list[LightSegment] = field(default_factory=list)
    # Song/section structure from the Ableton scenes (slot i ↔ scene i).
    # ``scene`` is the raw scene name at this clip's slot (empty if unnamed);
    # ``section`` is the *inherited* name — the nearest named scene at or before
    # this slot — so a run of clips under one marker shares a section. An
    # encoder seeds shared character (palette family / energy) by section, not
    # per clip, so a song reads coherently. See ``sources/legacy_macro``.
    scene: str = ""
    section: str = ""
    # Deep copy of the source <MidiClip>, kept so the writer can reuse its
    # Loop / TimeSignature / CurrentStart-End (preserves the user's timing).
    source_clip: ET.Element | None = None

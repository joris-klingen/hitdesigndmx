"""End-to-end conversion tests against the checked-in fixture set."""

from pathlib import Path

import pytest

from hitdesigndmx import als, sources
from hitdesigndmx.convert import convert
from hitdesigndmx.vocab import hitnote_v1 as V

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "hitmix_set_dmx_input Project"
    / "hitmix_set_dmx_input.als"
)


@pytest.fixture(scope="module")
def clips():
    """Decoded IR for every populated clip in the fixture set."""
    root = als.read_als(FIXTURE)
    return sources.get("legacy").decode(root)


@pytest.fixture(scope="module")
def converted(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("out") / "converted.als"
    convert(FIXTURE, out)
    return out


# ---- integration: counts + valid .als structure --------------------------
def test_golden_counts(tmp_path):
    """The fixture set is frozen — totals stay stable (band on notes so hue/
    dynamics tuning doesn't break the test on every constant tweak)."""
    res = convert(FIXTURE, tmp_path / "out.als")
    assert res.source == "legacy"
    assert res.target == "hitnote_v1"
    assert res.clips_in == 519
    assert res.clips_written == 513      # 6 fully-dark clips emit nothing
    assert 15000 <= res.notes_written <= 20000


def test_track_inserted_before_returns(converted):
    """Regression: a track appended after the ReturnTracks corrupts the set in
    Live ("track has more send knobs than there are return tracks")."""
    root = als.read_als(converted)
    tags = [t.tag for t in als.tracks(root)]
    first_return = tags.index("ReturnTrack")
    target = als.find_track(root, name="dmx_note")
    assert als.tracks(root).index(target) < first_return


def test_sends_match_returns(converted):
    root = als.read_als(converted)
    returns = sum(1 for t in als.tracks(root) if t.tag == "ReturnTrack")
    target = als.find_track(root, name="dmx_note")
    assert len(target.findall(".//Sends/TrackSendHolder")) == returns


def test_rerun_replaces_existing_target(converted, tmp_path):
    """Converting a set that already carries a dmx_note track must replace it,
    not accumulate a second one."""
    out2 = tmp_path / "twice.als"
    convert(converted, out2)
    root = als.read_als(out2)
    named = [t for t in als.tracks(root) if (als.track_name(t) or "") == "dmx_note"]
    assert len(named) == 1


# ---- fidelity invariants --------------------------------------------------
def test_color_variety(clips):
    """Colour is matched, not forced to red: the set uses a wide palette."""
    used = set()
    for ir in clips:
        for n in V.encode(ir):
            if V.PRIMARY_PALETTE_START <= n.pitch < V.SECONDARY_PALETTE_START:
                used.add(n.pitch)
    assert len(used) >= 12
    # not the old all-red stub (that would be a single pitch)
    assert used != {V.PRIMARY_PALETTE_START + V.RED_INDEX}


def test_vox_maps_to_spot_ww(clips):
    """A clip with the singer-spot (vox) macro raised emits both warm-white
    spot notes (1 and 3) — never the secondary/colour spots."""
    for ir in clips:
        if any(s.spots_warm for s in ir.segments):
            pitches = {n.pitch for n in V.encode(ir)}
            assert V.SPOT_L_WW in pitches and V.SPOT_R_WW in pitches
            return
    pytest.fail("fixture has no vox clip to test")


def test_palette_onsets_land_on_segment_boundaries(clips):
    """Strict timing: every palette-note onset coincides with a colour-segment
    start, so intensity/colour jumps land exactly on the beat."""
    for ir in clips:
        starts = {round(s.t0, 4) for s in ir.segments if s.color is not None}
        for n in V.encode(ir):
            if V.PRIMARY_PALETTE_START <= n.pitch < V.SECONDARY_PALETTE_START:
                assert round(n.start, 4) in starts


def test_no_blackout_note_emitted(clips):
    """Note 0 is a hard kill of the whole rig (spots included); it must never
    appear inside a normal clip — darkness is the absence of notes."""
    for ir in clips:
        assert all(n.pitch != V.BLACKOUT for n in V.encode(ir))


def test_notes_never_overlap_dark_spans(clips):
    """No note (least of all a brightness dynamic, which would white-flash via
    hitnotedmx's white-default) may sound during a fully-dark segment."""
    eps = 1e-6
    for ir in clips:
        dark = [(s.t0, s.t1) for s in ir.segments if not s.lit]
        for n in V.encode(ir):
            ns, ne = n.start, n.start + n.dur
            for d0, d1 in dark:
                assert not (ns < d1 - eps and ne > d0 + eps)


def test_multicolor_only_on_washed_out_clips(clips):
    """Self-coloured Multicolor recipes override hue, so they're reserved for
    clips whose lit segments are mostly washed-out (no strong colour to keep)."""
    for ir in clips:
        if any(V.COLOR_DYN_START <= n.pitch < V.PRIMARY_PALETTE_START for n in V.encode(ir)):
            lit = [s for s in ir.segments if s.color is not None]
            washed = sum(1 for s in lit if s.is_washed_out) / len(lit)
            assert washed > 0.6


def test_deterministic(clips):
    """Same clip name → identical notes every run (seeded creative layer)."""
    for ir in clips[:40]:
        a = [(n.pitch, n.start, n.dur, n.velocity) for n in V.encode(ir)]
        b = [(n.pitch, n.start, n.dur, n.velocity) for n in V.encode(ir)]
        assert a == b


def test_linear_envelope_sampling():
    """Automation is read as piecewise-linear (Ableton's model), so a ramp is
    sampled mid-way, not held at its start value."""
    from hitdesigndmx.sources.legacy_macro import _Env

    env = _Env(points=[(0.0, 0.0), (4.0, 1.0)])  # 0→1 ramp over 4 beats
    assert abs(env.sample(2.0) - 0.5) < 1e-6
    # instantaneous step (two points at the same time) → post-step value
    step = _Env(points=[(0.0, 0.2), (1.0, 0.2), (1.0, 0.8), (2.0, 0.8)])
    assert abs(step.sample(1.0) - 0.8) < 1e-6


def test_fade_ramp_becomes_climbing_velocity():
    """A brightness ramp lowers to a staircase of same-hue palette notes whose
    velocity climbs — reproducing a fade-from-black via MIDI velocity."""
    from hitdesigndmx.semantic import ClipIR, LightSegment

    segs = [LightSegment(t0=i * 0.5, t1=(i + 1) * 0.5, color=(0.12 * (i + 1), 0.0, 0.0))
            for i in range(8)]
    ir = ClipIR(name="synthetic ramp", slot=0, length_beats=4.0, segments=segs)
    pal = sorted(
        (n for n in V.encode(ir) if V.PRIMARY_PALETTE_START <= n.pitch < V.SECONDARY_PALETTE_START),
        key=lambda n: n.start,
    )
    vels = [n.velocity for n in pal]
    assert len(vels) >= 4
    assert vels == sorted(vels)        # monotonic rise = a fade-in
    assert vels[-1] > vels[0]


def test_app_warm_is_static_warm(clips):
    """Named cue: 'App Warm' (the calm applause moment) renders one steady warm
    note — no movement, no recipe, no fade staircase."""
    aw = [ir for ir in clips if "app warm" in ir.name.lower()]
    assert aw, "fixture should contain App Warm cues"
    for ir in aw:
        assert V._clip_plan(ir).mode == "static"
        pitches = {n.pitch for n in V.encode(ir)}
        assert pitches, "App Warm should still light something"
        # only the warm amber palette note (spots 1..4 allowed); nothing in the
        # bar/zone/chase/breathe/wild/multicolor range (5..83) → no movement.
        assert not any(5 <= p <= 83 for p in pitches)
        palette = {p for p in pitches if V.PRIMARY_PALETTE_START <= p < V.SECONDARY_PALETTE_START}
        assert palette == {V.APP_WARM_NOTE}


def test_all_notes_quantized_to_sixteenth(clips):
    """Every note onset and offset lands on the 1/16 (0.25-beat) grid."""
    grid = 0.25
    for ir in clips:
        for n in V.encode(ir):
            for t in (n.start, n.start + n.dur):
                assert abs(t / grid - round(t / grid)) < 1e-4


def test_movement_clips_drive_selectors(clips):
    """Clips with active (oscillating) movement get a bar/zone-selector pattern.
    Vertical-zone notes (12..20) are emitted *only* by that pattern, so they're
    a clean marker that spatial movement is happening across the set."""
    movers = [ir for ir in clips if V._clip_plan(ir).mode == "selectors"]
    assert len(movers) > 50                            # a substantial share move

    zone_clips = 0
    for ir in clips:
        has_zone = any(12 <= n.pitch <= 20 for n in V.encode(ir))
        if has_zone:
            zone_clips += 1
            assert V._clip_plan(ir).mode == "selectors"
    assert zone_clips > 0

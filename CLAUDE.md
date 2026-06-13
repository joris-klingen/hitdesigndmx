# hitdesigndmx

Design tool for hitnotedmx MIDI clips + converter from legacy Ableton
lighting formats into the hitnotedmx note vocabulary. Part of the hitdmx
family (sibling repos in `../`): **hitnotedmx** (MIDI-notes→DMX VST3, the
backbone), **hitlaunchdmx** (standalone Launchpad app), **hitccdmx** (raw
CC-style channel VST).

## Architecture — keep this shape

```
.als → sources/<decoder> → IR (semantic.LightSegment timeline) → vocab/<encoder> → als.add_note_track → .als
```

- `sources/` — one module per input format (`decode`/`detect`), registered in
  `sources/__init__.py`. Auto-detect picks the first match.
- `semantic.py` — vocabulary-neutral IR. Future design features should
  *produce IR* and reuse the encoder/writer unchanged.
- `vocab/hitnote_v1.py` — the ONLY place that knows note numbers. Mirrors
  hitnotedmx's frozen mapping v1 (`../hitnotedmx/mappings/v1.tsv`, 128 rows
  `note<TAB>chainName`). When hitnotedmx bumps the mapping, copy to
  `hitnote_v2.py` and repoint `convert.TARGETS`.
- `reference/` — read-only snapshots from the archived legacy repos
  (not importable; see its README). `lightmidi_midi_to_dmx.py` documents the
  old pre-freeze note vocabulary for a future `sources/old_notes.py` decoder.

## State (2026-06-13)

Converter runs end-to-end (519 clips → 513 written, 6 fully-dark clips emit
nothing; ~9.8k notes) and the output loads in Live (track-ordering fixed).
**Fidelity rewrite landed** — see [the design plan](../../../.claude/plans/agile-watching-dijkstra.md)
for the verified hitnotedmx composition model it targets.

What the encoder/decoder now do:
- **Colour matched, not red** — `pick_color_index` nearest-matches hue on
  *normalised* RGB (dim red → Red, not Crimson); intensity rides palette-note
  velocity. The set now uses 20+ palette colours.
- **Linear automation + strict timing** — `_Env.sample` reads envelopes as
  piecewise-**linear** (Ableton's real model; the old sample-and-hold lost
  every fade). A `SUBGRID_BEATS` grid turns ramps into staircases; the
  significance merge (`TAU_L`/`TAU_CHROMA`) collapses flats so only genuine
  jumps/ramps survive, each landing exactly on the beat.
- **Fade-from-black** — a ramp becomes climbing-velocity palette notes (e.g.
  'App Warm' fades in vel 56→126), reproducing the swell with MIDI velocity.
- **Small, travelling lit regions** — coverage is kept partial and moving (no
  static half). Rhythmic clips (`_attacks` ≥ `ATTACK_MIN`) step a travelling
  `PATTERNS` entry on the beat (`PULSE_BEATS`): bar ping-pong, zone-band
  up/down sweep, rotating quadrant, diagonal cell — each a quarter/band/cell
  that roams the grid, replacing the pan bars. Calm clips (`calm` mode) keep
  the pan bars but narrow them with a **slowly drifting zone band**
  (`_drift_zone`, `CALM_PULSE_BEATS`) so the area wanders instead of sitting.
- **Gentle dynamics** — recipe pools are Breathes/soft movers only (no
  Sparkles); `BREATHE_VEL` low for patchy, subtle islands. **Multicolor gated
  to washed-out clips.** Movement, not busy brightness, carries the interest.
- `vox → Spot WW (1+3)`; no blackout note 0 mid-clip (darkness = no notes).
- **Everything quantized to 1/16** — boundaries snap to `QUANTIZE_BEATS`
  (0.25) in the decoder, so all onsets/offsets land on-grid with no overlaps.
- **Named cues** override the generic plan: `_is_app_warm` → a *static* warm
  Amber wash (`APP_WARM_NOTE`/`APP_WARM_VEL`), no movement/fade — it's the calm
  applause moment (56 such clips in the set). Add more named cues the same way.

Tunable knobs in `vocab/hitnote_v1.py`: `ATTACK_DELTA`/`ATTACK_MIN` (what
counts as "movement"), `PULSE_BEATS`/`CALM_PULSE_BEATS` (movement/drift speed),
`PATTERNS` + `_drift_zone` + `_zone_band` width (the spatial vocabulary &
coverage), `BREATHE_VEL`/`DYN_VEL` (dynamics subtlety), `VEL_FLOOR`; and
`SUBGRID_BEATS`/`TAU_*`/`QUANTIZE_BEATS` in `sources/legacy_macro.py` (fade
smoothness / merge aggressiveness / 1-16 grid).

Known tradeoff: palette-note velocity sets **both** intensity *and* fade
duration, so a dim wash fades in over up to ~2 s. Attack timing stays exact;
only the rise-time of dim segments softens.

Next, in priority order:
1. **Make the movement feel less random (user feedback 2026-06-13: "getting
   closer, but still a bit random").** The spatial patterns travel but the
   *choice* of pattern and its phase are seeded per clip with no musical
   anchoring, so motion doesn't feel intentional. Ideas to try: align pattern
   phase to the clip's bar/beat 1 (not absolute time); pick the pattern from
   the clip's actual rhythm (e.g. pan direction → L/R sweep, build → climb)
   rather than a name hash; reuse one coherent pattern across a song section;
   coarser/steadier `_zone_band` motion. Tune the knobs below to taste.
2. **Eyeball on hardware** — confirm colour, hit timing, the fades, movement.
2. **Mapping-drift test** — parse `../hitnotedmx/mappings/v1.tsv` (skip if
   sibling absent) and assert the vocab constants line up.
3. **barmode-without-colour** still renders a *white* chase; legacy convention
   was a red chase — consider injecting a dim red there if it reads better.

`reference/lightgen_legacy_convert.py` still holds richer per-pixel pattern
heuristics if the grid wants more variety later.

## Commands

```bash
python3 -m hitdesigndmx.cli "fixtures/hitmix_set_dmx_input Project/hitmix_set_dmx_input.als" -o /tmp/out.als
python3 -m hitdesigndmx.cli --gui   # minimal tkinter GUI
pytest                              # (needs `pip install -e ".[dev]"`)
```

No third-party runtime dependencies — stdlib only, keep it that way unless
there's a strong reason.

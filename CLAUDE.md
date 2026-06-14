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

## Roadmap (approved 2026-06-13) — toward a hitnotedmx clip designer

Key reframe from the user: **the legacy rig had no spatial movement.** Rhythmic
R/G/B pulsing was **beat-synced colour flashing** (bars pump the colour on the
beat); `barmode` was the only "program" motion. Our travelling selector
patterns *invented* motion → that's the "random" feel. Also: pan was an L↔R
crossfade (left/right pair ok, refine later); coherence should be **per song /
section**; ultimate goal is a designer built on a **shared library of named
"looks."**

Phases (do in order; each is shippable):
1. **Beat-flash, not travel** — make rhythmic clips pump the matched colour on
   the beat (the per-segment colour notes already encode this); stop defaulting
   to travelling bar/zone patterns. Use `_attacks` for *energy*, not motion.
   Keep `barmode → chase`, `vox → Spot WW`, pan left/right-pair.
2. **Section coherence via scene names** — the Ableton **scenes** hold song/
   section names (`als` needs a `scene_names(root)`; slot *i* ↔ scene *i*).
   Carry `scene` into `ClipIR`; group into songs/sections; **seed character by
   song, not per clip** so a song's clips share palette/energy. Section type
   (verse/chorus/drop/tutti…) sets energy.
3. **Looks library** (`hitdesigndmx/looks.py`) — refactor the encoder modes into
   named, parameterised Looks (`warm_static`=App Warm, `colour_pump`,
   `chase_program`, `breathe_wash`, `multicolour_wash`, structured
   `traveling_region`). Converter becomes `classify(ir) → (look, params)`. This
   is the shared vocabulary the designer (Phase 4) will author with.
4. **Designer** (future) — high-level "section → Look + params" → MIDI over
   `looks.py` + `als.add_note_track`.

Reconciliation to settle on hardware: default to beat-flash; allow a structured
`traveling_region` only on high-energy sections, phase-locked, one per section.

Smaller follow-ups: mapping-drift test vs `../hitnotedmx/mappings/v1.tsv`;
barmode-without-colour currently renders a *white* chase (legacy was red).

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

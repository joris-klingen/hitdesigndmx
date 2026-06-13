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
- **Strict timing** — decoder (`legacy_macro.py`) collapses micro-ripple by
  significance (`TAU_L` / `TAU_CHROMA`) so every surviving boundary is a real
  jump; encoder onsets a palette note exactly at each colour-segment start.
- **Bold grid dynamics** — `_creative_layer` adds one deterministic recipe per
  clip (chase for barmode, Breathe/Wild texture sized to the clip's pace, a
  ~30% pixel-zone comb), held only over lit spans. **Multicolor recipes are
  gated to washed-out clips** (they override hue).
- `vox → Spot WW (1+3)`; no blackout note 0 mid-clip (darkness = no notes).

Known tradeoff: palette-note velocity sets **both** intensity *and* fade
duration, so a dim wash fades in over up to ~2 s. Onsets still land on the
beat (attack timing is exact); only the rise-time of dim segments softens.
Tune `VEL_FLOOR` if hardware shows this is too soft.

Next, in priority order:
1. **Eyeball on hardware** — confirm the colour spread, hit timing, and that
   the bold dynamics read well; tune the curated recipe pools / `COMB_FRACTION`
   / thresholds in `vocab/hitnote_v1.py` to taste.
2. **Mapping-drift test** — parse `../hitnotedmx/mappings/v1.tsv` (skip if
   sibling absent) and assert the vocab constants line up.
3. **barmode-without-colour** currently renders a *white* chase (no wash colour
   in the curve). Legacy convention was a red chase — consider injecting a dim
   red for those segments if it reads better.

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

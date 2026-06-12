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

## State (2026-06-12)

Converter runs end-to-end on the fixture: 519/519 clips, ~8.5k notes.
Remaining work to trust the output, in priority order:

1. **Color matching** — `vocab/hitnote_v1.py::pick_color_index` is a
   placeholder returning red always. Implement nearest-neighbour over
   `PRIMARY_PALETTE` (swap point is isolated; nothing else changes).
2. **Golden tests** — `tests/test_convert.py` covers fixture totals
   (519 clips / 8521 notes), track-before-returns ordering, sends==returns,
   and idempotent re-runs. Still missing: per-clip note assertions (dark
   clip → blackout note 0, strobe → note 48, pan-left → bar selectors 5+6).
   Run with `uv run --with pytest --no-project -m pytest tests/ -q`.
3. **Mapping-drift test** — parse `../hitnotedmx/mappings/v1.tsv` (skip test
   if sibling repo absent) and assert vocab constants line up.
4. **Velocity semantics** — encoder maps brightness → vel 64–127 for palette
   notes (primary routing), `lo=1.0` for strobe/chase intensity. Verify
   against actual hitnotedmx behaviour in Live (A/B converted track vs
   legacy rack) before tuning.

If converted sets feel visually flat, mine
`reference/lightgen_legacy_convert.py` for its effect-variety heuristics.

## Commands

```bash
python3 -m hitdesigndmx.cli "fixtures/hitmix_set_dmx_input Project/hitmix_set_dmx_input.als" -o /tmp/out.als
python3 -m hitdesigndmx.cli --gui   # minimal tkinter GUI
pytest                              # (needs `pip install -e ".[dev]"`)
```

No third-party runtime dependencies — stdlib only, keep it that way unless
there's a strong reason.

# Reference code from the archived repos

Read-only snapshots kept for the converter work — **not importable** (their
relative imports point at packages that no longer exist here). The full
originals live in the archived GitHub repos
[hitmixdmx](https://github.com/joris-klingen/hitmixdmx) and
[hitmixmididmx](https://github.com/joris-klingen/hitmixmididmx).

- `lightgen_legacy_convert.py` — from `hitmixdmx/lightgen/legacy_convert.py`
  (final WIP state). The original legacy-macro → DMXIS converter whose
  parsing approach `hitdesigndmx/sources/legacy_macro.py` ports. Useful for
  the richer segment-interpretation heuristics (pattern masks, effect
  selection) not yet carried over.
- `lightmidi_midi_to_dmx.py` — from `hitmixmididmx/lightmidi/midi_to_dmx.py`.
  Documents the **old, pre-freeze note vocabulary** (bar selectors at 4–11,
  primaries at 36–59, layer/mask composition semantics) and contains the
  KeyTrack note-reading code. This is the spec for a future
  `sources/old_notes.py` decoder that migrates old note clips to the current
  mapping.

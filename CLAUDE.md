# hitdesigndmx — HitDesign

A small JUCE app + CLI that **designs** a hitnotedmx-triggering MIDI clip from
three input clips (drums / bass / synths) plus colour / dynamics / brightness
controls and an adjustable length. Part of the hitdmx family (sibling repos on
GitHub): **hitnotedmx** (MIDI-notes→DMX VST3, the backbone — this repo depends on
its sources), **hitlaunchdmx** (standalone Launchpad app), **hitccdmx** (raw
CC-style channel VST).

> **History:** this repo began as the legacy Ableton `.als` lighting-clip
> converter (Python). It was rewritten (2026-07-07) into the HitDesign C++ app;
> the old converter is in git history before that change.

## Architecture — keep this shape

```
drums/bass/synths .mid → ClipAnalysis (per-role features) → DesignEngine
   (region-based layering) → NoteList → MidiClipIO.write → .mid (triggers HitNoteDmx)
```

- **`design/` — the GUI-free core** (shared by the CLI, the app and the tests):
  - `MidiClipIO` — Standard MIDI File read/write, beat-based (tempo-agnostic).
  - `ClipAnalysis` — per-role features on a 1/16 grid: drums → onsets / per-bar
    energy / strong-onset threshold / fill bars; bass → a per-cell activity
    envelope; synths → sustain ratio / movement / pad-like flag.
  - `DesignEngine` — the design logic. Deterministic in `(inputs, params, seed)`.
  - `DesignVocab.h` — **the ONLY place the engine names notes.** Named constants
    + motion pools, each carrying its expected HitNoteDmx chain name; `selfCheck()`
    verifies them so a future mapping bump fails the test instead of emitting
    wrong notes.
- **`design/app/` — the JUCE app:** `DropZone` (per-role .mid drop target),
  `SwatchGrid` (palette picker from the real palette), `PlaybackEngine` (plays
  the design through the REAL `computeDmx` into the shared `DmxVisualizer`;
  optional ENTTEC out), `MainComponent` (layout + regenerate-on-change),
  `HitDesignApp` (entry point; accepts `[drums bass synths]` launch args).
- **`tools/HitDesignCli.cpp`** — the console front-end + `selftest`.
- **HitNoteDmx dependency** — fetched via `FetchContent` at a **pinned commit**
  (see `CMakeLists.txt`), for its `Source/` only (TriggerVocabulary, Palette,
  Rig, Recipes, MidiState, Composition, DmxVisualizer, EnttecProDmx). We compile
  the specific files we need into our targets; we do **not** build the plugin.
  Bump the pin to adopt a newer mapping, then re-run `design-selftest`.

## Design model (the important bit)

Layering is organised around **bass-gated active regions** so a lit stretch
always carries the chosen colour (never bare white) and rests are truly dark
(darkness = no notes; never the blackout note mid-clip):

- **Colour bed** — single colour: re-strike the base on each pump beat,
  back-to-back (pulses on the beat, no gaps). Multiple colours: hold the base
  wash across the region + strike accents on strong drum hits.
- **Motion** — one recipe per region by dynamics: calm → held **breathe**;
  mid → held **chase**; high → held chase + **wild** accents on fills. All
  brightness recipes (chases/breathes/wild), so the chosen colour is honoured
  (self-coloured Multicolor is deliberately not used).
- **Brightness** → palette-note velocity (also the fade rate). **Length** loops
  or truncates the source; everything snaps to the 1/16 grid, nothing past the
  clip end.

Tunable knobs live in `design/DesignEngine.cpp` (velocity maps, pump predicate,
region gating thresholds) and the pools in `design/DesignVocab.h`.

## Commands

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target hitdesign HitDesign
ctest --test-dir build            # design-selftest (vocab drift + engine invariants)

./build/hitdesign_artefacts/Release/hitdesign drums.mid --bass bass.mid \
    --synths synths.mid --colors "Red,Amber" --dynamics 70 --brightness 80 -o out.mid
./build/HitDesign_artefacts/Release/HitDesign [drums.mid bass.mid synths.mid]
```

No third-party runtime deps beyond JUCE + the HitNoteDmx sources (both fetched).
Keep the engine core (`design/`, minus `design/app/`) GUI-free so the CLI and
tests stay light.

## Verifying a design

`design-selftest` guards correctness (in-vocabulary, on-grid, balanced,
deterministic). To eyeball a real design, render its `.mid` through HitNoteDmx's
`recipe-render clip` (in that repo) — it composes the clip through the same
`computeDmx` and writes a filmstrip PNG. Or load it in the app and watch the live
rig preview.

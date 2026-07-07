# hitdesigndmx — HitDesign

**Design a light-show clip from your music.** HitDesign takes three MIDI clips —
**drums**, **bass**, **synths** — by drag and drop, plus a few high-level
controls (pick **colours**, a **dynamics** level and a **brightness** level, and
an adjustable **length**), and designs a MIDI clip that triggers
[hitnotedmx](https://github.com/joris-klingen/hitnotedmx) — the MIDI-notes → DMX
plugin that is the backbone of the hitdmx family.

It's a small JUCE app (Standalone; macOS + cross-platform GUI). Because it links
HitNoteDmx's own note vocabulary, palette, compositor and rig visualiser, the
notes it emits can never drift from the plugin's live mapping, and its preview
plays through the **real** `computeDmx` — what you see is what the rig does.

## What it does

Feed it up to three clips (only **drums** is required) and it designs a layered
clip, honouring HitNoteDmx's composition model (beat-flash, not travel):

- **Drums** drive rhythm + energy — onsets pump the chosen colour on the beat,
  and fills fire wild accents at high dynamics.
- **Bass** gates *active regions* — the rig is lit and coloured where the bass
  plays, and dark where it rests (darkness = no notes, never bare white).
- **Synths** set texture — pad-like parts lean on gentle breathes, busier parts
  get livelier motion.
- **Dynamics** picks one motion recipe per region (calm breathe → chase → chase
  + wild). **Brightness** rides the palette-note velocity. **Length** defaults to
  the drums clip and is adjustable (loops / truncates the source). A **seed**
  makes the creative choices deterministic (reroll for a variation).

The result is a tempo-agnostic `.mid` clip — drag it onto a HitNoteDmx track in
your DAW, or preview + drive the rig straight from the app.

## Build

Requires CMake 3.22+. JUCE and the HitNoteDmx sources are fetched automatically
via `FetchContent`.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target hitdesign HitDesign
ctest --test-dir build            # design-selftest: vocab-drift + engine invariants
```

The GUI app lands at `build/HitDesign_artefacts/Release/HitDesign` and the CLI at
`build/hitdesign_artefacts/Release/hitdesign`.

## Use it

GUI — drag clips onto the three drop zones (or pass them as launch args), pick
colours + set the sliders, preview on the rig visualiser, then drag the result
into your DAW:

```sh
./build/HitDesign_artefacts/Release/HitDesign [drums.mid bass.mid synths.mid]
```

CLI — script it or batch it:

```sh
./build/hitdesign_artefacts/Release/hitdesign drums.mid --bass bass.mid \
    --synths synths.mid --colors "Red,Amber" --dynamics 70 --brightness 80 -o out.mid
./build/hitdesign_artefacts/Release/hitdesign --list-colors
```

## Layout

```
design/            GUI-free core (shared by CLI, app and tests)
  MidiClipIO       Standard MIDI File read / write (beat-based)
  ClipAnalysis     per-role features (onsets, energy, bass envelope, texture)
  DesignEngine     region-based layering → a designed note list
  DesignVocab      the ONE place notes are named (guarded against mapping drift)
design/app/        the JUCE app (drop zones, swatch picker, sliders, live preview)
tools/HitDesignCli.cpp   the console front-end + `selftest`
CMakeLists.txt     fetches JUCE + HitNoteDmx (pinned); no plugin is built here
```

## Family

- [hitnotedmx](https://github.com/joris-klingen/hitnotedmx) — MIDI-notes → DMX
  VST3 + Standalone (the backbone; this repo depends on its sources)
- [hitlaunchdmx](https://github.com/joris-klingen/hitlaunchdmx) — standalone
  Launchpad-triggered ambient scenes
- [hitccdmx](https://github.com/joris-klingen/hitccdmx) — raw CC-style DMX
  channel VST

> The legacy Ableton (`.als`) lighting-clip converter that this repo started as
> now lives in git history (before the HitDesign rewrite) — see the `main`
> branch prior to this change if you need it.

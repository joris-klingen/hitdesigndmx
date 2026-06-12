# hitdesigndmx

Design tool for [hitnotedmx](https://github.com/joris-klingen/hitnotedmx) MIDI clips,
part of the hitdmx family:

- **hitnotedmx** — MIDI-notes → DMX VST3 (the backbone)
- **hitlaunchdmx** — standalone Launchpad-controlled DMX app
- **hitautomdmx** — minimal VST exposing raw DMX channels to a DAW
- **hitdesigndmx** — this repo: design hitnotedmx MIDI clips, and convert
  legacy clip-automation DMX (DMXIS-style `.als` macro automation) into the
  hitnotedmx note vocabulary

## Status

Seeded from the converter (`hitdmxconvert`). Clip-design features come next.

## Usage

```bash
# Convert a legacy Ableton lighting set into hitnotedmx-style MIDI clips
hitdmxconvert <input.als> <output.als>

# Or launch the minimal GUI
python -m hitdesigndmx.gui
```

A sample legacy Ableton project lives in `fixtures/hitmix_set_dmx_input Project/`
for conversion testing.

## Development

```bash
pip install -e ".[dev]"
pytest
```

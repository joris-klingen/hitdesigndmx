#pragma once

#include <juce_audio_basics/juce_audio_basics.h>
#include <vector>

namespace hitdesign
{

// One timed note, tempo-agnostic (times in beats; a beat = one quarter note).
struct Note
{
    int    pitch;       // MIDI note number 0..127
    int    velocity;    // 1..127
    double startBeats;  // note-on time in beats
    double lenBeats;    // note-on → note-off, in beats (> 0)

    double endBeats() const noexcept { return startBeats + lenBeats; }
};

// A parsed / designed clip: a flat note list plus the clip's musical length.
struct Clip
{
    std::vector<Note> notes;
    double            lengthBeats = 0.0;   // rounded up to a whole bar on read

    bool empty() const noexcept { return notes.empty(); }
};

namespace MidiClipIO
{
    // Beats per bar assumed for length rounding (4/4). The engine works in beats
    // throughout, so this only affects the default clip length.
    inline constexpr double kBeatsPerBar = 4.0;
    inline constexpr int    kTicksPerQuarter = 960;

    // Read a Standard MIDI File into a Clip: all tracks merged, ticks → beats via
    // the file's PPQ, note-ons matched to their note-offs. `lengthBeats` is the
    // last note-off rounded UP to a whole bar. Returns false (and leaves `out`
    // untouched) if the file can't be parsed or uses SMPTE time.
    bool read (const juce::File& file, Clip& out, juce::String& error);

    // Write a Clip to a Standard MIDI File (one track, beat-based, matched
    // note-on/off pairs), overwriting any existing file. Returns false on an I/O
    // error.
    bool write (const Clip& clip, const juce::File& file, juce::String& error);
}

}  // namespace hitdesign

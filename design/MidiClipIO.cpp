#include "MidiClipIO.h"

#include <algorithm>
#include <cmath>

namespace hitdesign
{

bool MidiClipIO::read (const juce::File& file, Clip& out, juce::String& error)
{
    juce::FileInputStream in (file);
    if (! in.openedOk())
    {
        error = "cannot open " + file.getFullPathName();
        return false;
    }

    juce::MidiFile mf;
    if (! mf.readFrom (in))
    {
        error = "not a MIDI file: " + file.getFullPathName();
        return false;
    }

    const int tf = mf.getTimeFormat();
    if (tf <= 0)
    {
        error = "SMPTE time format is not supported: " + file.getFullPathName();
        return false;
    }
    const double ppq = static_cast<double> (tf);

    // Flatten every track's matched note pairs into beat-stamped notes.
    Clip clip;
    double lastEnd = 0.0;
    for (int t = 0; t < mf.getNumTracks(); ++t)
    {
        auto seq = *mf.getTrack (t);
        seq.updateMatchedPairs();

        for (int i = 0; i < seq.getNumEvents(); ++i)
        {
            auto* ev = seq.getEventPointer (i);
            const auto& m = ev->message;
            if (! m.isNoteOn() || m.getVelocity() == 0)
                continue;

            const double startB = m.getTimeStamp() / ppq;
            double endB = startB;
            if (ev->noteOffObject != nullptr)
                endB = ev->noteOffObject->message.getTimeStamp() / ppq;

            double lenB = endB - startB;
            if (lenB <= 0.0)
                lenB = 0.25;   // a note with no matched off: give it a 1/16 tap

            clip.notes.push_back ({ m.getNoteNumber(),
                                    juce::jlimit (1, 127, static_cast<int> (m.getVelocity())),
                                    startB, lenB });
            lastEnd = std::max (lastEnd, startB + lenB);
        }
    }

    std::stable_sort (clip.notes.begin(), clip.notes.end(),
                      [] (const Note& a, const Note& b)
                      { return a.startBeats < b.startBeats; });

    // Length = last note-off rounded up to a whole bar (never zero).
    const double bars = std::ceil (std::max (lastEnd, 1e-9) / kBeatsPerBar);
    clip.lengthBeats = std::max (1.0, bars) * kBeatsPerBar;

    out = std::move (clip);
    return true;
}

bool MidiClipIO::write (const Clip& clip, const juce::File& file, juce::String& error)
{
    juce::MidiMessageSequence seq;
    for (const auto& n : clip.notes)
    {
        const auto vel = static_cast<juce::uint8> (juce::jlimit (1, 127, n.velocity));
        seq.addEvent (juce::MidiMessage::noteOn (1, n.pitch, vel),
                      n.startBeats * kTicksPerQuarter);
        seq.addEvent (juce::MidiMessage::noteOff (1, n.pitch),
                      n.endBeats() * kTicksPerQuarter);
    }
    seq.updateMatchedPairs();

    juce::MidiFile mf;
    mf.setTicksPerQuarterNote (kTicksPerQuarter);
    mf.addTrack (seq);

    file.getParentDirectory().createDirectory();
    auto os = file.createOutputStream();
    if (os == nullptr)
    {
        error = "cannot write " + file.getFullPathName();
        return false;
    }
    os->setPosition (0);
    os->truncate();
    const bool ok = mf.writeTo (*os);
    if (! ok)
        error = "failed to encode MIDI: " + file.getFullPathName();
    return ok;
}

}  // namespace hitdesign

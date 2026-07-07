#pragma once

#include <functional>
#include <vector>

#include <juce_gui_basics/juce_gui_basics.h>

#include "Composition.h"     // computeDmx, DmxValues, GridState, ColorFadeState, BumpState
#include "EnttecProDmx.h"
#include "MidiState.h"
#include "MidiClipIO.h"

namespace hitdesign
{

// Plays a designed clip through the REAL hitnotedmx composition path at the
// driver's send rate, exactly as the audio thread does — so the preview matches
// what the rig plays. Feeds an on-screen DmxValues/SelectionMask (for the
// visualiser) and, when an ENTTEC widget is connected, the physical rig.
class PlaybackEngine : private juce::Timer
{
public:
    PlaybackEngine();

    void setClip (const Clip& clip);           // swap the clip (safe while playing)
    void setBpm (double bpm)      { bpmValue = juce::jlimit (20.0, 300.0, bpm); }
    void setLooping (bool shouldLoop) { looping = shouldLoop; }

    void play();
    void stop();
    void rewind();
    bool isPlaying() const        { return playing; }
    double positionBeats() const  { return posBeats; }
    double clipLengthBeats() const { return clipLen; }

    const hitnotedmx::DmxValues&     values()    const { return vals; }
    const hitnotedmx::SelectionMask& selection() const { return sel; }
    const hitnotedmx::Rig&           rig()       const { return grid.rig; }

    // Live DMX out (macOS; a no-op stub off-Apple). Pushes each computed frame.
    hitnotedmx::EnttecProDmx& driver() { return enttec; }
    void setSendToDmx (bool on)   { sendToDmx = on; }

    // Called after every computed frame (on the message thread) — the app hooks
    // this to repaint the visualiser + refresh the transport readout.
    std::function<void()> onFrame;

private:
    void timerCallback() override;
    void compose();
    void applyEventsUpTo (double beat);
    void resetToStart();

    struct Ev { double beat; int pitch; int vel; bool on; };
    std::vector<Ev> evs;
    size_t          ei = 0;

    hitnotedmx::MidiState      state;
    hitnotedmx::ColorFadeState fade;
    hitnotedmx::BumpState      bump;
    hitnotedmx::DmxValues      vals;
    hitnotedmx::SelectionMask  sel;
    hitnotedmx::GridState      grid;

    hitnotedmx::EnttecProDmx enttec;
    bool   sendToDmx = false;

    double posBeats = 0.0;
    double clipLen  = MidiClipIO::kBeatsPerBar;
    double bpmValue = 120.0;
    bool   looping  = true;
    bool   playing  = false;
    double lastMs   = 0.0;
};

}  // namespace hitdesign

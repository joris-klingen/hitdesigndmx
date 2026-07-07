#include "PlaybackEngine.h"

#include <algorithm>
#include <cmath>

namespace hitdesign
{

using namespace hitnotedmx;

PlaybackEngine::PlaybackEngine()
{
    grid.rig = Rig {};   // default 4 × 18
    grid.rebuild();
    compose();           // an initial dark frame
}

void PlaybackEngine::setClip (const Clip& clip)
{
    evs.clear();
    for (const auto& n : clip.notes)
    {
        evs.push_back ({ n.startBeats, n.pitch, n.velocity, true });
        evs.push_back ({ n.endBeats(), n.pitch, 0, false });
    }
    // Note-offs before note-ons at an equal beat, so a same-pitch retrigger
    // keeps the note on (matches the offline clip renderer).
    std::stable_sort (evs.begin(), evs.end(), [] (const Ev& a, const Ev& b)
    {
        if (a.beat < b.beat) return true;
        if (b.beat < a.beat) return false;
        return a.on < b.on;
    });
    clipLen = std::max (MidiClipIO::kBeatsPerBar, clip.lengthBeats);
    resetToStart();
    applyEventsUpTo (posBeats);   // light the frame-0 notes so a paused preview isn't dark
    compose();
    if (onFrame) onFrame();
}

void PlaybackEngine::resetToStart()
{
    posBeats = 0.0;
    ei = 0;
    state.clear();
    fade.reset();
    bump.reset();
    bump.resyncClocks();
}

void PlaybackEngine::play()
{
    if (playing) return;
    playing = true;
    lastMs = juce::Time::getMillisecondCounterHiRes();
    startTimerHz (EnttecProDmx::kSendRateHz);
}

void PlaybackEngine::stop()
{
    playing = false;
    stopTimer();
}

void PlaybackEngine::rewind()
{
    resetToStart();
    applyEventsUpTo (posBeats);
    compose();
    if (onFrame) onFrame();
}

void PlaybackEngine::applyEventsUpTo (double beat)
{
    while (ei < evs.size() && evs[ei].beat <= beat + 1e-6)
    {
        const auto& e = evs[ei++];
        if (e.on) state.noteOn  (static_cast<std::uint8_t> (e.pitch), 1,
                                 static_cast<std::uint8_t> (e.vel), e.beat);
        else      state.noteOff (static_cast<std::uint8_t> (e.pitch));
    }
}

void PlaybackEngine::compose()
{
    const double dtSec = 1.0 / EnttecProDmx::kSendRateHz;
    computeDmx (state, posBeats, vals, grid, 1.0f, 1.0f, &fade, dtSec, 1.0f, &sel, &bump);

    if (sendToDmx && enttec.isConnected())
        for (int ch = 1; ch <= grid.rig.rigChannels(); ++ch)
            enttec.setChannel (ch, static_cast<juce::uint8> (
                juce::jlimit (0, 255, static_cast<int> (std::lround (vals.get (ch) * 255.0f)))));
}

void PlaybackEngine::timerCallback()
{
    const double now = juce::Time::getMillisecondCounterHiRes();
    const double dtSec = juce::jlimit (0.0, 0.25, (now - lastMs) / 1000.0);
    lastMs = now;

    posBeats += dtSec * bpmValue / 60.0;
    if (posBeats >= clipLen)
    {
        if (looping)
        {
            posBeats = std::fmod (posBeats, clipLen);
            ei = 0;
            state.clear();
            fade.reset();
            bump.resyncClocks();
        }
        else
        {
            posBeats = clipLen;
            stop();
        }
    }

    applyEventsUpTo (posBeats);
    compose();
    if (onFrame) onFrame();
}

}  // namespace hitdesign

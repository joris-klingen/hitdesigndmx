#pragma once

#include <vector>

#include "MidiClipIO.h"

namespace hitdesign
{

// Everything downstream works on a 1/16 grid (the convention that held up in the
// legacy converter): onsets and region boundaries land on multiples of this.
inline constexpr double kGridBeats = 0.25;

inline double snapToGrid (double beats) noexcept
{
    return std::round (beats / kGridBeats) * kGridBeats;
}

struct Onset
{
    double beat;   // quantised to the 1/16 grid
    int    vel;    // summed velocity of the notes in this grid cell, capped 127
};

// Drums drive rhythm + energy: where the beats land, how hard, how busy, and
// which bars are fills (bursts of activity → accent moments).
struct DrumFeatures
{
    bool                present = false;
    double              sourceLenBeats = 0.0;
    std::vector<Onset>  onsets;            // sorted, one per occupied grid cell
    int                 strongVel = 100;   // ≥ this velocity ⇒ a "strong" onset
    std::vector<int>    onsetsPerBar;
    std::vector<bool>   fillBar;           // per bar: a burst of activity
    int                 medianPerBar = 0;
};

// Bass is the foundation: a per-grid-cell activity envelope in [0,1] that gates
// how bright the base wash is (and whether the floor is lit at all).
struct BassFeatures
{
    bool                present = false;
    double              sourceLenBeats = 0.0;
    std::vector<float>  cell;              // one per 1/16 cell over [0,sourceLen)
    float               meanActivity = 0.0f;
};

// Synths are texture: sustained/pad-like → gentle breathes; moving/busy → livelier.
struct SynthFeatures
{
    bool    present = false;
    double  sourceLenBeats = 0.0;
    double  sustainRatio = 0.0;   // mean note length / one beat
    double  movement = 0.0;       // pitch changes per bar
    bool    padLike = false;
};

namespace ClipAnalysis
{
    DrumFeatures  drums  (const Clip& c);
    BassFeatures  bass   (const Clip& c);
    SynthFeatures synths (const Clip& c);
}

}  // namespace hitdesign

#pragma once

#include <cstdint>
#include <vector>

#include "MidiClipIO.h"

namespace hitdesign
{

// User-facing design controls.
struct DesignParams
{
    std::vector<int> colorPitches;   // ≥ 1 palette pitch; first = base colour
    int              dynamics   = 50;    // 0..100  calm → wild
    int              brightness = 80;    // 0..100  dim → bright
    double           lengthBeats = 0.0;  // 0 ⇒ use the drums clip's length
    std::uint64_t    seed = 1;           // same inputs + seed ⇒ identical output
};

// Design a HitNoteDmx-triggering clip from the three input clips + params.
// Only `drums` is required; pass empty clips for missing bass/synths. Output is
// deterministic in (inputs, params) and fully on the 1/16 grid; no note falls
// outside [0, length]. Never emits the blackout note mid-clip (darkness = the
// absence of notes).
Clip design (const Clip& drums, const Clip& bass, const Clip& synths,
             const DesignParams& params);

}  // namespace hitdesign

#pragma once

#include <array>
#include <juce_core/juce_core.h>

#include "Palette.h"     // kPrimaryPaletteStart, kSecondaryPaletteStart, names
#include "Recipes.h"     // kChasesStart, kBreathesStart, kWildStart
#include "TriggerVocabulary.h"

// The ONE place the design engine names notes. Every constant here is a MIDI
// pitch in the live hitnotedmx vocabulary; `selfCheck()` verifies each against
// vocab::chainName() so a future mapping bump fails the `design-selftest` CTest
// instead of the engine silently emitting a wrong note.
namespace hitdesign::vox
{

using namespace hitnotedmx;

// --- structural selectors (Spots & bars octave, pitches 1..8) ---------------
inline constexpr int kSpotLwarm = 1;   // "sp Spot L WW"
inline constexpr int kSpotRwarm = 3;   // "sp Spot R WW"
inline constexpr int kBarLeft   = 5;   // "ba Left"
inline constexpr int kBarMidL   = 6;   // "ba Mid left"
inline constexpr int kBarMidR   = 7;   // "ba Mid right"
inline constexpr int kBarRight  = 8;   // "ba Right"

// --- palette ----------------------------------------------------------------
// A chosen colour is just a palette pitch. Primary spans 84..107, secondary
// 108..119. offset is the colour's index within its table.
inline constexpr int primaryPitch   (int offset) { return kPrimaryPaletteStart   + offset; }
inline constexpr int secondaryPitch (int offset) { return kSecondaryPaletteStart + offset; }

// --- motion pools (brightness recipes only, so the chosen colour is honoured;
//     self-coloured Multicolor is deliberately NOT used here) ----------------

// Calm held breathes. Pad-like synths lean on the first (smoother) entries.
inline constexpr std::array<int, 5> kBreathePool {{
    kBreathesStart + 1,   // Sine
    kBreathesStart + 11,  // Glow
    kBreathesStart + 5,   // Halo
    kBreathesStart + 0,   // Tide
    kBreathesStart + 8,   // Drift
}};

// Beat-locked chases for mid/high dynamics.
inline constexpr std::array<int, 4> kChasePool {{
    kChasesStart + 0,   // Chase
    kChasesStart + 8,   // Waves
    kChasesStart + 9,   // Expand
    kChasesStart + 7,   // Spiral
}};

// Wild accents fired on fills — NEVER the strobe root (kWildStart + 0).
inline constexpr std::array<int, 4> kWildPool {{
    kWildStart + 1,    // Sparkle
    kWildStart + 11,   // Burst
    kWildStart + 2,    // Sparkle few
    kWildStart + 3,    // Lightning
}};

// Resolve a palette colour name (primary first, then secondary) to a pitch.
// Case-insensitive exact-or-prefix match. Returns -1 if nothing matches.
inline int colorNameToPitch (const juce::String& name)
{
    const auto q = name.trim().toLowerCase();
    if (q.isEmpty())
        return -1;

    auto scan = [&q] (const auto& names, int start, int count) -> int
    {
        int exact = -1, prefix = -1;
        for (int i = 0; i < count; ++i)
        {
            const juce::String n = juce::String (names[static_cast<size_t> (i)]).toLowerCase();
            if (n == q)              exact  = start + i;
            else if (n.startsWith (q) && prefix < 0) prefix = start + i;
        }
        return exact >= 0 ? exact : prefix;
    };

    if (int p = scan (kPaletteNames, kPrimaryPaletteStart, kPaletteSize); p >= 0)
        return p;
    return scan (kSecondaryPaletteNames, kSecondaryPaletteStart, kSecondaryPaletteSize);
}

// Verify every named constant + pool entry resolves to the chain name we expect.
// Returns an empty string on success, or a human-readable description of the
// first mismatch (used by the CLI `selftest`).
inline juce::String selfCheck()
{
    struct Expect { int pitch; const char* chain; };
    const std::array<Expect, 6> fixed {{
        { kSpotLwarm, "sp Spot L WW" }, { kSpotRwarm, "sp Spot R WW" },
        { kBarLeft, "ba Left" }, { kBarMidL, "ba Mid left" },
        { kBarMidR, "ba Mid right" }, { kBarRight, "ba Right" },
    }};
    for (const auto& e : fixed)
    {
        const auto got = vocab::chainName (e.pitch);
        if (got != juce::String (e.chain))
            return "note " + juce::String (e.pitch) + " expected '" + e.chain
                 + "' but vocabulary says '" + got + "'";
    }

    // Pool entries must all be real, prefix-correct trigger notes.
    auto checkPool = [] (const auto& pool, const char* pre) -> juce::String
    {
        for (int p : pool)
        {
            const auto got = vocab::chainName (p);
            if (! got.startsWith (juce::String (pre) + " "))
                return "pool note " + juce::String (p) + " ('" + got
                     + "') is not a '" + pre + "' trigger";
        }
        return {};
    };
    if (auto e = checkPool (kBreathePool, "br"); e.isNotEmpty()) return e;
    if (auto e = checkPool (kChasePool,   "ch"); e.isNotEmpty()) return e;
    if (auto e = checkPool (kWildPool,    "wd"); e.isNotEmpty()) return e;

    return {};
}

}  // namespace hitdesign::vox

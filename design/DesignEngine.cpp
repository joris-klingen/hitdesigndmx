#include "DesignEngine.h"

#include <algorithm>
#include <cmath>

#include "ClipAnalysis.h"
#include "DesignVocab.h"

namespace hitdesign
{

namespace
{
// ---- tiny deterministic PRNG (no Date/random; pure fn of the seed) ----------
struct SplitMix64
{
    std::uint64_t s;
    explicit SplitMix64 (std::uint64_t seed) : s (seed) {}
    std::uint64_t next()
    {
        s += 0x9E3779B97F4A7C15ull;
        std::uint64_t z = s;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
        return z ^ (z >> 31);
    }
    // Deterministic pick from a fixed-size pool.
    template <typename Pool>
    int pick (const Pool& pool) { return pool[next() % pool.size()]; }
};

int clampVel (double v) { return static_cast<int> (std::lround (juce::jlimit (1.0, 127.0, v))); }

// brightness 0..100 → palette-note velocity (also the fade rate: harder = brighter
// + snappier). Keep a floor so a dim wash still reads.
int baseVelFor (int brightness) { return clampVel (45.0 + brightness * 0.82); }

// Append a note, snapping onto the grid and clipping to [0, length]. Drops notes
// that would be zero-length or start past the end.
void emit (Clip& clip, int pitch, double start, double len, int vel, double length)
{
    double s = snapToGrid (start);
    double e = snapToGrid (start + len);
    s = juce::jlimit (0.0, length, s);
    e = juce::jlimit (0.0, length, e);
    if (e - s < kGridBeats * 0.5)
        return;
    clip.notes.push_back ({ pitch, juce::jlimit (1, 127, vel), s, e - s });
}
}  // namespace

Clip design (const Clip& drumsClip, const Clip& bassClip, const Clip& synthsClip,
             const DesignParams& params)
{
    const auto drums  = ClipAnalysis::drums  (drumsClip);
    const auto bass   = ClipAnalysis::bass   (bassClip);
    const auto synth  = ClipAnalysis::synths (synthsClip);

    Clip out;

    // ---- length -------------------------------------------------------------
    double length = params.lengthBeats > 0.0 ? params.lengthBeats
                                             : drums.sourceLenBeats;
    if (length <= 0.0) length = MidiClipIO::kBeatsPerBar;   // fallback: 1 bar
    length = std::max (kGridBeats, snapToGrid (length));
    out.lengthBeats = length;

    const double srcLen = drums.present && drums.sourceLenBeats > 0.0
                            ? drums.sourceLenBeats : length;

    // ---- colours ------------------------------------------------------------
    std::vector<int> colors = params.colorPitches;
    if (colors.empty())
        colors.push_back (vox::primaryPitch (1));   // default: Red
    const int base = colors.front();
    const bool haveAccents = colors.size() >= 2;

    const int dyn = juce::jlimit (0, 100, params.dynamics);
    const int baseVel = baseVelFor (params.brightness);

    SplitMix64 rng (params.seed ? params.seed : 1);
    const int chasePitch   = rng.pick (vox::kChasePool);
    // Pad-like synths lean on the smoother breathes (front of the pool).
    const int breathePitch = synth.padLike ? vox::kBreathePool[0]
                                           : rng.pick (vox::kBreathePool);

    // Bass activity sampled at an arbitrary beat, tiled across the design length.
    auto bassAt = [&bass] (double beat) -> float
    {
        if (! bass.present || bass.cell.empty()) return 1.0f;   // no bass clip ⇒ always lit
        double t = std::fmod (beat, bass.sourceLenBeats);
        if (t < 0.0) t += bass.sourceLenBeats;
        int c = static_cast<int> (t / kGridBeats);
        c = juce::jlimit (0, static_cast<int> (bass.cell.size()) - 1, c);
        return bass.cell[static_cast<size_t> (c)];
    };

    // ---- active regions -----------------------------------------------------
    // The rig is lit inside a region and dark between them (darkness = no notes).
    // Bass gates the regions; with no bass clip the whole clip is one region.
    // EVERY light layer is gated to these regions, so a lit stretch always
    // carries the chosen colour (never bare white) and rests are truly dark.
    struct Region { double start, end; };
    std::vector<Region> regions;
    if (! bass.present)
    {
        regions.push_back ({ 0.0, length });
    }
    else
    {
        const int nCells = static_cast<int> (std::ceil (length / kGridBeats));
        int start = -1;
        for (int i = 0; i <= nCells; ++i)
        {
            const bool active = i < nCells && bassAt (i * kGridBeats) > 0.05f;
            if (active && start < 0) start = i;
            if (! active && start >= 0)
            {
                regions.push_back ({ start * kGridBeats, i * kGridBeats });
                start = -1;
            }
        }
        // Merge across short gaps, drop slivers.
        std::vector<Region> merged;
        for (const auto& r : regions)
        {
            if (! merged.empty() && r.start - merged.back().end < 0.5)
                merged.back().end = r.end;
            else
                merged.push_back (r);
        }
        regions.clear();
        for (const auto& r : merged)
            if (r.end - r.start >= kGridBeats) regions.push_back (r);
        if (regions.empty()) regions.push_back ({ 0.0, length });   // bass ~silent: light anyway
    }

    // Tiled drum onsets across [0, length), each with a strong flag.
    struct Hit { double beat; int vel; bool strong; };
    std::vector<Hit> hits;
    if (drums.present)
    {
        const int reps = static_cast<int> (std::ceil (length / srcLen));
        for (int r = 0; r < reps; ++r)
            for (const auto& o : drums.onsets)
            {
                const double beat = o.beat + r * srcLen;
                if (beat < length - 1e-6)
                    hits.push_back ({ beat, o.vel, o.vel >= drums.strongVel });
            }
        std::sort (hits.begin(), hits.end(),
                   [] (const Hit& a, const Hit& b) { return a.beat < b.beat; });
    }
    auto inRegion = [] (const Region& r, double beat)
    { return beat >= r.start - 1e-6 && beat < r.end - 1e-6; };
    auto isFillAt = [&] (double beat) -> bool
    {
        if (! drums.present || drums.fillBar.empty()) return false;
        const int bar = static_cast<int> (beat / MidiClipIO::kBeatsPerBar)
                            % static_cast<int> (drums.fillBar.size());
        return drums.fillBar[static_cast<size_t> (bar)];
    };

    // Pump beats: which onsets carry a colour re-strike (busier as dynamics rise).
    auto pumps = [&] (const Hit& h) -> bool
    {
        const bool downbeat = std::abs (h.beat - std::round (h.beat)) < 1e-6;
        return downbeat || h.strong || dyn > 60;
    };

    const int wildAccent = rng.pick (vox::kWildPool);

    // ---- per-region composition --------------------------------------------
    for (const auto& reg : regions)
    {
        // Colour bed.
        if (haveAccents)
        {
            // Held base wash across the region; accents pulse on strong hits.
            emit (out, base, reg.start, reg.end - reg.start,
                  clampVel (baseVel * 0.9), length);
            int accentTurn = 0;
            for (const auto& h : hits)
                if (h.strong && inRegion (reg, h.beat))
                {
                    const int accent = colors[static_cast<size_t> (
                        1 + accentTurn++ % (static_cast<int> (colors.size()) - 1))];
                    emit (out, accent, h.beat, 0.5,
                          clampVel (baseVel * (0.6 + 0.4 * h.vel / 127.0)), length);
                }
        }
        else
        {
            // Single colour: re-strike the base on each pump beat, back-to-back
            // (no gaps ⇒ the colour pulses on the beat but never drops to white).
            std::vector<Hit> beats;
            for (const auto& h : hits)
                if (inRegion (reg, h.beat) && pumps (h)) beats.push_back (h);
            if (beats.empty())
            {
                emit (out, base, reg.start, reg.end - reg.start, clampVel (baseVel * 0.9), length);
            }
            else
            {
                for (size_t i = 0; i < beats.size(); ++i)
                {
                    const double s = beats[i].beat;
                    const double e = (i + 1 < beats.size()) ? beats[i + 1].beat : reg.end;
                    emit (out, base, s, e - s,
                          clampVel (baseVel * (0.65 + 0.35 * beats[i].vel / 127.0)), length);
                }
                // Lead-in: colour the region head before the first pump.
                if (beats.front().beat > reg.start + 1e-6)
                    emit (out, base, reg.start, beats.front().beat - reg.start,
                          clampVel (baseVel * 0.7), length);
            }
        }

        // Motion (one recipe per region, keyed by dynamics), gated to the region.
        const double rlen = reg.end - reg.start;
        if (dyn < 33)
            emit (out, breathePitch, reg.start, rlen, clampVel (45 + dyn), length);
        else if (dyn <= 66)
            emit (out, chasePitch, reg.start, rlen, clampVel (64), length);
        else
        {
            emit (out, chasePitch, reg.start, rlen, clampVel (70 + (dyn - 66) / 3), length);
            for (const auto& h : hits)
                if (h.strong && inRegion (reg, h.beat) && isFillAt (h.beat))
                    emit (out, wildAccent, h.beat, kGridBeats, clampVel (80), length);
        }

        // High-energy structural motion: one L/R alternation per bar (opt-in via
        // very high dynamics on busy material), gated to the region.
        if (dyn >= 90 && drums.present && drums.medianPerBar >= 4)
        {
            const int b0 = static_cast<int> (reg.start / MidiClipIO::kBeatsPerBar);
            const int b1 = static_cast<int> (std::ceil (reg.end / MidiClipIO::kBeatsPerBar));
            for (int b = b0; b < b1; ++b)
            {
                const double s = std::max (reg.start, b * MidiClipIO::kBeatsPerBar);
                const double e = std::min (reg.end, (b + 1) * MidiClipIO::kBeatsPerBar);
                if (e > s)
                    emit (out, (b % 2 == 0) ? vox::kBarLeft : vox::kBarRight, s, e - s, 100, length);
            }
        }
    }

    // ---- warm spots on calm, pad-heavy stretches (whole clip) ---------------
    if (dyn < 40 && synth.present && synth.padLike)
    {
        emit (out, vox::kSpotLwarm, 0.0, length, baseVel, length);
        emit (out, vox::kSpotRwarm, 0.0, length, baseVel, length);
    }

    // Deterministic ordering (start, then pitch) so output is byte-stable.
    std::stable_sort (out.notes.begin(), out.notes.end(),
                      [] (const Note& a, const Note& b)
                      {
                          if (a.startBeats < b.startBeats) return true;
                          if (b.startBeats < a.startBeats) return false;
                          return a.pitch < b.pitch;
                      });
    return out;
}

}  // namespace hitdesign

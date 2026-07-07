#include "ClipAnalysis.h"

#include <algorithm>
#include <cmath>
#include <map>

namespace hitdesign
{

DrumFeatures ClipAnalysis::drums (const Clip& c)
{
    DrumFeatures f;
    f.present = ! c.empty();
    f.sourceLenBeats = c.lengthBeats;
    if (! f.present)
        return f;

    // Collapse onsets into 1/16 grid cells, summing velocity within a cell.
    std::map<long long, int> cellVel;
    for (const auto& n : c.notes)
    {
        const long long cell = llround (n.startBeats / kGridBeats);
        cellVel[cell] = std::min (127, cellVel[cell] + n.velocity);
    }
    f.onsets.reserve (cellVel.size());
    for (const auto& [cell, vel] : cellVel)
        f.onsets.push_back ({ static_cast<double> (cell) * kGridBeats, vel });

    // Strong-onset threshold = 75th percentile of onset velocities.
    std::vector<int> vels;
    vels.reserve (f.onsets.size());
    for (const auto& o : f.onsets) vels.push_back (o.vel);
    std::sort (vels.begin(), vels.end());
    if (! vels.empty())
    {
        const size_t idx = (vels.size() * 3) / 4;
        f.strongVel = vels[std::min (idx, vels.size() - 1)];
        f.strongVel = std::max (f.strongVel, 1);
    }

    // Per-bar onset counts, median, and fill bars (a burst well above median).
    const int bars = std::max (1, static_cast<int> (std::ceil (c.lengthBeats
                                                    / MidiClipIO::kBeatsPerBar)));
    f.onsetsPerBar.assign (static_cast<size_t> (bars), 0);
    for (const auto& o : f.onsets)
    {
        const int b = static_cast<int> (o.beat / MidiClipIO::kBeatsPerBar);
        if (b >= 0 && b < bars) ++f.onsetsPerBar[static_cast<size_t> (b)];
    }
    {
        std::vector<int> sorted = f.onsetsPerBar;
        std::sort (sorted.begin(), sorted.end());
        f.medianPerBar = sorted[sorted.size() / 2];
    }
    f.fillBar.assign (static_cast<size_t> (bars), false);
    for (int b = 0; b < bars; ++b)
    {
        const int n = f.onsetsPerBar[static_cast<size_t> (b)];
        f.fillBar[static_cast<size_t> (b)] =
            n > f.medianPerBar && n >= std::max (3, (f.medianPerBar * 8) / 5);
    }
    return f;
}

BassFeatures ClipAnalysis::bass (const Clip& c)
{
    BassFeatures f;
    f.present = ! c.empty();
    f.sourceLenBeats = c.lengthBeats;
    if (! f.present)
        return f;

    const int nCells = std::max (1, static_cast<int> (std::ceil (c.lengthBeats / kGridBeats)));
    f.cell.assign (static_cast<size_t> (nCells), 0.0f);

    for (const auto& n : c.notes)
    {
        const float v = static_cast<float> (n.velocity) / 127.0f;
        const int c0 = std::max (0, static_cast<int> (std::floor (n.startBeats / kGridBeats)));
        const int c1 = std::min (nCells, static_cast<int> (std::ceil (n.endBeats() / kGridBeats)));
        for (int i = c0; i < c1; ++i)
            f.cell[static_cast<size_t> (i)] = std::max (f.cell[static_cast<size_t> (i)], v);
    }

    double sum = 0.0;
    for (float v : f.cell) sum += v;
    f.meanActivity = static_cast<float> (sum / nCells);
    return f;
}

SynthFeatures ClipAnalysis::synths (const Clip& c)
{
    SynthFeatures f;
    f.present = ! c.empty();
    f.sourceLenBeats = c.lengthBeats;
    if (! f.present)
        return f;

    double lenSum = 0.0;
    for (const auto& n : c.notes) lenSum += n.lenBeats;
    f.sustainRatio = lenSum / static_cast<double> (c.notes.size());   // beats/note

    // Movement: how often the pitch changes, per bar.
    int changes = 0;
    for (size_t i = 1; i < c.notes.size(); ++i)
        if (c.notes[i].pitch != c.notes[i - 1].pitch)
            ++changes;
    const double bars = std::max (1.0, c.lengthBeats / MidiClipIO::kBeatsPerBar);
    f.movement = changes / bars;

    // Pad-like: long notes, not much movement.
    f.padLike = f.sustainRatio >= 1.5 && f.movement <= 2.0;
    return f;
}

}  // namespace hitdesign

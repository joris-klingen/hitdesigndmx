// hitdesign — design a HitNoteDmx-triggering MIDI clip from drums/bass/synths
// input clips plus colour / dynamics / brightness controls.
//
//   hitdesign <drums.mid> [--bass b.mid] [--synths s.mid]
//             --colors "Red,Amber" [--dynamics 70] [--brightness 80]
//             [--bars N] [--seed K] -o out.mid
//   hitdesign --list-colors
//   hitdesign selftest          (vocabulary drift guard + engine invariants)

#include <cmath>
#include <iostream>

#include <juce_audio_basics/juce_audio_basics.h>

#include "ClipAnalysis.h"
#include "DesignEngine.h"
#include "DesignVocab.h"
#include "MidiClipIO.h"
#include "Palette.h"
#include "TriggerVocabulary.h"

using namespace hitdesign;

namespace
{
void listColors()
{
    std::cout << "Primary palette (pitch " << hitnotedmx::kPrimaryPaletteStart << "..):\n";
    for (int i = 0; i < hitnotedmx::kPaletteSize; ++i)
        std::cout << "  " << hitnotedmx::kPaletteNames[static_cast<size_t> (i)] << '\n';
    std::cout << "Secondary palette (pitch " << hitnotedmx::kSecondaryPaletteStart << "..):\n";
    for (int i = 0; i < hitnotedmx::kSecondaryPaletteSize; ++i)
        std::cout << "  " << hitnotedmx::kSecondaryPaletteNames[static_cast<size_t> (i)] << '\n';
}

// A flag's value, or {} if absent. Supports "--flag value" and "--flag=value".
juce::String optValue (const juce::StringArray& args, const juce::String& flag)
{
    for (int i = 0; i < args.size(); ++i)
    {
        if (args[i] == flag && i + 1 < args.size()) return args[i + 1];
        if (args[i].startsWith (flag + "=")) return args[i].fromFirstOccurrenceOf ("=", false, false);
    }
    return {};
}

std::vector<int> parseColors (const juce::String& csv, juce::String& err)
{
    std::vector<int> out;
    juce::StringArray names;
    names.addTokens (csv, ",", "");
    for (auto& n : names)
    {
        const auto t = n.trim();
        if (t.isEmpty()) continue;
        const int p = vox::colorNameToPitch (t);
        if (p < 0) { err = "unknown colour: '" + t + "' (try --list-colors)"; return {}; }
        out.push_back (p);
    }
    if (out.empty()) err = "no colours given";
    return out;
}

// ---- selftest: build fixtures in memory, design across a params sweep -------
Clip fixtureDrums()
{
    Clip c; c.lengthBeats = 16.0;
    for (int beat = 0; beat < 16; ++beat)
    {
        c.notes.push_back ({ 36, 110, double (beat), 0.25 });                  // kick per beat
        if (beat % 2 == 1) c.notes.push_back ({ 38, 100, double (beat), 0.25 }); // snare 2&4
        c.notes.push_back ({ 42, 70, beat + 0.5, 0.25 });                       // hat off-beat
        if (beat == 15) for (int k = 0; k < 4; ++k)                              // a fill
            c.notes.push_back ({ 38, 120, 15.0 + k * 0.25, 0.25 });
    }
    return c;
}
Clip fixtureBass()
{
    Clip c; c.lengthBeats = 16.0;
    for (int beat = 0; beat < 16; ++beat)
        if (beat / 4 != 2)   // quiet in bar 3
            c.notes.push_back ({ 40, 90, double (beat), 0.9 });
    return c;
}
Clip fixtureSynths()
{
    Clip c; c.lengthBeats = 16.0;
    for (int p : { 60, 64, 67 })
        c.notes.push_back ({ p, 80, 0.0, 16.0 });   // a held pad chord
    return c;
}

bool onGrid (double b) { return std::abs (b / kGridBeats - std::round (b / kGridBeats)) < 1e-6; }

int selftest()
{
    if (auto e = vox::selfCheck(); e.isNotEmpty())
    {
        std::cerr << "vocab drift: " << e << '\n';
        return 1;
    }

    const Clip drums = fixtureDrums(), bass = fixtureBass(), synths = fixtureSynths();
    const std::vector<std::vector<int>> colorSets {
        { vox::primaryPitch (1) },                                        // Red
        { vox::primaryPitch (1), vox::primaryPitch (4) },                 // Red, Amber
        { vox::primaryPitch (12), vox::primaryPitch (10), vox::secondaryPitch (2) },
    };

    int cases = 0;
    for (int dyn : { 10, 50, 95 })
    for (int bri : { 20, 80 })
    for (const auto& cols : colorSets)
    for (std::uint64_t seed : { 1ull, 7ull })
    for (double bars : { 0.0, 8.0 })   // 0 = inherit drums length; 8 = 32-beat loop
    {
        DesignParams p;
        p.colorPitches = cols; p.dynamics = dyn; p.brightness = bri;
        p.seed = seed;
        p.lengthBeats = bars * MidiClipIO::kBeatsPerBar;
        const double wantLen = bars > 0 ? bars * MidiClipIO::kBeatsPerBar : drums.lengthBeats;

        Clip out = design (drums, bass, synths, p);
        ++cases;

        auto fail = [&] (const juce::String& why) -> int
        {
            std::cerr << "case dyn=" << dyn << " bri=" << bri << " seed=" << seed
                      << " bars=" << bars << ": " << why << '\n';
            return 1;
        };

        if (std::abs (out.lengthBeats - wantLen) > 1e-6) return fail ("length not honoured");
        if (out.notes.empty())                           return fail ("no notes emitted");

        for (const auto& n : out.notes)
        {
            if (n.pitch == 0)                            return fail ("blackout note emitted");
            if (hitnotedmx::vocab::chainName (n.pitch) == "-")
                return fail ("off-vocabulary pitch " + juce::String (n.pitch));
            if (! onGrid (n.startBeats) || ! onGrid (n.endBeats()))
                return fail ("off-grid note at " + juce::String (n.startBeats));
            if (n.lenBeats <= 0.0)                       return fail ("non-positive length");
            if (n.endBeats() > out.lengthBeats + 1e-6)   return fail ("note past clip end");
            if (n.velocity < 1 || n.velocity > 127)      return fail ("velocity out of range");
        }

        // Determinism: same inputs + seed ⇒ identical output.
        Clip again = design (drums, bass, synths, p);
        if (again.notes.size() != out.notes.size()) return fail ("non-deterministic (count)");
        for (size_t i = 0; i < out.notes.size(); ++i)
        {
            const auto& a = out.notes[i]; const auto& b = again.notes[i];
            if (a.pitch != b.pitch || a.velocity != b.velocity
                || std::abs (a.startBeats - b.startBeats) > 1e-9
                || std::abs (a.lenBeats - b.lenBeats) > 1e-9)
                return fail ("non-deterministic (note " + juce::String (int (i)) + ")");
        }
    }

    std::cout << "design-selftest OK (" << cases << " cases, mapping v"
              << hitnotedmx::vocab::kMappingVersion << ")\n";
    return 0;
}

int usage()
{
    std::cout <<
        "hitdesign — design a HitNoteDmx clip from drums/bass/synths\n\n"
        "  hitdesign <drums.mid> [--bass b.mid] [--synths s.mid] \\\n"
        "            --colors \"Red,Amber\" [--dynamics 0..100] [--brightness 0..100] \\\n"
        "            [--bars N] [--seed K] -o out.mid\n"
        "  hitdesign --list-colors\n"
        "  hitdesign selftest\n\n"
        "  --colors     comma-separated palette names; first = base, rest = accents\n"
        "  --dynamics   calm(0) → wild(100); default 50\n"
        "  --brightness dim(0) → bright(100); default 80\n"
        "  --bars       output length in bars (default: the drums clip's length)\n"
        "  --seed       reroll the creative choices deterministically (default 1)\n";
    return 1;
}
}  // namespace

int main (int argc, char* argv[])
{
    juce::StringArray args;
    for (int i = 1; i < argc; ++i) args.add (juce::String (argv[i]));

    if (args.isEmpty())            return usage();
    if (args.contains ("selftest")) return selftest();
    if (args.contains ("--list-colors")) { listColors(); return 0; }

    const juce::File drumsFile (juce::File::getCurrentWorkingDirectory().getChildFile (args[0]));
    juce::String err;
    Clip drums;
    if (! MidiClipIO::read (drumsFile, drums, err)) { std::cerr << err << '\n'; return 1; }

    Clip bass, synths;
    auto readOpt = [&] (const juce::String& flag, Clip& into) -> bool
    {
        const auto v = optValue (args, flag);
        if (v.isEmpty()) return true;
        const juce::File f (juce::File::getCurrentWorkingDirectory().getChildFile (v));
        if (! MidiClipIO::read (f, into, err)) { std::cerr << err << '\n'; return false; }
        return true;
    };
    if (! readOpt ("--bass", bass))     return 1;
    if (! readOpt ("--synths", synths)) return 1;

    const auto colorsCsv = optValue (args, "--colors");
    if (colorsCsv.isEmpty()) { std::cerr << "--colors is required (see --list-colors)\n"; return 1; }
    DesignParams p;
    p.colorPitches = parseColors (colorsCsv, err);
    if (p.colorPitches.empty()) { std::cerr << err << '\n'; return 1; }

    if (auto v = optValue (args, "--dynamics");   v.isNotEmpty()) p.dynamics   = v.getIntValue();
    if (auto v = optValue (args, "--brightness"); v.isNotEmpty()) p.brightness = v.getIntValue();
    if (auto v = optValue (args, "--seed");       v.isNotEmpty()) p.seed = static_cast<std::uint64_t> (v.getLargeIntValue());
    if (auto v = optValue (args, "--bars");       v.isNotEmpty()) p.lengthBeats = v.getDoubleValue() * MidiClipIO::kBeatsPerBar;

    const Clip out = design (drums, bass, synths, p);

    juce::String outPath = optValue (args, "-o");
    if (outPath.isEmpty()) outPath = optValue (args, "--out");
    if (outPath.isEmpty()) { std::cerr << "-o <out.mid> is required\n"; return 1; }
    const juce::File outFile (juce::File::getCurrentWorkingDirectory().getChildFile (outPath));
    if (! MidiClipIO::write (out, outFile, err)) { std::cerr << err << '\n'; return 1; }

    std::cout << "designed " << out.notes.size() << " notes over "
              << (out.lengthBeats / MidiClipIO::kBeatsPerBar) << " bars → "
              << outFile.getFullPathName() << '\n';
    return 0;
}

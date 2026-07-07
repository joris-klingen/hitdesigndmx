#include "SwatchGrid.h"

#include "Palette.h"

namespace hitdesign
{

using namespace hitnotedmx;

namespace
{
juce::Colour toColour (const PaletteColor& c)
{
    return juce::Colour::fromFloatRGBA (c.r, c.g, c.b, 1.0f);
}
}

SwatchGrid::SwatchGrid()
{
    // Primary palette skips index 0 (Black) — a black swatch is a non-colour here.
    for (int i = 1; i < kPaletteSize; ++i)
        swatches.push_back ({ toColour (kPalette[static_cast<size_t> (i)]),
                              kPrimaryPaletteStart + i, {} });
    for (int i = 0; i < kSecondaryPaletteSize; ++i)
        swatches.push_back ({ toColour (kSecondaryPalette[static_cast<size_t> (i)]),
                              kSecondaryPaletteStart + i, {} });
}

int SwatchGrid::orderOf (int pitch) const
{
    for (int i = 0; i < static_cast<int> (order.size()); ++i)
        if (order[static_cast<size_t> (i)] == pitch) return i;
    return -1;
}

void SwatchGrid::setSelection (const std::vector<int>& pitches)
{
    order.clear();
    for (int p : pitches)
        if (static_cast<int> (order.size()) < kMaxSelect) order.push_back (p);
    repaint();
    if (onChange) onChange();
}

void SwatchGrid::resized()
{
    const int cols = 12;
    const int n = static_cast<int> (swatches.size());
    const int rows = (n + cols - 1) / cols;
    const int gap = 4;
    const int w = (getWidth() - gap * (cols - 1)) / cols;
    const int h = rows > 0 ? juce::jmin (w, (getHeight() - gap * (rows - 1)) / rows) : w;
    for (int i = 0; i < n; ++i)
    {
        const int r = i / cols, c = i % cols;
        swatches[static_cast<size_t> (i)].bounds =
            { c * (w + gap), r * (h + gap), w, h };
    }
}

void SwatchGrid::mouseDown (const juce::MouseEvent& e)
{
    for (const auto& s : swatches)
        if (s.bounds.contains (e.getPosition()))
        {
            const int idx = orderOf (s.pitch);
            if (idx >= 0)
                order.erase (order.begin() + idx);              // toggle off
            else if (static_cast<int> (order.size()) < kMaxSelect)
                order.push_back (s.pitch);                       // add (if room)
            repaint();
            if (onChange) onChange();
            return;
        }
}

void SwatchGrid::paint (juce::Graphics& g)
{
    for (const auto& s : swatches)
    {
        const auto r = s.bounds.toFloat().reduced (1.0f);
        g.setColour (s.colour);
        g.fillRoundedRectangle (r, 3.0f);

        const int idx = orderOf (s.pitch);
        if (idx >= 0)
        {
            g.setColour (juce::Colours::white);
            g.drawRoundedRectangle (r, 3.0f, 2.5f);
            g.setColour (juce::Colours::black.withAlpha (0.55f));
            auto badge = r;
            g.fillEllipse (badge.removeFromTop (16.0f).removeFromLeft (16.0f));
            g.setColour (juce::Colours::white);
            g.setFont (juce::FontOptions (11.0f, juce::Font::bold));
            g.drawText (juce::String (idx + 1), s.bounds.withSize (16, 16),
                        juce::Justification::centred, false);
        }
    }
}

}  // namespace hitdesign

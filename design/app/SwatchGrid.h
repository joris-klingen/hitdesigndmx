#pragma once

#include <functional>
#include <vector>

#include <juce_gui_basics/juce_gui_basics.h>

namespace hitdesign
{

// The palette picker: the real hitnotedmx primary (24) + secondary (12) colours
// as swatches. Click to select up to `maxSelect`; the first pick is the base
// colour, the rest are accents (shown with their order number).
class SwatchGrid : public juce::Component
{
public:
    SwatchGrid();

    std::function<void()> onChange;

    // Selected palette pitches, in pick order (base first).
    std::vector<int> selectedPitches() const { return order; }
    void setSelection (const std::vector<int>& pitches);

    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;

private:
    struct Swatch { juce::Colour colour; int pitch; juce::Rectangle<int> bounds; };
    std::vector<Swatch> swatches;
    std::vector<int>    order;               // selected pitches, in pick order
    static constexpr int kMaxSelect = 3;

    int orderOf (int pitch) const;           // 0-based selection index, or -1

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SwatchGrid)
};

}  // namespace hitdesign

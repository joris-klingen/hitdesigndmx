#pragma once

#include <memory>

#include <juce_gui_basics/juce_gui_basics.h>

#include "DmxVisualizer.h"
#include "DropZone.h"
#include "PlaybackEngine.h"
#include "SwatchGrid.h"
#include "DesignEngine.h"
#include "MidiClipIO.h"

namespace hitdesign
{

// A drag source: press-drag exports the last designed clip as a temp .mid so it
// drops straight onto a HitNoteDmx track in the DAW.
class ClipDragSource : public juce::Component
{
public:
    std::function<Clip()> provideClip;          // returns the clip to export
    std::function<bool()> ready;                // is a design available?
    void paint (juce::Graphics&) override;
    void mouseDrag (const juce::MouseEvent&) override;
private:
    bool exporting = false;
};

class MainComponent : public juce::Component,
                      public juce::DragAndDropContainer
{
public:
    MainComponent();
    ~MainComponent() override;

    // Preload clips by path (drums, bass, synths in order) — lets the app be
    // launched with clips dropped on its icon or from a script.
    void loadInitialClips (const juce::StringArray& midiPaths);

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void loadClip (DropZone& zone, Clip& into, bool& flag, const juce::File& file,
                   const juce::String& role, bool isDrums);
    void refreshDefaultLength();
    void regenerate();
    void doSave();
    void refreshTransportLabel();

    // Inputs
    DropZone drumsZone  { "Drums" };
    DropZone bassZone   { "Bass" };
    DropZone synthsZone { "Synths" };
    Clip drumsClip, bassClip, synthsClip;
    bool hasDrums = false, hasBass = false, hasSynths = false;

    // Controls
    SwatchGrid   swatches;
    juce::Label  swatchLabel;
    juce::Slider dynamics, brightness;
    juce::Label  dynamicsLabel, brightnessLabel;
    juce::Slider lengthBars;
    juce::Label  lengthLabel;
    juce::ToggleButton autoLength { "auto (drums)" };
    juce::TextEditor   seedEditor;
    juce::Label        seedLabel;
    juce::TextButton   rerollBtn { "Reroll" };

    // Output
    juce::TextButton generateBtn { "Generate" };
    juce::TextButton saveBtn     { "Save .mid..." };
    ClipDragSource   dragOut;
    Clip             designedClip;
    bool             haveDesign = false;
    std::unique_ptr<juce::FileChooser> chooser;

    // Preview
    PlaybackEngine            playback;
    hitnotedmx::DmxVisualizer visualizer { playback.values(), playback.selection() };
    juce::TextButton   playBtn { "Play" };
    juce::ToggleButton loopToggle { "Loop" };
    juce::Slider       bpm;
    juce::Label        bpmLabel, transportLabel;
    juce::TextButton   connectBtn { "Connect USB" };
    juce::Label        statusLabel;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MainComponent)
};

}  // namespace hitdesign

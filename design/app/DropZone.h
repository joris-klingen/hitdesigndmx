#pragma once

#include <functional>
#include <memory>

#include <juce_gui_basics/juce_gui_basics.h>

namespace hitdesign
{

// One labelled drop target for a role's MIDI clip (Drums / Bass / Synths).
// Accepts a dropped .mid, or a click opens a file browser. Shows a summary
// once a clip is loaded; a small ✕ clears it.
class DropZone : public juce::Component,
                 public juce::FileDragAndDropTarget
{
public:
    explicit DropZone (juce::String roleTitle);

    std::function<void (const juce::File&)> onFile;   // a valid .mid was chosen
    std::function<void()>                   onCleared;

    void setSummary (const juce::String& text);
    void setLoaded (bool isLoaded);

    bool isInterestedInFileDrag (const juce::StringArray& files) override;
    void fileDragEnter (const juce::StringArray&, int, int) override;
    void fileDragExit  (const juce::StringArray&) override;
    void filesDropped  (const juce::StringArray& files, int, int) override;

    void paint (juce::Graphics&) override;
    void resized() override;
    void mouseDown (const juce::MouseEvent&) override;

private:
    static bool looksLikeMidi (const juce::String& path);
    void browse();

    juce::String title;
    juce::String summary { "drop a .mid, or click to browse" };
    bool         loaded { false };
    bool         dragOver { false };
    juce::TextButton clearBtn { "X" };
    std::unique_ptr<juce::FileChooser> chooser;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (DropZone)
};

}  // namespace hitdesign

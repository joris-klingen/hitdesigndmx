#include "DropZone.h"

namespace hitdesign
{

DropZone::DropZone (juce::String roleTitle) : title (std::move (roleTitle))
{
    addChildComponent (clearBtn);
    clearBtn.setTooltip ("Clear this clip");
    clearBtn.onClick = [this]
    {
        setLoaded (false);
        summary = "drop a .mid, or click to browse";
        if (onCleared) onCleared();
        repaint();
    };
}

bool DropZone::looksLikeMidi (const juce::String& path)
{
    return path.endsWithIgnoreCase (".mid") || path.endsWithIgnoreCase (".midi");
}

bool DropZone::isInterestedInFileDrag (const juce::StringArray& files)
{
    for (const auto& f : files) if (looksLikeMidi (f)) return true;
    return false;
}

void DropZone::fileDragEnter (const juce::StringArray&, int, int) { dragOver = true;  repaint(); }
void DropZone::fileDragExit  (const juce::StringArray&)           { dragOver = false; repaint(); }

void DropZone::filesDropped (const juce::StringArray& files, int, int)
{
    dragOver = false;
    for (const auto& f : files)
        if (looksLikeMidi (f))
        {
            if (onFile) onFile (juce::File (f));
            break;
        }
    repaint();
}

void DropZone::mouseDown (const juce::MouseEvent& e)
{
    if (! clearBtn.getBounds().contains (e.getPosition()))
        browse();
}

void DropZone::browse()
{
    chooser = std::make_unique<juce::FileChooser> ("Choose a " + title + " MIDI clip",
                                                   juce::File(), "*.mid;*.midi");
    chooser->launchAsync (juce::FileBrowserComponent::openMode
                          | juce::FileBrowserComponent::canSelectFiles,
                          [this] (const juce::FileChooser& fc)
                          {
                              const auto f = fc.getResult();
                              if (f.existsAsFile() && onFile) onFile (f);
                          });
}

void DropZone::setSummary (const juce::String& text) { summary = text; repaint(); }

void DropZone::setLoaded (bool isLoaded)
{
    loaded = isLoaded;
    clearBtn.setVisible (isLoaded);
    repaint();
}

void DropZone::paint (juce::Graphics& g)
{
    auto r = getLocalBounds().toFloat().reduced (2.0f);
    const auto accent = loaded ? juce::Colour (0xff3a7d44) : juce::Colour (0xff4a4a4a);
    g.setColour (dragOver ? juce::Colour (0xff2b6cb0) : accent.withAlpha (0.25f));
    g.fillRoundedRectangle (r, 6.0f);
    g.setColour (dragOver ? juce::Colour (0xff63b3ed) : accent);
    g.drawRoundedRectangle (r, 6.0f, dragOver ? 2.0f : 1.2f);

    g.setColour (juce::Colours::white);
    g.setFont (juce::FontOptions (15.0f, juce::Font::bold));
    g.drawText (title, r.reduced (10.0f, 6.0f).removeFromTop (20.0f),
                juce::Justification::topLeft, false);

    g.setColour (juce::Colour (0xffb8b8b8));
    g.setFont (juce::FontOptions (12.0f));
    g.drawFittedText (summary, r.reduced (10.0f).withTrimmedTop (22.0f).toNearestInt(),
                      juce::Justification::topLeft, 3);
}

void DropZone::resized()
{
    clearBtn.setBounds (getWidth() - 26, 6, 20, 20);
}

}  // namespace hitdesign

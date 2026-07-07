#include <juce_gui_basics/juce_gui_basics.h>

#include "MainComponent.h"

namespace hitdesign
{

// The HitDesign standalone app: drag in drums/bass/synths clips, choose colours
// + dynamics + brightness, and design a MIDI clip that triggers HitNoteDmx —
// previewed live through the real composition path on the shared rig visualiser.
class HitDesignApplication : public juce::JUCEApplication
{
public:
    const juce::String getApplicationName() override    { return "HitDesign"; }
    const juce::String getApplicationVersion() override { return "0.1.0"; }
    bool moreThanOneInstanceAllowed() override          { return true; }

    void initialise (const juce::String&) override
    {
        mainWindow = std::make_unique<MainWindow> (getApplicationName(),
                                                   getCommandLineParameterArray());
    }

    void shutdown() override { mainWindow = nullptr; }

    void systemRequestedQuit() override { quit(); }

    class MainWindow : public juce::DocumentWindow
    {
    public:
        MainWindow (juce::String name, const juce::StringArray& clipArgs)
            : DocumentWindow (name,
                              juce::Desktop::getInstance().getDefaultLookAndFeel()
                                  .findColour (juce::ResizableWindow::backgroundColourId),
                              DocumentWindow::allButtons)
        {
            setUsingNativeTitleBar (true);
            auto* content = new MainComponent();
            setContentOwned (content, true);
            setResizable (true, true);
            setResizeLimits (760, 520, 4000, 3000);
            centreWithSize (getWidth(), getHeight());
            setVisible (true);
            content->loadInitialClips (clipArgs);
        }

        void closeButtonPressed() override
        {
            JUCEApplication::getInstance()->systemRequestedQuit();
        }

        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MainWindow)
    };

private:
    std::unique_ptr<MainWindow> mainWindow;
};

}  // namespace hitdesign

START_JUCE_APPLICATION (hitdesign::HitDesignApplication)

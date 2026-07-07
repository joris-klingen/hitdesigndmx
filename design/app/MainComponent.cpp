#include "MainComponent.h"

#include "ClipAnalysis.h"
#include "Palette.h"
#include "TriggerVocabulary.h"

namespace hitdesign
{

// ---- ClipDragSource ---------------------------------------------------------
void ClipDragSource::paint (juce::Graphics& g)
{
    auto r = getLocalBounds().toFloat().reduced (2.0f);
    const bool on = ready && ready();
    g.setColour (juce::Colour (on ? 0xff2b6cb0 : 0xff3a3a3a).withAlpha (0.5f));
    g.fillRoundedRectangle (r, 6.0f);
    g.setColour (on ? juce::Colour (0xff90cdf4) : juce::Colour (0xff666666));
    g.drawRoundedRectangle (r, 6.0f, 1.2f);
    g.setColour (on ? juce::Colours::white : juce::Colour (0xff888888));
    g.setFont (juce::FontOptions (13.0f, juce::Font::bold));
    g.drawFittedText (on ? "Drag to your DAW ->" : "Generate first",
                      r.toNearestInt(), juce::Justification::centred, 1);
}

void ClipDragSource::mouseDrag (const juce::MouseEvent&)
{
    if (exporting || ! (ready && ready()) || ! provideClip) return;
    const Clip clip = provideClip();
    if (clip.notes.empty()) return;

    auto tmp = juce::File::getSpecialLocation (juce::File::tempDirectory)
                   .getChildFile ("HitDesign-drag.mid");
    juce::String err;
    if (! MidiClipIO::write (clip, tmp, err)) return;

    exporting = true;
    if (auto* c = juce::DragAndDropContainer::findParentDragContainerFor (this))
        c->performExternalDragDropOfFiles ({ tmp.getFullPathName() }, false, this,
                                           [this] { exporting = false; });
    else
        exporting = false;
}

// ---- MainComponent ----------------------------------------------------------
MainComponent::MainComponent()
{
    auto addSlider = [this] (juce::Slider& s, juce::Label& l, const juce::String& name,
                             double lo, double hi, double val, double step)
    {
        s.setSliderStyle (juce::Slider::LinearHorizontal);
        s.setTextBoxStyle (juce::Slider::TextBoxRight, false, 48, 20);
        s.setRange (lo, hi, step);
        s.setValue (val, juce::dontSendNotification);
        addAndMakeVisible (s);
        l.setText (name, juce::dontSendNotification);
        l.setFont (juce::FontOptions (12.0f, juce::Font::bold));
        addAndMakeVisible (l);
    };

    for (auto* z : { &drumsZone, &bassZone, &synthsZone }) addAndMakeVisible (z);
    drumsZone.onFile  = [this] (const juce::File& f) { loadClip (drumsZone,  drumsClip,  hasDrums,  f, "Drums",  true);  };
    bassZone.onFile   = [this] (const juce::File& f) { loadClip (bassZone,   bassClip,   hasBass,   f, "Bass",   false); };
    synthsZone.onFile = [this] (const juce::File& f) { loadClip (synthsZone, synthsClip, hasSynths, f, "Synths", false); };
    drumsZone.onCleared  = [this] { hasDrums  = false; refreshDefaultLength(); };
    bassZone.onCleared   = [this] { hasBass   = false; regenerate(); };
    synthsZone.onCleared = [this] { hasSynths = false; regenerate(); };

    swatchLabel.setText ("Colours (1 base + up to 2 accents)", juce::dontSendNotification);
    swatchLabel.setFont (juce::FontOptions (12.0f, juce::Font::bold));
    addAndMakeVisible (swatchLabel);
    addAndMakeVisible (swatches);
    swatches.setSelection ({ hitnotedmx::kPrimaryPaletteStart + 1 });   // default Red
    swatches.onChange = [this] { regenerate(); };

    addSlider (dynamics,   dynamicsLabel,   "Dynamics",   0, 100, 55, 1);
    addSlider (brightness, brightnessLabel, "Brightness", 0, 100, 80, 1);
    dynamics.onValueChange   = [this] { regenerate(); };
    brightness.onValueChange = [this] { regenerate(); };

    addSlider (lengthBars, lengthLabel, "Length (bars)", 1, 64, 4, 1);
    lengthBars.onValueChange = [this] { if (! autoLength.getToggleState()) regenerate(); };
    autoLength.setToggleState (true, juce::dontSendNotification);
    autoLength.onClick = [this]
    {
        lengthBars.setEnabled (! autoLength.getToggleState());
        refreshDefaultLength();
    };
    lengthBars.setEnabled (false);
    addAndMakeVisible (autoLength);

    seedLabel.setText ("Seed", juce::dontSendNotification);
    seedLabel.setFont (juce::FontOptions (12.0f, juce::Font::bold));
    addAndMakeVisible (seedLabel);
    seedEditor.setText ("1", juce::dontSendNotification);
    seedEditor.setInputRestrictions (9, "0123456789");
    seedEditor.onTextChange = [this] { regenerate(); };
    addAndMakeVisible (seedEditor);
    rerollBtn.onClick = [this]
    {
        seedEditor.setText (juce::String (seedEditor.getText().getLargeIntValue() + 1),
                            juce::dontSendNotification);
        regenerate();
    };
    addAndMakeVisible (rerollBtn);

    generateBtn.onClick = [this] { regenerate(); };
    addAndMakeVisible (generateBtn);
    saveBtn.onClick = [this] { doSave(); };
    saveBtn.setEnabled (false);
    addAndMakeVisible (saveBtn);
    dragOut.ready = [this] { return haveDesign; };
    dragOut.provideClip = [this] { return designedClip; };
    addAndMakeVisible (dragOut);

    // Preview
    visualizer.setGrid (playback.rig());
    addAndMakeVisible (visualizer);
    playback.onFrame = [this] { visualizer.repaintIfChanged(); refreshTransportLabel(); };
    playBtn.onClick = [this]
    {
        if (playback.isPlaying()) { playback.stop(); playBtn.setButtonText ("Play"); }
        else                      { playback.play(); playBtn.setButtonText ("Stop"); }
    };
    addAndMakeVisible (playBtn);
    loopToggle.setToggleState (true, juce::dontSendNotification);
    loopToggle.onClick = [this] { playback.setLooping (loopToggle.getToggleState()); };
    addAndMakeVisible (loopToggle);
    addSlider (bpm, bpmLabel, "BPM", 40, 220, 120, 1);
    bpm.onValueChange = [this] { playback.setBpm (bpm.getValue()); };
    playback.setBpm (120.0);

    transportLabel.setFont (juce::FontOptions (12.0f));
    addAndMakeVisible (transportLabel);

    connectBtn.onClick = [this]
    {
        if (playback.driver().isRunning()) { playback.driver().disconnect(); playback.setSendToDmx (false); }
        else                               { playback.driver().connect();    playback.setSendToDmx (true); }
        connectBtn.setButtonText (playback.driver().isRunning() ? "Disconnect" : "Connect USB");
        statusLabel.setText (playback.driver().getStatusText(), juce::dontSendNotification);
    };
    addAndMakeVisible (connectBtn);
    statusLabel.setFont (juce::FontOptions (11.0f));
    statusLabel.setText ("No DMX widget connected", juce::dontSendNotification);
    addAndMakeVisible (statusLabel);

    setSize (940, 640);
}

MainComponent::~MainComponent() { playback.stop(); }

void MainComponent::loadClip (DropZone& zone, Clip& into, bool& flag, const juce::File& file,
                              const juce::String& role, bool isDrums)
{
    juce::String err;
    Clip clip;
    if (! MidiClipIO::read (file, clip, err))
    {
        zone.setSummary ("⚠ " + err);
        zone.setLoaded (false);
        flag = false;
        return;
    }
    into = clip;
    flag = true;
    const int bars = juce::roundToInt (clip.lengthBeats / MidiClipIO::kBeatsPerBar);
    zone.setSummary (file.getFileName() + "\n" + juce::String (clip.notes.size())
                     + " notes · " + juce::String (bars) + " bars");
    zone.setLoaded (true);
    if (isDrums) refreshDefaultLength();
    else         regenerate();
}

void MainComponent::loadInitialClips (const juce::StringArray& midiPaths)
{
    struct Slot { DropZone& zone; Clip& clip; bool& flag; const char* role; bool drums; };
    const Slot slots[] {
        { drumsZone,  drumsClip,  hasDrums,  "Drums",  true  },
        { bassZone,   bassClip,   hasBass,   "Bass",   false },
        { synthsZone, synthsClip, hasSynths, "Synths", false },
    };
    for (int i = 0; i < midiPaths.size() && i < 3; ++i)
    {
        const juce::File f (midiPaths[i]);
        if (f.existsAsFile())
            loadClip (slots[i].zone, slots[i].clip, slots[i].flag, f,
                      slots[i].role, slots[i].drums);
    }
}

void MainComponent::refreshDefaultLength()
{
    if (autoLength.getToggleState() && hasDrums)
    {
        const int bars = juce::roundToInt (drumsClip.lengthBeats / MidiClipIO::kBeatsPerBar);
        lengthBars.setValue (juce::jlimit (1, 64, bars), juce::dontSendNotification);
    }
    regenerate();
}

void MainComponent::regenerate()
{
    if (! hasDrums)
    {
        haveDesign = false;
        saveBtn.setEnabled (false);
        dragOut.repaint();
        return;
    }
    const auto colors = swatches.selectedPitches();
    if (colors.empty())
    {
        haveDesign = false;
        saveBtn.setEnabled (false);
        dragOut.repaint();
        return;
    }

    DesignParams p;
    p.colorPitches = colors;
    p.dynamics   = juce::roundToInt (dynamics.getValue());
    p.brightness = juce::roundToInt (brightness.getValue());
    p.seed = static_cast<std::uint64_t> (juce::jmax ((juce::int64) 1,
                                                     seedEditor.getText().getLargeIntValue()));
    p.lengthBeats = autoLength.getToggleState()
                       ? 0.0
                       : lengthBars.getValue() * MidiClipIO::kBeatsPerBar;

    designedClip = design (drumsClip,
                           hasBass   ? bassClip   : Clip{},
                           hasSynths ? synthsClip : Clip{},
                           p);
    haveDesign = true;
    saveBtn.setEnabled (true);
    dragOut.repaint();
    playback.setClip (designedClip);
}

void MainComponent::doSave()
{
    if (! haveDesign) return;
    chooser = std::make_unique<juce::FileChooser> ("Save designed clip",
                                                   juce::File::getSpecialLocation (juce::File::userMusicDirectory)
                                                       .getChildFile ("HitDesign clip.mid"),
                                                   "*.mid");
    chooser->launchAsync (juce::FileBrowserComponent::saveMode
                          | juce::FileBrowserComponent::canSelectFiles
                          | juce::FileBrowserComponent::warnAboutOverwriting,
                          [this] (const juce::FileChooser& fc)
                          {
                              const auto f = fc.getResult();
                              if (f == juce::File()) return;
                              juce::String err;
                              MidiClipIO::write (designedClip,
                                                 f.hasFileExtension ("mid") ? f : f.withFileExtension ("mid"),
                                                 err);
                          });
}

void MainComponent::refreshTransportLabel()
{
    const double bars = playback.positionBeats() / MidiClipIO::kBeatsPerBar;
    const double total = playback.clipLengthBeats() / MidiClipIO::kBeatsPerBar;
    transportLabel.setText (juce::String (bars + 1.0, 2) + " / " + juce::String (total, 0) + " bars",
                            juce::dontSendNotification);
}

void MainComponent::paint (juce::Graphics& g) { g.fillAll (juce::Colour (0xff1e1e1e)); }

void MainComponent::resized()
{
    auto r = getLocalBounds().reduced (12);
    auto left = r.removeFromLeft (440);
    r.removeFromLeft (12);
    auto right = r;

    // Left column: inputs + controls.
    const int zoneH = 74;
    drumsZone.setBounds  (left.removeFromTop (zoneH)); left.removeFromTop (6);
    bassZone.setBounds   (left.removeFromTop (zoneH)); left.removeFromTop (6);
    synthsZone.setBounds (left.removeFromTop (zoneH)); left.removeFromTop (10);

    swatchLabel.setBounds (left.removeFromTop (18));
    swatches.setBounds    (left.removeFromTop (90)); left.removeFromTop (8);

    auto row = [&left] (int h) { auto x = left.removeFromTop (h); left.removeFromTop (6); return x; };
    auto labelled = [] (juce::Rectangle<int> area, juce::Label& l, juce::Component& c)
    {
        l.setBounds (area.removeFromLeft (90));
        c.setBounds (area);
    };
    labelled (row (22), dynamicsLabel, dynamics);
    labelled (row (22), brightnessLabel, brightness);
    {
        auto lr = row (22);
        lengthLabel.setBounds (lr.removeFromLeft (90));
        autoLength.setBounds (lr.removeFromRight (120));
        lengthBars.setBounds (lr);
    }
    {
        auto sr = row (24);
        seedLabel.setBounds (sr.removeFromLeft (90));
        rerollBtn.setBounds (sr.removeFromRight (80));
        seedEditor.setBounds (sr.removeFromLeft (100));
    }
    left.removeFromTop (6);
    {
        auto br = row (30);
        generateBtn.setBounds (br.removeFromLeft (110));
        br.removeFromLeft (8);
        saveBtn.setBounds (br.removeFromLeft (110));
        br.removeFromLeft (8);
        dragOut.setBounds (br);
    }

    // Right column: preview + transport.
    auto transport = right.removeFromBottom (30);
    auto controls  = right.removeFromBottom (34);
    right.removeFromBottom (8);
    visualizer.setBounds (right);

    {
        auto c = controls;
        playBtn.setBounds (c.removeFromLeft (70)); c.removeFromLeft (8);
        loopToggle.setBounds (c.removeFromLeft (64)); c.removeFromLeft (8);
        bpmLabel.setBounds (c.removeFromLeft (34));
        bpm.setBounds (c.removeFromLeft (150)); c.removeFromLeft (12);
        transportLabel.setBounds (c);
    }
    {
        auto c = transport;
        connectBtn.setBounds (c.removeFromLeft (110)); c.removeFromLeft (10);
        statusLabel.setBounds (c);
    }
}

}  // namespace hitdesign

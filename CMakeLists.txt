cmake_minimum_required(VERSION 3.22)

project(HitDesign VERSION 0.1.0 LANGUAGES C CXX)

# HitDesign is the clip designer for the hitdmx family: feed it drums / bass /
# synths MIDI clips, pick colours + dynamics + brightness, and it designs a MIDI
# clip that triggers HitNoteDmx. It reuses HitNoteDmx's own note vocabulary,
# palette, composition path and rig visualiser (fetched below) so the notes it
# emits can never drift from the plugin's live mapping, and the preview plays
# through the REAL computeDmx.
#
# Ships primarily for macOS (the ENTTEC driver uses IOKit + POSIX serial); on
# non-Apple platforms the driver compiles to a no-op stub, so the GUI / engine
# build and run everywhere (DMX output disabled there).
if(NOT APPLE)
    message(STATUS "HitDesign: non-Apple build - ENTTEC DMX output is a no-op stub.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)

# ---- JUCE -------------------------------------------------------------------
FetchContent_Declare(
    JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG        8.0.4
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(JUCE)

# ---- HitNoteDmx (the backbone) ----------------------------------------------
# We depend on HitNoteDmx for its shared plugin sources — the SINGLE source of
# truth for the note vocabulary (TriggerVocabulary), palette, rig, recipe engine,
# compositor (computeDmx) and rig visualiser + ENTTEC driver. We fetch the repo
# for its Source/ tree and compile only the files we need into our own targets;
# we deliberately do NOT add_subdirectory it (no plugin build here). Pinned to a
# commit so the vocabulary version is reproducible — bump it to adopt a newer
# mapping (and re-verify design-selftest).
FetchContent_Declare(
    hitnotedmx
    GIT_REPOSITORY https://github.com/joris-klingen/hitnotedmx.git
    GIT_TAG        51f9be3369e07b39f47fe918a7a316da07aa0922
)
FetchContent_GetProperties(hitnotedmx)
if(NOT hitnotedmx_POPULATED)
    FetchContent_Populate(hitnotedmx)
endif()
set(HND_SRC "${hitnotedmx_SOURCE_DIR}/Source")

# ---- hitdesign (CLI) --------------------------------------------------------
# The design engine + its console front-end. GUI-free (the engine is the shared
# core behind the CLI, the GUI app and the tests). Links only TriggerVocabulary
# from HitNoteDmx.
juce_add_console_app(hitdesign PRODUCT_NAME "hitdesign")
target_sources(hitdesign PRIVATE
    tools/HitDesignCli.cpp
    design/MidiClipIO.cpp
    design/ClipAnalysis.cpp
    design/DesignEngine.cpp
    "${HND_SRC}/TriggerVocabulary.cpp"
)
target_include_directories(hitdesign PRIVATE "${HND_SRC}" design)
target_compile_definitions(hitdesign PRIVATE JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_link_libraries(hitdesign PRIVATE
    juce::juce_audio_basics
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags
)

# ---- HitDesign (GUI app) ----------------------------------------------------
# The drag-and-drop design app: three clip drop zones, a palette swatch picker,
# dynamics/brightness sliders, an adjustable length, and a live rig preview that
# plays the designed clip through the REAL computeDmx into HitNoteDmx's shared
# DmxVisualizer (optional ENTTEC out).
juce_add_gui_app(HitDesign
    PRODUCT_NAME "HitDesign"
    COMPANY_NAME "HitDmx"
    BUNDLE_ID    "com.hitdmx.HitDesign"
)
target_sources(HitDesign PRIVATE
    design/app/HitDesignApp.cpp
    design/app/MainComponent.cpp
    design/app/DropZone.cpp
    design/app/SwatchGrid.cpp
    design/app/PlaybackEngine.cpp
    design/MidiClipIO.cpp
    design/ClipAnalysis.cpp
    design/DesignEngine.cpp
    "${HND_SRC}/Composition.cpp"
    "${HND_SRC}/Recipes.cpp"
    "${HND_SRC}/MidiState.cpp"
    "${HND_SRC}/DmxVisualizer.cpp"
    "${HND_SRC}/EnttecProDmx.cpp"
    "${HND_SRC}/TriggerVocabulary.cpp"
)
target_include_directories(HitDesign PRIVATE "${HND_SRC}" design)
target_compile_definitions(HitDesign PRIVATE
    JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0)
target_link_libraries(HitDesign PRIVATE
    juce::juce_audio_utils
    juce::juce_audio_basics
    juce::juce_gui_basics
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags
)
if(APPLE)
    target_link_libraries(HitDesign PRIVATE "-framework IOKit" "-framework CoreFoundation")
endif()

# ---- tests ------------------------------------------------------------------
# Guard the design engine + its note vocabulary: every note the engine can emit
# must resolve to a live HitNoteDmx chain name (never drift off the mapping), and
# the engine's output must stay on-grid / balanced / deterministic across a
# params sweep of the built-in fixtures (see tools/HitDesignCli.cpp `selftest`).
enable_testing()
add_test(NAME design-selftest COMMAND hitdesign selftest)

"""Source-decoder registry.

A source turns some native ``.als`` format into the neutral IR. Add a new one
(e.g. an older hitnotedmx note mapping) by writing a module with ``decode`` /
``detect`` and registering it here — the CLI/GUI pick it up automatically.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from . import legacy_macro

# name → module. Order matters for auto-detect (first match wins).
SOURCES = {
    "legacy": legacy_macro,
}


def get(name: str):
    if name not in SOURCES:
        raise RuntimeError(f"unknown source {name!r}; known: {sorted(SOURCES)}")
    return SOURCES[name]


def autodetect(root: ET.Element) -> str:
    for name, mod in SOURCES.items():
        if mod.detect(root):
            return name
    raise RuntimeError("could not auto-detect the source format; pass --source")

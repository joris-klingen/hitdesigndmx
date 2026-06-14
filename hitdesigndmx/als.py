"""Read and write Ableton Live ``.als`` files (gzipped XML).

Scope here is deliberately generic — load the document, find tracks/clips,
and *write MIDI notes* into a freshly added track. The format-specific reading
(legacy rack macros, future note mappings) lives in the source decoders; this
module only knows about the container.

The output strategy mirrors the proven "sidecar" trick: deep-copy the source
track, re-allocate its element Ids from ``NextPointeeId`` to avoid collisions,
strip its instrument devices (so it's a plain MIDI track you route to the
hitnotedmx plugin), and replace each clip's automation envelopes with note
data. ClipSlot Ids are kept as-is because Live aligns them with Scene Ids and
shares those Ids across tracks by design.
"""

from __future__ import annotations

import copy
import gzip
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from .vocab.hitnote_v1 import Note


def read_als(path: str | Path) -> ET.Element:
    with gzip.open(Path(path), "rb") as f:
        return ET.fromstring(f.read())


def write_als(root: ET.Element, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = ET.tostring(
        root, encoding="utf-8", xml_declaration=True, short_empty_elements=True
    )
    with gzip.open(out, "wb") as f:
        f.write(xml_bytes)


def track_name(track: ET.Element) -> str | None:
    el = track.find("Name/EffectiveName")
    return el.get("Value") if el is not None else None


def tracks(root: ET.Element) -> list[ET.Element]:
    return list(root.find("LiveSet/Tracks"))


def find_track(
    root: ET.Element, *, name: str | None = None, index: int | None = None
) -> ET.Element:
    ts = tracks(root)
    if index is not None:
        return ts[index]
    if name is not None:
        for t in ts:
            if (track_name(t) or "").strip() == name:
                return t
        raise RuntimeError(f"no track named {name!r}")
    raise RuntimeError("find_track needs a name or index")


def find_legacy_track(root: ET.Element) -> ET.Element:
    """First MidiTrack carrying an Instrument Rack — the legacy macro track."""
    for t in tracks(root):
        if t.tag == "MidiTrack" and t.find(".//InstrumentGroupDevice") is not None:
            return t
    raise RuntimeError("no MidiTrack with an InstrumentGroupDevice (legacy rack) found")


def scene_names(root: ET.Element) -> list[str]:
    """Scene names in document order. Live aligns scene *i* with clip-slot *i*
    across every track, so this is the song/section structure for a slot index
    (empty string where a scene is unnamed). Stripped of surrounding whitespace
    so ``'thema '`` and ``'thema'`` read as the same section."""
    scenes = root.find("LiveSet/Scenes")
    if scenes is None:
        return []
    out: list[str] = []
    for sc in scenes.findall("Scene"):
        n = sc.find("Name")
        out.append(((n.get("Value") if n is not None else "") or "").strip())
    return out


def clip_slots(track: ET.Element) -> list[ET.Element]:
    return track.findall(".//ClipSlotList/ClipSlot")


def slot_clip(slot: ET.Element) -> ET.Element | None:
    return slot.find("ClipSlot/Value/MidiClip")


def _id_allocator(root: ET.Element) -> tuple[Callable[[], int], Callable[[], None]]:
    el = root.find("LiveSet/NextPointeeId")
    nxt = int(el.get("Value"))

    def alloc() -> int:
        nonlocal nxt
        v = nxt
        nxt += 1
        return v

    def commit() -> None:
        el.set("Value", str(nxt))

    return alloc, commit


def _build_keytracks(
    parent: ET.Element, notes: list[Note], alloc: Callable[[], int]
) -> int:
    """Replace ``parent``'s children with one KeyTrack per pitch. Returns the
    next free NoteId (one past the highest used), for the NoteIdGenerator."""
    for child in list(parent):
        parent.remove(child)

    by_pitch: dict[int, list[Note]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)

    note_id = 0
    for pitch in sorted(by_pitch):
        kt = ET.SubElement(parent, "KeyTrack", {"Id": str(alloc())})
        notes_el = ET.SubElement(kt, "Notes")
        for n in sorted(by_pitch[pitch], key=lambda x: x.start):
            ET.SubElement(
                notes_el,
                "MidiNoteEvent",
                {
                    "Time": _num(n.start),
                    "Duration": _num(n.dur),
                    "Velocity": _num(n.velocity),
                    "OffVelocity": "64",
                    "NoteId": str(note_id),
                },
            )
            note_id += 1
        ET.SubElement(kt, "MidiKey", {"Value": str(pitch)})
    return note_id


def _num(x: float) -> str:
    """Compact numeric string — integers without a trailing ``.0``."""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return repr(round(float(x), 6))


def _clear_envelopes(clip: ET.Element) -> None:
    """Drop the macro-automation envelopes carried over from the source clip."""
    inner = clip.find("Envelopes/Envelopes")
    if inner is not None:
        for ce in list(inner):
            inner.remove(ce)


def _strip_devices(track: ET.Element) -> None:
    """Empty the track's device chain so it's a plain MIDI track (the user
    routes its MIDI output to the hitnotedmx plugin track)."""
    for devices in track.findall(".//DeviceChain/DeviceChain/Devices"):
        for d in list(devices):
            devices.remove(d)


def _reassign_ids(track: ET.Element, alloc: Callable[[], int]) -> None:
    """Fresh Ids for every Id-bearing element EXCEPT the scene-aligned outer
    ClipSlots (Live shares those Ids with Scenes / across tracks)."""
    keep = {id(s) for s in track.findall(".//ClipSlotList/ClipSlot")}
    for el in track.iter():
        if el.get("Id") is not None and id(el) not in keep:
            el.set("Id", str(alloc()))


def add_note_track(
    root: ET.Element,
    source_track: ET.Element,
    target_name: str,
    notes_by_slot: dict[int, list[Note]],
) -> int:
    """Append a new MIDI track (cloned from ``source_track``) named
    ``target_name`` whose clips carry the given notes. Returns clips written.

    The clone keeps clip names/timing/loop/time-signature; we only swap each
    populated clip's envelopes for notes and strip the instrument devices.

    Any existing MidiTrack already named ``target_name`` is replaced, so
    re-running the converter on a set is idempotent instead of accumulating
    output tracks.
    """
    alloc, commit = _id_allocator(root)

    new_track = copy.deepcopy(source_track)
    _strip_devices(new_track)

    # Rename (user-facing + effective + memorised first-clip name).
    name_el = new_track.find("Name")
    if name_el is not None:
        for tag in ("UserName", "EffectiveName", "MemorizedFirstClipName"):
            child = name_el.find(tag)
            if child is not None:
                child.set("Value", target_name)

    written = 0
    for slot_idx, slot in enumerate(clip_slots(new_track)):
        clip = slot_clip(slot)
        if clip is None:
            continue
        _clear_envelopes(clip)
        notes = notes_by_slot.get(slot_idx, [])
        kt_parent = clip.find("Notes/KeyTracks")
        if kt_parent is None:
            continue
        next_note_id = _build_keytracks(kt_parent, notes, alloc)
        gen = clip.find("Notes/NoteIdGenerator/NextId")
        if gen is not None:
            gen.set("Value", str(max(next_note_id, 1)))
        if notes:
            written += 1

    _reassign_ids(new_track, alloc)

    tracks_el = root.find("LiveSet/Tracks")
    for t in list(tracks_el):
        if t.tag == "MidiTrack" and (track_name(t) or "").strip() == target_name:
            tracks_el.remove(t)
    # Live requires regular tracks to precede the ReturnTracks; a track
    # appended after them fails to load ("more send knobs than returns").
    children = list(tracks_el)
    first_return = next(
        (i for i, t in enumerate(children) if t.tag == "ReturnTrack"), len(children)
    )
    tracks_el.insert(first_return, new_track)
    commit()
    return written

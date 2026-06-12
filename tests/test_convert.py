"""End-to-end conversion tests against the checked-in fixture set."""

from pathlib import Path

import pytest

from hitdesigndmx import als
from hitdesigndmx.convert import convert

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "hitmix_set_dmx_input Project"
    / "hitmix_set_dmx_input.als"
)


@pytest.fixture(scope="module")
def converted(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("out") / "converted.als"
    res = convert(FIXTURE, out)
    assert res.out_path == out
    return out


def test_golden_counts(converted):
    """The fixture set is frozen — conversion totals must stay stable."""
    res = convert(FIXTURE, converted)
    assert res.source == "legacy"
    assert res.target == "hitnote_v1"
    assert res.clips_in == 519
    assert res.clips_written == 519
    assert res.notes_written == 8521


def test_track_inserted_before_returns(converted):
    """Regression: a track appended after the ReturnTracks corrupts the set
    in Live ("track has more send knobs than there are return tracks")."""
    root = als.read_als(converted)
    tags = [t.tag for t in als.tracks(root)]
    first_return = tags.index("ReturnTrack")
    target = als.find_track(root, name="dmx_note")
    assert als.tracks(root).index(target) < first_return


def test_sends_match_returns(converted):
    root = als.read_als(converted)
    returns = sum(1 for t in als.tracks(root) if t.tag == "ReturnTrack")
    target = als.find_track(root, name="dmx_note")
    assert len(target.findall(".//Sends/TrackSendHolder")) == returns


def test_rerun_replaces_existing_target(converted, tmp_path):
    """Converting a set that already carries a dmx_note track must replace
    it, not accumulate a second one."""
    out2 = tmp_path / "converted_twice.als"
    convert(converted, out2)
    root = als.read_als(out2)
    named = [t for t in als.tracks(root) if (als.track_name(t) or "") == "dmx_note"]
    assert len(named) == 1

"""flp_performance: time markers + playlist-track performance settings in a copy."""
import struct

import pytest

from fl_studio_mcp import flp_performance as perf
from fl_studio_mcp import flp_reader as r


def _text(eid, s):
    raw = s.encode("utf-16-le") + b"\x00\x00"
    return bytes([eid, len(raw)]) + raw


def _flp(events: bytes, ppq=96) -> bytes:
    return (b"FLhd" + struct.pack("<IhHH", 6, 0, 9, ppq)
            + b"FLdt" + struct.pack("<I", len(events)) + events)


def _marker(ticks, name, action=0):
    return (bytes([148]) + struct.pack("<I", ticks | (action << 24)) + bytes([33, 4, 34, 4, 46, 0, 45, 0])
            + bytes([168]) + b"\x00" * 4 + bytes([101]) + b"\x00" * 2 + _text(205, name))


def _track(iid, trigger=0):
    raw = struct.pack("<IiiBfiBIIIIII", iid, 0x485156, 0, 1, 1.0, -16, 0, 0, 0, trigger, 0, 0, 0)
    raw += b"\x00\x00" + b"\xff" * 8 + b"\x01" + b"\x00" * 8
    return bytes([238, len(raw)]) + raw


def _project(tmp_path, markers=b""):
    events = (bytes([199, 12]) + b"26.1.0.5530\x00"
              + bytes([99]) + struct.pack("<H", 0) + _text(241, "Arrangement")
              + bytes([233, 0]) + markers
              + b"".join(_track(t, trigger=5) for t in range(1, 5))
              + bytes([99]) + struct.pack("<H", 1) + _text(241, "Song")
              + bytes([233, 0]) + _marker(0, "Intro") + b"".join(_track(t) for t in range(1, 3)))
    src = tmp_path / "src.flp"
    src.write_bytes(_flp(events))
    return src


def test_read_markers_and_tracks(tmp_path):
    src = _project(tmp_path, _marker(0, "A") + _marker(3072, "B") + _marker(98688, "Start", 5))
    a = perf.read(str(src), 0, 4)["arrangements"][0]
    assert [(m["bar"], m["name"], m["type"]) for m in a["markers"]] == [
        (1.0, "A", "marker"), (9.0, "B", "marker"), (258.0, "Start", "start")]
    assert a["performance_zone_bars"] == 257.0
    assert a["tracks"][0] == {"track": 1, "motion": "stay", "press": "retrigger",
                              "trigger_sync": "four_beats", "position_sync": "off"}


def test_noop_write_is_byte_identical(tmp_path):
    src = _project(tmp_path, _marker(0, "A"))
    out = tmp_path / "same.flp"
    perf.write(str(src), str(out), 0, [], None, {}, clear_markers=False)
    assert out.read_bytes() == src.read_bytes()


def test_write_blocks_start_and_track_settings(tmp_path):
    src = _project(tmp_path, _marker(0, "Old") + _marker(98688, "Start", 5))
    out = tmp_path / "out.flp"
    res = perf.write(str(src), str(out), 0, [(1, "Groove"), (9, "Drop")], 17,
                     {2: {"motion": "march_wrap", "press": "latch", "trigger_sync": "beat"}})
    assert res["markers_removed"] == 2 and res["markers_written"] == 3 and res["tracks_patched"] == 1
    a = perf.read(str(out), 0, 4)["arrangements"][0]
    assert [(m["bar"], m["name"], m["type"]) for m in a["markers"]] == [
        (1.0, "Groove", "marker"), (9.0, "Drop", "marker"), (17.0, "Start", "start")]
    assert a["performance_zone_bars"] == 16.0
    t = {x["track"]: x for x in a["tracks"]}
    assert (t[2]["motion"], t[2]["press"], t[2]["trigger_sync"]) == ("march_wrap", "latch", "beat")
    assert t[1]["trigger_sync"] == "four_beats"                       # untouched track kept
    song = perf.read(str(out), 1)["arrangements"][0]
    assert [m["name"] for m in song["markers"]] == ["Intro"]          # other arrangement untouched
    assert r.parse(str(out))["arrangements"][1]["name"] == "Song"


def test_markers_created_when_arrangement_has_none(tmp_path):
    src = _project(tmp_path)
    out = tmp_path / "out.flp"
    perf.write(str(src), str(out), 0, [(1, "One")], 9, {})
    a = perf.read(str(out), 0)["arrangements"][0]
    assert [(m["bar"], m["type"]) for m in a["markers"]] == [(1.0, "marker"), (9.0, "start")]


def test_validation(tmp_path):
    src = _project(tmp_path)
    with pytest.raises(ValueError):
        perf.write(str(src), str(src), 0, [], None, {})
    with pytest.raises(ValueError):
        perf.write(str(src), str(tmp_path / "x.flp"), 0, [], None, {1: {"press": "smash"}})
    with pytest.raises(ValueError):
        perf.write(str(src), str(tmp_path / "x.flp"), 7, [], None, {})

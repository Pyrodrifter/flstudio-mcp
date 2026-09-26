"""flp_notes / flp_plugins: notes, channel presets and mixer effects in a copy."""
import struct

import pytest

from fl_studio_mcp import flp_notes, flp_plugins, flp_reader as r


def _text(eid, s):
    raw = s.encode("utf-16-le") + b"\x00\x00"
    return bytes([eid, len(raw)]) + raw


def _blob(eid, payload):
    return bytes([eid]) + flp_plugins._varint(len(payload)) + payload


def _file(path, events, ppq=96):
    path.write_bytes(b"FLhd" + struct.pack("<IhHH", 6, 0, 9, ppq) + b"FLdt" + struct.pack("<I", len(events)) + events)
    return path


def _project(tmp_path):
    chan = (bytes([64]) + struct.pack("<H", 0) + bytes([21, 2]) + _text(201, "Harmor")
            + _blob(212, b"\x00" * 52) + _text(203, "Synth") + bytes([155]) + b"\x00" * 4
            + bytes([128]) + b"HQV\x00" + bytes([41, 0]) + _blob(213, b"OLDSTATE"))
    insert = lambda: bytes([236, 12]) + b"\x00" * 12 + b"".join(bytes([98]) + struct.pack("<H", s) for s in range(10))
    events = (_blob(199, b"26.1.0.5530\x00") + bytes([216, 0])
              + bytes([65]) + struct.pack("<H", 1) + _blob(224, flp_notes.pack_notes([{"channel": 0, "position": 0, "key": 60}]))
              + chan + insert() + insert() + insert())
    return _file(tmp_path / "p.flp", events)


def _preset(tmp_path, name, state):
    wrapper = bytearray(52)
    struct.pack_into("<II", wrapper, 0, 8, 1)
    ev = (_blob(199, b"20.8.0\x00") + bytes([28, 3]) + _text(201, name) + _blob(212, bytes(wrapper))
          + bytes([155]) + b"\x00" * 4 + bytes([128]) + b"HQV\x00" + _blob(213, state))
    return str(_file(tmp_path / (name + ".fst"), ev))


def test_notes_replace_and_new_patterns(tmp_path):
    src = _project(tmp_path)
    out = tmp_path / "n.flp"
    res = flp_notes.write_patterns(str(src), str(out), {
        1: [{"channel": 0, "position": 96, "length": 48, "key": 57, "velocity": 110}],
        7: [{"channel": 0, "position": 0, "key": 60}, {"channel": 0, "position": 24, "key": 62, "length": 24}]})
    assert res["patterns_total"] == 2
    pats = r.parse(str(out))["patterns"]
    assert [(n["position"], n["key"], n["length"], n["velocity"]) for n in pats[1]["notes"]] == [(96, 57, 48, 110)]
    assert len(pats[7]["notes"]) == 2
    assert r.parse(str(out))["channels"][0]["plugin"] == "Harmor"          # rest of the file intact


def test_notes_append(tmp_path):
    src = _project(tmp_path)
    out = tmp_path / "n.flp"
    flp_notes.write_patterns(str(src), str(out), {1: [{"channel": 0, "position": 48, "key": 64}]}, replace=False)
    assert len(r.parse(str(out))["patterns"][1]["notes"]) == 2


def test_channel_preset_and_mixer_fx(tmp_path):
    src = _project(tmp_path)
    syn = _preset(tmp_path, "Harmor", b"NEWSTATE")
    fx = _preset(tmp_path, "Fruity Delay 3", b"DELAYSTATE")
    out = tmp_path / "fx.flp"
    res = flp_plugins.apply(str(src), str(out), {0: syn}, [(2, 3, fx)])
    assert res == {"file": str(out), "channel_presets": 1, "mixer_fx": 1}
    _b, _d, data, spans = flp_plugins._load(str(out))
    states = [data[p0:p1] for e, _s, p0, p1 in spans if e == 213]
    assert states == [b"NEWSTATE", b"DELAYSTATE"]
    k = next(i for i, s in enumerate(spans) if s[0] == 213 and data[s[2]:s[3]] == b"DELAYSTATE")
    assert struct.unpack("<H", data[spans[k + 1][2]:spans[k + 1][3]])[0] == 3        # right before slot 3's 98
    w = next(data[s[2]:s[3]] for s in spans[k - 6:k] if s[0] == 212)
    assert struct.unpack_from("<II", w) == (2, 3)                                      # wrapper = insert, slot
    with pytest.raises(ValueError):
        flp_plugins.apply(str(out), str(tmp_path / "x.flp"), {}, [(2, 3, fx)])        # slot now taken


def test_old_preset_rejected(tmp_path):
    ev = _blob(199, b"9.0.3\x00") + _text(201, "Harmless") + _blob(212, b"\x00" * 52) + _blob(213, b"x")
    old = _file(tmp_path / "old.fst", ev)
    with pytest.raises(ValueError):
        flp_plugins.read_preset(str(old))

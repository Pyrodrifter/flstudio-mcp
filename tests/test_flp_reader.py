"""flp_reader against synthetic FL 26-style event streams."""
import struct

from fl_studio_mcp import flp_reader as r


def _text(eid, s):
    raw = s.encode("utf-16-le") + b"\x00\x00"
    assert len(raw) < 128
    return bytes([eid, len(raw)]) + raw


def _flp(events: bytes, ppq=96) -> bytes:
    return (b"FLhd" + struct.pack("<IhHH", 6, 0, 9, ppq)
            + b"FLdt" + struct.pack("<I", len(events)) + events)


def _note(channel, key, pos, length, vel=100):
    return struct.pack("<IHHIHHBBBBBBBB", pos, 0, channel, length, key, 0,
                       120, 0, 64, 0, 64, vel, 128, 128)


def _clip(pattern, pos, length, track):
    item = struct.pack("<IHHIHH", pos, 20480, 20480 + pattern, length, 500 - track, 0)
    return item + b"\x00" * (88 - len(item))


def test_fl26_odd_sized_dword_events_do_not_desync(tmp_path):
    notes = _note(5, 81, 0, 72) + _note(5, 79, 72, 72)
    events = (
        bytes([199, 12]) + b"26.1.0.5530\x00"
        + bytes([172]) + b"\x01\x01\x00"                 # 3-byte payload (FL 26)
        + _text(192, "FL Studio 26.1.0.5530")
        + bytes([156]) + struct.pack("<I", 130000)       # tempo
        + bytes([172]) + b"\x00\x01\x00\x00\x00"         # 5-byte payload (FL 26)
        + _text(231, "Unsorted")
        + bytes([65]) + struct.pack("<H", 1)
        + bytes([224, len(notes)]) + notes
        + bytes([64]) + struct.pack("<H", 5) + _text(203, "Keybit")
    )
    f = tmp_path / "t.flp"
    f.write_bytes(_flp(events))
    p = r.parse(str(f))
    assert p["tempo"] == 130.0
    assert p["channels"][5]["name"] == "Keybit"
    view = r.notes_view(p, 1)
    assert [(n["note"], n["time_bars"], n["length_bars"]) for n in view["notes"]] == [
        ("A6", 0.0, 0.1875), ("G6", 0.1875, 0.1875)]


def test_playlist_items_are_88_bytes_in_fl26(tmp_path):
    items = _clip(5, 0, 3072, 4) + _clip(6, 3072, 768, 5) + _clip(2, 3072, 3072, 1)
    events = bytes([199, 12]) + b"26.1.0.5530\x00" + bytes([233]) + _varint(len(items)) + items
    f = tmp_path / "t.flp"
    f.write_bytes(_flp(events))
    clips = r.summarize(r.parse(str(f)))["arrangements"][0]["clips"]
    assert clips == [
        {"track": 4, "bar": 1.0, "length_bars": 8.0, "pattern": 5},
        {"track": 5, "bar": 9.0, "length_bars": 2.0, "pattern": 6},
        {"track": 1, "bar": 9.0, "length_bars": 8.0, "pattern": 2},
    ]


def test_find_latest_skips_overwritten_backups(tmp_path):
    (tmp_path / "Mau5.flp").write_bytes(b"x")
    backup = tmp_path / "Backup"
    backup.mkdir()
    newer = backup / "Mau5 (overwritten on 9-25-2026 at 23h44).flp"
    newer.write_bytes(b"x")
    assert r.find_latest(dirs=[str(tmp_path)]).endswith("Mau5.flp")


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

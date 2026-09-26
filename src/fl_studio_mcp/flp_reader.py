"""Minimal, dependency-free reader for FL Studio .flp project files.

FL's scripting API cannot read Piano-roll notes, sample paths or the playlist,
but the saved project (or FL's own autosave backup) contains all of it. The
format is a flat stream of events; we decode only what we need:

  header  b"FLhd" <u32 len=6> <i16 format> <u16 n_channels> <u16 ppq>
  data    b"FLdt" <u32 len>   events...
  event   <u8 id> then: id<64 -> 1 byte, <128 -> 2 bytes, <192 -> 4 bytes,
          else a varint length + that many bytes.

PyFLP does this too but is unmaintained and fails to import on Python 3.14.
"""
from __future__ import annotations

import glob
import os
import struct
import time
from typing import Dict, Iterator, List, Optional, Tuple

# Event ids (names follow FL's SDK / PyFLP).
EV_CHAN_TYPE = 21
EV_CHAN_NEW = 64
EV_PAT_NEW = 65
EV_ARRANGEMENT_NEW = 99
EV_FINE_TEMPO = 156
EV_PAT_NAME = 193
EV_SAMPLE_PATH = 196
EV_VERSION = 199
EV_DEF_PLUGIN_NAME = 201
EV_PLUGIN_NAME = 203
EV_PAT_NOTES = 224
EV_PLAYLIST_ITEMS = 233
EV_ARRANGEMENT_NAME = 241

_NOTE = struct.Struct("<IHHIHHBBBBBBBB")          # 24 bytes per note
_PL_BASE = struct.Struct("<IHHIHH")              # first 16 bytes of a playlist item
_PATTERN_BASE = 20480                             # item_index above this = pattern clip

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

DEFAULT_PROJECT_DIRS = [
    os.path.join(os.path.expanduser("~"), "Documents", "Image-Line", "FL Studio", "Projects"),
]


def note_name(key: int) -> str:
    """MIDI key -> name in FL's octave convention (60 = C5)."""
    return "%s%d" % (NOTE_NAMES[key % 12], key // 12)


def _events(data: bytes) -> Iterator[Tuple[int, bytes]]:
    i, n = 0, len(data)
    while i < n:
        eid = data[i]
        i += 1
        if eid < 64:
            size = 1
        elif eid < 128:
            size = 2
        elif eid < 192:
            size = 4
        else:
            size, shift = 0, 0
            while True:
                b = data[i]
                i += 1
                size |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        yield eid, data[i:i + size]
        i += size


def _text(raw: bytes, utf16: bool) -> str:
    if utf16:
        return raw.decode("utf-16-le", "replace").rstrip("\x00")
    return raw.decode("latin-1", "replace").rstrip("\x00")


def _playlist_items(raw: bytes) -> List[dict]:
    # Item size grew over versions (32 -> 60 bytes); pick the one that divides.
    size = next((s for s in (60, 32) if raw and len(raw) % s == 0), None)
    if size is None:
        return []
    out = []
    for off in range(0, len(raw), size):
        pos, _base, idx, length, track_rv, _group = _PL_BASE.unpack_from(raw, off)
        item = {"position": pos, "length": length, "track": 500 - track_rv}
        if idx > _PATTERN_BASE:
            item["pattern"] = idx - _PATTERN_BASE
        else:
            item["channel"] = idx
        out.append(item)
    return out


def parse(path: str) -> dict:
    """Parse an .flp into plain dicts: version, ppq, tempo, channels,
    patterns (with notes), arrangements (with playlist items)."""
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:4] != b"FLhd":
        raise ValueError("not an FL Studio project: %s" % path)
    hlen = struct.unpack_from("<I", blob, 4)[0]
    _fmt, _nch, ppq = struct.unpack_from("<hHH", blob, 8)
    d = 8 + hlen
    if blob[d:d + 4] != b"FLdt":
        raise ValueError("missing FLdt chunk")
    dlen = struct.unpack_from("<I", blob, d + 4)[0]
    data = blob[d + 8:d + 8 + dlen]

    proj = {"path": path, "ppq": ppq, "version": None, "tempo": None,
            "channels": {}, "patterns": {}, "arrangements": []}
    utf16 = True
    chan: Optional[dict] = None
    pat: Optional[dict] = None
    arr: Optional[dict] = None
    for eid, raw in _events(data):
        if eid == EV_VERSION:
            proj["version"] = raw.decode("ascii", "replace").rstrip("\x00")
            try:
                utf16 = tuple(int(x) for x in proj["version"].split(".")[:2]) >= (11, 5)
            except ValueError:
                utf16 = True
        elif eid == EV_FINE_TEMPO:
            proj["tempo"] = struct.unpack("<I", raw)[0] / 1000.0
        elif eid == EV_CHAN_NEW:
            iid = struct.unpack("<H", raw)[0]
            chan = proj["channels"].setdefault(iid, {"iid": iid, "name": None,
                                                     "plugin": None, "sample": None})
        elif eid == EV_PLUGIN_NAME and chan is not None and chan["name"] is None:
            chan["name"] = _text(raw, utf16)
        elif eid == EV_DEF_PLUGIN_NAME and chan is not None and chan["plugin"] is None:
            chan["plugin"] = _text(raw, utf16)
        elif eid == EV_SAMPLE_PATH and chan is not None:
            chan["sample"] = _text(raw, utf16)
        elif eid == EV_PAT_NEW:
            iid = struct.unpack("<H", raw)[0]
            pat = proj["patterns"].setdefault(iid, {"iid": iid, "name": None, "notes": []})
        elif eid == EV_PAT_NAME and pat is not None:
            pat["name"] = _text(raw, utf16)
        elif eid == EV_PAT_NOTES and pat is not None:
            for off in range(0, len(raw) - len(raw) % _NOTE.size, _NOTE.size):
                (pos, _flags, rack, length, key, _grp, fine, _u1, rel, _mch,
                 pan, vel, _mx, _my) = _NOTE.unpack_from(raw, off)
                pat["notes"].append({"channel": rack, "key": key, "position": pos,
                                     "length": length, "velocity": vel, "pan": pan,
                                     "release": rel, "fine_pitch": fine})
        elif eid == EV_ARRANGEMENT_NEW:
            arr = {"iid": struct.unpack("<H", raw)[0], "name": None, "items": []}
            proj["arrangements"].append(arr)
        elif eid == EV_ARRANGEMENT_NAME and arr is not None:
            arr["name"] = _text(raw, utf16)
        elif eid == EV_PLAYLIST_ITEMS:
            if arr is None:
                arr = {"iid": 0, "name": None, "items": []}
                proj["arrangements"].append(arr)
            arr["items"].extend(_playlist_items(raw))
    return proj


def project_dirs() -> List[str]:
    """FL's Projects folder plus any dirs in FLSTUDIO_MCP_PROJECT_DIRS (os.pathsep-separated)."""
    extra = [d for d in os.environ.get("FLSTUDIO_MCP_PROJECT_DIRS", "").split(os.pathsep) if d]
    return DEFAULT_PROJECT_DIRS + extra


def find_latest(title: Optional[str] = None, dirs: Optional[List[str]] = None) -> Optional[str]:
    """Newest .flp under the project dirs (includes FL's Backup autosaves).
    With the FL window ``title``, prefer the newest file whose name appears in it."""
    files = []
    for d in dirs or project_dirs():
        files += glob.glob(os.path.join(d, "**", "*.flp"), recursive=True)
    files.sort(key=os.path.getmtime, reverse=True)
    if title and "untitled" not in title.lower():
        for f in files:
            if os.path.splitext(os.path.basename(f))[0] in title:
                return f
    return files[0] if files else None


def file_age_seconds(path: str) -> float:
    return time.time() - os.path.getmtime(path)


# -- Views in the same units the write tools use (bars, velocity 0..1) --------

def _bars(ticks: int, ppq: int) -> float:
    return round(ticks / (ppq * 4.0), 4)


def summarize(proj: dict) -> dict:
    """Compact overview: channels, patterns with per-channel note counts and
    length, playlist clips. Channel ids are channel-rack indices."""
    ppq = proj["ppq"]
    chans = [{"channel": c["iid"], "name": c["name"], "plugin": c["plugin"] or None,
              "sample": os.path.basename(c["sample"]) if c["sample"] else None}
             for c in sorted(proj["channels"].values(), key=lambda c: c["iid"])
             if c["name"] or c["plugin"] or c["sample"]]
    names = {c["channel"]: c["name"] for c in chans}
    pats = []
    for p in sorted(proj["patterns"].values(), key=lambda p: p["iid"]):
        counts: Dict[int, int] = {}
        end = 0
        for n in p["notes"]:
            counts[n["channel"]] = counts.get(n["channel"], 0) + 1
            end = max(end, n["position"] + n["length"])
        pats.append({"pattern": p["iid"], "name": p["name"],
                     "length_bars": _bars(end, ppq),
                     "notes": [{"channel": ch, "name": names.get(ch), "count": k}
                               for ch, k in sorted(counts.items())]})
    arrs = [{"arrangement": a["iid"], "name": a["name"],
             "clips": [{"track": it["track"], "start_bar": _bars(it["position"], ppq),
                        "length_bars": _bars(it["length"], ppq),
                        **({"pattern": it["pattern"]} if "pattern" in it else
                           {"channel": it["channel"]})} for it in a["items"]]}
            for a in proj["arrangements"]]
    return {"file": proj["path"], "fl_version": proj["version"], "ppq": ppq,
            "channels": chans, "patterns": pats, "arrangements": arrs}


def notes_view(proj: dict, pattern: int, channel: Optional[int] = None) -> dict:
    """Notes of one pattern (optionally one channel), sorted by time."""
    ppq = proj["ppq"]
    pat = proj["patterns"].get(pattern)
    if pat is None:
        return {"pattern": pattern, "found": False, "notes": [],
                "patterns_with_notes": sorted(proj["patterns"])}
    rows = [n for n in pat["notes"] if channel is None or n["channel"] == channel]
    rows.sort(key=lambda n: (n["position"], n["channel"], n["key"]))
    return {"pattern": pattern, "name": pat["name"], "found": True, "count": len(rows),
            "notes": [{"channel": n["channel"], "pitch": n["key"], "note": note_name(n["key"]),
                       "time_bars": _bars(n["position"], ppq),
                       "length_bars": _bars(n["length"], ppq),
                       "velocity": round(n["velocity"] / 128.0, 3)} for n in rows]}

"""Performance Mode setup in a COPY of an FL Studio project.

FL's scripting API can't create time markers of a given type (the Start marker
that ends the performance zone) or change a playlist track's performance
settings, but both live in the project file. Like flp_writer, this rewrites
only the events involved and copies every other byte unchanged.

Formats (verified against FL 26.1 projects; track layout matches PyFLP):

Time marker -- a group of events inside its arrangement, in this order:
    148  u32  position ticks | (action << 24)   action 0 = marker, 5 = Start
     33  u8   time-signature numerator
     34  u8   time-signature denominator
     46  u8,  45 u8,  168 u32,  101 u16          (copied from an existing marker)
    205  text name (UTF-16LE + NUL)
The performance zone is everything before the Start marker; the markers inside
it split it into the blocks that Performance Mode launches.

Playlist track -- event 238, one per track (500 per arrangement):
     0 u32 iid (1-based track)   4 u32 colour   ...   22 u32 motion
    26 u32 press   30 u32 trigger sync   34 u32 queued   38 u32 tolerant
    42 u32 position sync
"""
from __future__ import annotations

import os
import struct
from typing import Dict, List, Optional, Tuple

from . import flp_reader

EV_MARKER_POS = 148
EV_MARKER_NUM = 33
EV_MARKER_DEN = 34
EV_MARKER_NAME = 205
EV_TRACK_DATA = 238

ACTION_MARKER = 0
ACTION_START = 5
_ACTION_NAMES = {ACTION_MARKER: "marker", ACTION_START: "start"}

MOTION = {"stay": 0, "one_shot": 1, "march_wrap": 2, "march_stay": 3, "march_stop": 4,
          "random": 5, "exclusive_random": 6}
PRESS = {"retrigger": 0, "hold_stop": 1, "hold_motion": 2, "latch": 3}
SYNC = {"off": 0, "quarter_beat": 1, "half_beat": 2, "beat": 3, "two_beats": 4, "four_beats": 5, "auto": 6}
TRACK_FIELDS = {"motion": (22, MOTION), "press": (26, PRESS), "trigger_sync": (30, SYNC),
                "position_sync": (42, SYNC)}

# Used when an arrangement has no marker to copy the unknown fields from.
_DEFAULT_MARKER_TAIL = [(EV_MARKER_NUM, b"\x04"), (EV_MARKER_DEN, b"\x04"), (46, b"\x00"),
                        (45, b"\x00"), (168, b"\x00" * 4), (101, b"\x00" * 2)]


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _event(eid: int, payload: bytes) -> bytes:
    if eid >= 192:
        return bytes([eid]) + _varint(len(payload)) + payload
    return bytes([eid]) + payload


def _text(s: str) -> bytes:
    return s.encode("utf-16-le") + b"\x00\x00"


def _split(path: str):
    blob = open(path, "rb").read()
    if blob[:4] != b"FLhd":
        raise ValueError("not an FL Studio project: %s" % path)
    hlen = struct.unpack_from("<I", blob, 4)[0]
    ppq = struct.unpack_from("<hHH", blob, 8)[2]
    d = 8 + hlen
    if blob[d:d + 4] != b"FLdt":
        raise ValueError("missing FLdt chunk")
    data = blob[d + 8:d + 8 + struct.unpack_from("<I", blob, d + 4)[0]]
    return blob, d, data, ppq


def _arrangement_range(spans, data, arrangement: int) -> Tuple[int, int]:
    """Index range [a, b) of the events belonging to arrangement ``arrangement``."""
    starts = [(k, struct.unpack("<H", data[p0:p1])[0]) for k, (eid, _s, p0, p1) in enumerate(spans)
              if eid == flp_reader.EV_ARRANGEMENT_NEW]
    for n, (k, iid) in enumerate(starts):
        if iid == arrangement:
            return k, (starts[n + 1][0] if n + 1 < len(starts) else len(spans))
    raise ValueError("no arrangement %d (have %s)" % (arrangement, [i for _k, i in starts]))


def _marker_groups(spans, data, a: int, b: int) -> List[Tuple[int, int]]:
    """[first, last] event indices of each marker group in [a, b)."""
    groups, k = [], a
    while k < b:
        if spans[k][0] == EV_MARKER_POS:
            j = k
            while j + 1 < b and spans[j][0] != EV_MARKER_NAME and spans[j + 1][0] != EV_MARKER_POS:
                j += 1
            groups.append((k, j))
            k = j + 1
        else:
            k += 1
    return groups


def read(path: str, arrangement: Optional[int] = None, tracks: int = 16) -> dict:
    """Markers (bar, name, type) and performance settings of the first ``tracks``
    playlist tracks, per arrangement."""
    _blob, _d, data, ppq = _split(path)
    spans = list(flp_reader.event_spans(data))
    bar = ppq * 4
    names = {v: k for k, v in MOTION.items()}, {v: k for k, v in PRESS.items()}, {v: k for k, v in SYNC.items()}
    out = []
    iids = [struct.unpack("<H", data[p0:p1])[0] for eid, _s, p0, p1 in spans if eid == flp_reader.EV_ARRANGEMENT_NEW]
    for iid in iids:
        if arrangement is not None and iid != arrangement:
            continue
        a, b = _arrangement_range(spans, data, iid)
        markers = []
        for g0, g1 in _marker_groups(spans, data, a, b):
            v = struct.unpack("<I", data[spans[g0][2]:spans[g0][3]])[0]
            name = ""
            for k in range(g0, g1 + 1):
                if spans[k][0] == EV_MARKER_NAME:
                    name = flp_reader._text(data[spans[k][2]:spans[k][3]], True)
            action = v >> 24
            markers.append({"bar": round((v & 0xFFFFFF) / bar + 1, 4), "name": name,
                            "type": _ACTION_NAMES.get(action, "action %d" % action)})
        trk = []
        for eid, _s, p0, p1 in spans[a:b]:
            if eid != EV_TRACK_DATA or p1 - p0 < 46:
                continue
            raw = data[p0:p1]
            t = struct.unpack_from("<I", raw, 0)[0]
            if 1 <= t <= tracks:
                trk.append({"track": t,
                            "motion": names[0].get(struct.unpack_from("<I", raw, 22)[0]),
                            "press": names[1].get(struct.unpack_from("<I", raw, 26)[0]),
                            "trigger_sync": names[2].get(struct.unpack_from("<I", raw, 30)[0]),
                            "position_sync": names[2].get(struct.unpack_from("<I", raw, 42)[0])})
        start = [m for m in markers if m["type"] == "start"]
        out.append({"arrangement": iid, "markers": markers, "tracks": trk,
                    "performance_zone_bars": (start[0]["bar"] - 1) if start else None})
    return {"file": path, "arrangements": out}


def write(src: str, dst: str, arrangement: int, markers: List[Tuple[float, str]],
          start_bar: Optional[float], track_settings: Dict[int, Dict[str, str]],
          clear_markers: bool = True) -> dict:
    """Write ``markers`` ([(bar, name)]) plus a Start marker at ``start_bar``
    into ``arrangement`` and apply ``track_settings`` ({track: {field: value}}).
    With ``clear_markers`` the arrangement's existing plain and Start markers
    are removed first (time-signature and other marker actions are kept)."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("refusing to overwrite the source project")
    for t, fields in track_settings.items():
        if not 1 <= int(t) <= 500:
            raise ValueError("playlist track %s out of range 1-500" % t)
        for f, v in fields.items():
            if f not in TRACK_FIELDS:
                raise ValueError("unknown track setting %r (use %s)" % (f, sorted(TRACK_FIELDS)))
            if v not in TRACK_FIELDS[f][1]:
                raise ValueError("%s must be one of %s" % (f, sorted(TRACK_FIELDS[f][1])))

    blob, d, data, ppq = _split(src)
    spans = list(flp_reader.event_spans(data))
    a, b = _arrangement_range(spans, data, arrangement)
    groups = _marker_groups(spans, data, a, b)

    # Template for the unknown marker fields: an existing marker's own events.
    tail = _DEFAULT_MARKER_TAIL
    if groups:
        g0, g1 = groups[0]
        tail = [(spans[k][0], data[spans[k][2]:spans[k][3]]) for k in range(g0 + 1, g1 + 1)
                if spans[k][0] != EV_MARKER_NAME]

    drop = set()
    for g0, g1 in groups:
        action = struct.unpack("<I", data[spans[g0][2]:spans[g0][3]])[0] >> 24
        if clear_markers and action in (ACTION_MARKER, ACTION_START):
            drop.update(range(g0, g1 + 1))
        elif start_bar is not None and action == ACTION_START:
            drop.update(range(g0, g1 + 1))              # only one Start marker

    # Insert where the first marker was, else right after the playlist items.
    insert_at = groups[0][0] if groups else next(
        (k + 1 for k in range(a, b) if spans[k][0] == flp_reader.EV_PLAYLIST_ITEMS), a + 1)

    bar = ppq * 4
    new = []
    wanted = sorted(((float(bar_no), name, ACTION_MARKER) for bar_no, name in markers), key=lambda m: m[0])
    if start_bar is not None:
        wanted.append((float(start_bar), "Start", ACTION_START))
    for bar_no, name, action in wanted:
        ticks = int(round((bar_no - 1) * bar))
        if ticks >= 1 << 24:
            raise ValueError("marker at bar %s is too far out" % bar_no)
        group = _event(EV_MARKER_POS, struct.pack("<I", ticks | (action << 24)))
        group += b"".join(_event(eid, raw) for eid, raw in tail)
        group += _event(EV_MARKER_NAME, _text(name))
        new.append(group)

    patched = 0
    parts = []
    for k, (eid, s0, p0, p1) in enumerate(spans):
        if k == insert_at:
            parts.extend(new)
        if k in drop:
            continue
        if a <= k < b and eid == EV_TRACK_DATA and p1 - p0 >= 46:
            raw = bytearray(data[p0:p1])
            t = struct.unpack_from("<I", raw, 0)[0]
            if t in track_settings:
                for f, v in track_settings[t].items():
                    off, table = TRACK_FIELDS[f]
                    struct.pack_into("<I", raw, off, table[v])
                parts.append(data[s0:p0] + bytes(raw))
                patched += 1
                continue
        parts.append(data[s0:p1])
    if insert_at >= len(spans):
        parts.extend(new)
    new_data = b"".join(parts)
    out = blob[:d + 4] + struct.pack("<I", len(new_data)) + new_data + blob[d + 8 + len(data):]
    with open(dst, "wb") as f:
        f.write(out)
    return {"file": dst, "arrangement": arrangement, "markers_written": len(new),
            "markers_removed": len({g for g in groups if g[0] in drop}), "tracks_patched": patched}

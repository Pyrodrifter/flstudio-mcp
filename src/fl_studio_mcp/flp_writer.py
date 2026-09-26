"""Write playlist clips into a COPY of an FL Studio project.

FL's scripting API cannot place clips in the playlist, but the project file
stores them as one event per arrangement (id 233): fixed-size items (88 bytes
on FL 26). We splice new items into that single event and fix the FLdt chunk
length -- every other byte of the project is copied unchanged -- then write
the result to a new file that the user opens in FL.

Item layout (FL 26.1, verified against clips placed by hand):
  0  u32 position (ticks)     4  u16 20480 (pattern base)   6  u16 20480+pattern
  8  u32 length (ticks)      12  u16 500-track             14..31 flags/offsets
 32  u32 clip id (unique across the project)               36..87 unchanged
New items are cloned from an existing pattern clip, so unknown fields keep
FL's own values; start/end offsets are forced to -1 (whole pattern).
"""
from __future__ import annotations

import os
import struct
from typing import List, Optional

from . import flp_reader

_BASE = 20480


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _item_size(raw: bytes) -> Optional[int]:
    base = struct.pack("<H", _BASE)
    return next((s for s in range(32, len(raw) + 1, 4)
                 if len(raw) % s == 0
                 and all(raw[o + 4:o + 6] == base for o in range(0, len(raw), s))), None)


def _locate(data: bytes):
    """Map arrangement iid -> (span of its 233 event | None, name); also
    return every item payload seen (for template + id allocation)."""
    arrs, cur, all_items = {}, None, []
    for eid, start, p0, p1 in flp_reader.event_spans(data):
        if eid == flp_reader.EV_ARRANGEMENT_NEW:
            cur = struct.unpack("<H", data[p0:p1])[0]
            arrs[cur] = {"span": None, "name": None}
        elif eid == flp_reader.EV_ARRANGEMENT_NAME and cur is not None:
            arrs[cur]["name"] = flp_reader._text(data[p0:p1], True)
        elif eid == flp_reader.EV_PLAYLIST_ITEMS and cur is not None:
            arrs[cur]["span"] = (start, p0, p1)
            all_items.append(data[p0:p1])
    return arrs, all_items


def write_clips(src: str, dst: str, arrangement: int, clips: List[dict],
                ppq: Optional[int] = None, replace: bool = False) -> dict:
    """Add ``clips`` ({pattern, track (1-based), bar (1-based), length_bars})
    to ``arrangement`` of ``src`` and write the result to ``dst``."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("refusing to overwrite the source project")
    blob = open(src, "rb").read()
    hlen = struct.unpack_from("<I", blob, 4)[0]
    ppq = ppq or struct.unpack_from("<hHH", blob, 8)[2]
    d = 8 + hlen
    data = blob[d + 8:d + 8 + struct.unpack_from("<I", blob, d + 4)[0]]

    arrs, all_items = _locate(data)
    if arrangement not in arrs:
        raise ValueError("no arrangement %d (have %s)" % (arrangement, sorted(arrs)))
    span = arrs[arrangement]["span"]
    if span is None:
        raise ValueError("arrangement %d has no clips yet -- place one clip by hand first "
                         "so the writer has an item to clone" % arrangement)
    start, p0, p1 = span
    existing = data[p0:p1]
    # An arrangement with no clips still has an (empty) items event; take the
    # item size from any arrangement that has clips.
    size = next((_item_size(x) for x in ([existing] if existing else []) + all_items if x), None)
    if size is None:
        if not clips and not existing:
            size = 1                                       # nothing to write or read
        else:
            raise ValueError("no clip in the project to learn the item layout from -- "
                             "place one clip by hand first")

    template, max_id = None, 0
    for raw in all_items:
        if not raw or len(raw) % size:
            continue
        for o in range(0, len(raw), size):
            it = raw[o:o + size]
            max_id = max(max_id, struct.unpack_from("<I", it, 32)[0])
            if template is None and struct.unpack_from("<H", it, 6)[0] > _BASE:
                template = it
    if template is None and clips:
        raise ValueError("no pattern clip to use as a template")

    bar = ppq * 4
    items = [] if replace else [existing[o:o + size] for o in range(0, len(existing), size)]
    for c in sorted(clips, key=lambda c: (float(c["bar"]), -int(c["track"]))):
        it = bytearray(template)
        struct.pack_into("<I", it, 0, int(round((float(c["bar"]) - 1) * bar)))
        struct.pack_into("<H", it, 6, _BASE + int(c["pattern"]))
        struct.pack_into("<I", it, 8, int(round(float(c["length_bars"]) * bar)))
        struct.pack_into("<H", it, 12, 500 - int(c["track"]))
        struct.pack_into("<H", it, 18, 0x0040)            # plain, unselected clip
        struct.pack_into("<ii", it, 24, -1, -1)           # whole pattern, no trim
        max_id += 1
        struct.pack_into("<I", it, 32, max_id)
        items.append(bytes(it))
    # Stable sort by position only: FL's own order among existing clips is
    # kept (so adding nothing reproduces the file byte-for-byte).
    items.sort(key=lambda it: struct.unpack_from("<I", it, 0)[0])
    payload = b"".join(items)

    new_data = (data[:start] + bytes([flp_reader.EV_PLAYLIST_ITEMS]) + _varint(len(payload))
                + payload + data[p1:])
    out = blob[:d + 4] + struct.pack("<I", len(new_data)) + new_data + blob[d + 8 + len(data):]
    with open(dst, "wb") as f:
        f.write(out)
    return {"file": dst, "arrangement": arrangement, "name": arrs[arrangement]["name"],
            "added": len(clips), "total_clips": len(items)}

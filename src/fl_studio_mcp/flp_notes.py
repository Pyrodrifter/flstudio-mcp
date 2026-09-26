"""Write pattern notes into a COPY of an FL Studio project.

FL's scripting API can only toggle step-sequencer steps; it cannot write
piano-roll notes (lengths, pitches, velocities) without the Piano-roll
pyscript bridge. The project file stores every pattern's notes as a pair of
events near the top of the file (before the first channel):

    65   u16  pattern number (1-based)
    224  data 24 bytes per note:
         0 u32 position (ticks)   4 u16 flags (0x4000)   6 u16 channel (rack index)
         8 u32 length (ticks; 0 = step-sequencer step)   12 u16 key (60 = C5)
        14 u16 group  16 u8 fine pitch (120 = 0)  17 u8 -  18 u8 release (64)
        19 u8 MIDI channel  20 u8 pan (64 = centre)  21 u8 velocity (0-128, 100 default)
        22 u8 mod X (128)  23 u8 mod Y (128)

Pattern names/colours/lengths live elsewhere (a second 65 block) and are set
through the live API. Like flp_writer, every other byte is copied unchanged.
"""
from __future__ import annotations

import os
import struct
from typing import Dict, Iterable, List

from . import flp_reader

_NOTE = struct.Struct("<IHHIHHBBBBBBBB")
FLAG_NOTE = 0x4000


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def pack_notes(notes: Iterable[dict]) -> bytes:
    """notes: {channel, position, length, key, velocity?(0-128), pan?(0-128),
    fine_pitch?(0-240), release?(0-128)} in ticks."""
    rows = sorted(notes, key=lambda n: (int(n["position"]), int(n["channel"]), int(n["key"])))
    return b"".join(_NOTE.pack(int(n["position"]), FLAG_NOTE, int(n["channel"]), int(n.get("length", 0)),
                               int(n["key"]), 0, int(n.get("fine_pitch", 120)), 0,
                               int(n.get("release", 64)), 0, int(n.get("pan", 64)),
                               max(0, min(128, int(n.get("velocity", 100)))), 128, 128) for n in rows)


def write_patterns(src: str, dst: str, patterns: Dict[int, List[dict]], replace: bool = True) -> dict:
    """Put ``patterns`` ({pattern number: [note, ...]}) into a copy of ``src``.
    With ``replace`` a pattern's existing notes are dropped, else appended."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("refusing to overwrite the source project")
    blob = open(src, "rb").read()
    hlen = struct.unpack_from("<I", blob, 4)[0]
    d = 8 + hlen
    data = blob[d + 8:d + 8 + struct.unpack_from("<I", blob, d + 4)[0]]
    spans = list(flp_reader.event_spans(data))

    first_chan = next((k for k, s in enumerate(spans) if s[0] == flp_reader.EV_CHAN_NEW), len(spans))
    # Existing (65, 224) note pairs before the first channel.
    pairs, k = {}, 0
    while k < first_chan:
        eid, s0, p0, p1 = spans[k]
        if eid == flp_reader.EV_PAT_NEW and k + 1 < first_chan and spans[k + 1][0] == flp_reader.EV_PAT_NOTES:
            pat = struct.unpack("<H", data[p0:p1])[0]
            n0, n1 = spans[k + 1][2], spans[k + 1][3]
            pairs[pat] = (k, data[n0:n1])
            k += 2
        else:
            k += 1
    if pairs:
        region_at = min(i for i, _raw in pairs.values())
    else:
        # Right after the 216 event that precedes the note block (else before
        # the first channel).
        region_at = next((i + 1 for i in range(first_chan) if spans[i][0] == 216), first_chan)

    merged = {p: raw for p, (_i, raw) in pairs.items()}
    for pat, notes in patterns.items():
        if not 1 <= int(pat) <= 999:
            raise ValueError("pattern %s out of range 1-999" % pat)
        packed = pack_notes(notes)
        merged[int(pat)] = packed if replace else merged.get(int(pat), b"") + packed
    region = b"".join(bytes([flp_reader.EV_PAT_NEW]) + struct.pack("<H", p)
                      + bytes([flp_reader.EV_PAT_NOTES]) + _varint(len(raw)) + raw
                      for p, raw in sorted(merged.items()) if raw)
    skip = {i for i, _raw in pairs.values()} | {i + 1 for i, _raw in pairs.values()}
    parts = []
    for k, (eid, s0, p0, p1) in enumerate(spans):
        if k == region_at:
            parts.append(region)
        if k in skip:
            continue
        parts.append(data[s0:p1])
    if region_at >= len(spans):
        parts.append(region)
    new_data = b"".join(parts)
    out = blob[:d + 4] + struct.pack("<I", len(new_data)) + new_data + blob[d + 8 + len(data):]
    with open(dst, "wb") as f:
        f.write(out)
    return {"file": dst, "patterns_written": len(patterns),
            "notes_written": sum(len(v) for v in patterns.values()), "patterns_total": len(merged)}

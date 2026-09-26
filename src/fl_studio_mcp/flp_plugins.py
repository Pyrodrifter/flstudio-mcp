"""Load presets and mixer effects in a COPY of an FL Studio project.

FL's scripting API can't load a plugin into a mixer slot or pick a preset by
name, but a plugin preset file (.fst) is a tiny FL event stream holding the
same events a project uses for that plugin:

    201 plugin name   212 wrapper (u32 insert, u32 slot, ...)   [203 display name]
    155 colour        128 icon          41 u8                  213 plugin state

Channel preset  -> replace the channel's 213 state with the preset's.
Mixer effect    -> an insert is a 236 event followed by ten 98 (slot index)
                   events; a filled slot has its plugin events right before its
                   98 event. We insert the preset's events there.
Every other byte is copied unchanged.
"""
from __future__ import annotations

import os
import struct
from typing import Dict, List, Tuple

from . import flp_reader

EV_SLOT = 98
EV_INSERT = 236
EV_STATE = 213
EV_WRAPPER = 212
_PLUGIN_EVENTS = (201, 212, 203, 155, 128, 41, 213)


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


def _load(path: str):
    blob = open(path, "rb").read()
    if blob[:4] != b"FLhd":
        raise ValueError("not an FL Studio file: %s" % path)
    d = 8 + struct.unpack_from("<I", blob, 4)[0]
    data = blob[d + 8:d + 8 + struct.unpack_from("<I", blob, d + 4)[0]]
    return blob, d, data, list(flp_reader.event_spans(data))


def read_preset(path: str) -> Dict[int, bytes]:
    """Plugin events of an .fst preset (FL 11.5+ format, UTF-16 names)."""
    _b, _d, data, spans = _load(path)
    ev = {}
    for eid, _s, p0, p1 in spans:
        if eid == 199:
            ver = data[p0:p1].decode("ascii", "replace").rstrip("\x00")
            if tuple(int(x) for x in ver.split(".")[:2] if x.isdigit()) < (11, 5):
                raise ValueError("%s is an old-format preset (FL %s)" % (os.path.basename(path), ver))
        if eid in _PLUGIN_EVENTS:
            ev[eid] = data[p0:p1]
    if 201 not in ev or EV_STATE not in ev or EV_WRAPPER not in ev:
        raise ValueError("%s has no plugin events" % path)
    return ev


def _write(blob, d, data, parts, dst):
    new_data = b"".join(parts)
    out = blob[:d + 4] + struct.pack("<I", len(new_data)) + new_data + blob[d + 8 + len(data):]
    with open(dst, "wb") as f:
        f.write(out)


def apply(src: str, dst: str, channel_presets: Dict[int, str] = None,
          mixer_fx: List[Tuple[int, int, str]] = None) -> dict:
    """channel_presets {channel index: .fst}; mixer_fx [(insert, slot, .fst)]."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("refusing to overwrite the source project")
    channel_presets = channel_presets or {}
    mixer_fx = mixer_fx or []
    blob, d, data, spans = _load(src)

    # Channel blocks: from a 64 event to the next 64 (or the first insert).
    chan_state = {}
    cur = None
    for k, (eid, _s, p0, p1) in enumerate(spans):
        if eid == flp_reader.EV_CHAN_NEW:
            cur = struct.unpack("<H", data[p0:p1])[0]
        elif eid == EV_INSERT:
            cur = None
        elif eid == EV_STATE and cur is not None and cur not in chan_state:
            chan_state[cur] = k
    missing = sorted(set(channel_presets) - set(chan_state))
    if missing:
        raise ValueError("channels %s have no plugin state (not a plugin channel?)" % missing)
    replace = {chan_state[ch]: read_preset(p)[EV_STATE] for ch, p in channel_presets.items()}

    # Mixer inserts: 236 events that start a run of 98 slot events.
    inserts = [k for k, s in enumerate(spans) if s[0] == EV_INSERT
               and any(spans[j][0] == EV_SLOT for j in range(k + 1, min(k + 3, len(spans))))]
    before = {}
    for ins, slot, path in mixer_fx:
        if ins >= len(inserts):
            raise ValueError("no mixer insert %d (have %d)" % (ins, len(inserts)))
        end = inserts[ins + 1] if ins + 1 < len(inserts) else len(spans)
        slots = [j for j in range(inserts[ins], end) if spans[j][0] == EV_SLOT]
        target = next((j for j in slots if struct.unpack("<H", data[spans[j][2]:spans[j][3]])[0] == slot), None)
        if target is None:
            raise ValueError("insert %d has no slot %d" % (ins, slot))
        if spans[target - 1][0] == EV_STATE:
            raise ValueError("insert %d slot %d is already filled" % (ins, slot))
        ev = read_preset(path)
        wrapper = bytearray(ev[EV_WRAPPER])
        struct.pack_into("<II", wrapper, 0, ins, slot)
        group = _event(201, ev[201]) + _event(EV_WRAPPER, bytes(wrapper))
        if 203 in ev:
            group += _event(203, ev[203])
        group += _event(155, ev.get(155, b"\x00" * 4)) + _event(128, ev.get(128, b"HQV\x00"))
        group += _event(41, ev.get(41, b"\x00")) + _event(EV_STATE, ev[EV_STATE])
        before[target] = group

    parts = []
    for k, (eid, s0, p0, p1) in enumerate(spans):
        if k in before:
            parts.append(before[k])
        if k in replace:
            parts.append(_event(EV_STATE, replace[k]))
            continue
        parts.append(data[s0:p1])
    _write(blob, d, data, parts, dst)
    return {"file": dst, "channel_presets": len(replace), "mixer_fx": len(before)}

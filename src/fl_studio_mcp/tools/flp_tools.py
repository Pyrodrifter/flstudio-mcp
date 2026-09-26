"""Project-file tools: notes, channel presets and mixer effects in a COPY.

FL's API can't write piano-roll notes, load a preset by name or put a plugin
in a mixer slot. These tools save the open project, write a copy with the
change, re-read it to verify, and tell you which file to open.
"""
from __future__ import annotations

import glob
import os
from typing import Annotated, Dict, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import flp_notes, flp_plugins, flp_reader
from .project import _copy_path, _load

PRESET_ROOTS = [
    r"C:\Program Files\Image-Line\FL Studio 2026\Data\Patches\Plugin presets",
    r"C:\Program Files\Image-Line\FL Studio 2025\Data\Patches\Plugin presets",
    os.path.join(os.path.expanduser("~"), "Documents", "Image-Line", "FL Studio", "Presets", "Plugin presets"),
]


class Note(BaseModel):
    channel: int = Field(ge=0, description="Channel-rack index.")
    step: float = Field(ge=0, description="Start in 16th steps from the pattern start (16 per bar).")
    length: float = Field(0, ge=0, description="Length in 16th steps; 0 = a step-sequencer step.")
    key: int = Field(60, ge=0, le=131, description="Note (60 = C5 in FL, middle C).")
    velocity: int = Field(100, ge=0, le=128)
    pan: int = Field(64, ge=0, le=128, description="0 left, 64 centre, 128 right.")


class PatternNotes(BaseModel):
    pattern: int = Field(ge=1, le=999)
    notes: List[Note]


class MixerFx(BaseModel):
    insert: int = Field(ge=0, description="Mixer insert (0 = master). Not FL's last 'Current' track.")
    slot: int = Field(ge=0, le=9)
    preset: str = Field(description="Preset: an .fst path, or 'Plugin/Preset name' found under FL's presets, "
                                    "e.g. 'Fruity Delay 3/Ping pong' or 'LuxeVerb/Default'.")


class ChannelPreset(BaseModel):
    channel: int = Field(ge=0)
    preset: str = Field(description="As for MixerFx.preset, e.g. 'Harmor/Lead Acido' (FL 11.5+ preset files).")


def find_preset(spec: str) -> str:
    if os.path.isfile(spec):
        return spec
    plugin, _, name = spec.replace("\\", "/").partition("/")
    for root in PRESET_ROOTS:
        for kind in ("Generators", "Effects"):
            hits = glob.glob(os.path.join(root, kind, plugin, "**", name + ".fst"), recursive=True)
            if hits:
                return hits[0]
    raise ValueError("preset %r not found (plugin folder / preset name, e.g. 'Fruity Delay 3/Tape')" % spec)


def list_presets(plugin: str, contains: str = "") -> List[str]:
    out = []
    for root in PRESET_ROOTS:
        for kind in ("Generators", "Effects"):
            base = os.path.join(root, kind, plugin)
            for f in glob.glob(os.path.join(base, "**", "*.fst"), recursive=True):
                name = os.path.relpath(f, base)[:-4]
                if contains.lower() in name.lower():
                    try:
                        flp_plugins.read_preset(f)
                        out.append(name)
                    except ValueError:
                        pass                                   # old format, can't be injected
    return sorted(set(out))


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={"title": "Write pattern notes (writes a project copy)", "readOnlyHint": False,
                           "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
    def fl_flp_write_notes(
        patterns: List[PatternNotes],
        replace: Annotated[bool, Field(description="Replace each pattern's notes (else add to them).")] = True,
        output_name: Annotated[Optional[str], Field(description="Copy's file name (default '<project> - Notes.flp').")] = None,
    ) -> dict:
        """Write any number of notes -- real lengths, pitches, velocities, pan --
        into any patterns (new pattern numbers are created), without the
        Piano-roll bridge. Saves the open project, writes a COPY, verifies the
        note counts. Open the copy in FL; set names/colours live afterwards."""
        _proj, meta = _load(True, None)
        src = meta["file"]
        dst = _copy_path(src, output_name, "Notes")
        step = flp_reader.parse(src)["ppq"] // 4
        data: Dict[int, list] = {}
        for p in patterns:
            data.setdefault(p.pattern, []).extend(
                {"channel": n.channel, "position": round(n.step * step), "length": round(n.length * step),
                 "key": n.key, "velocity": n.velocity, "pan": n.pan} for n in p.notes)
        res = flp_notes.write_patterns(src, dst, data, replace=replace)
        got = flp_reader.parse(dst)["patterns"]
        bad = [k for k, v in data.items() if replace and len(got.get(k, {}).get("notes", [])) != len(v)]
        return {**res, "source": src, "verified": not bad, "mismatched_patterns": bad,
                "next_step": "In FL: File > Open '%s'." % os.path.basename(dst)}

    @mcp.tool(annotations={"title": "Load presets / add mixer effects (writes a project copy)",
                           "readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": False, "openWorldHint": True})
    def fl_flp_load_plugins(
        mixer_fx: Optional[List[MixerFx]] = None,
        channel_presets: Optional[List[ChannelPreset]] = None,
        output_name: Annotated[Optional[str], Field(description="Copy's file name (default '<project> - FX.flp').")] = None,
    ) -> dict:
        """Put FL effects into empty mixer slots and load presets onto existing
        plugin channels, straight from FL's preset files -- things the live API
        can't do. Saves the open project, writes a COPY. Tweak parameters live
        afterwards with fl_plugin_set_param / fl_exec."""
        _proj, meta = _load(True, None)
        src = meta["file"]
        dst = _copy_path(src, output_name, "FX")
        res = flp_plugins.apply(src, dst,
                                {c.channel: find_preset(c.preset) for c in channel_presets or []},
                                [(m.insert, m.slot, find_preset(m.preset)) for m in mixer_fx or []])
        return {**res, "source": src, "next_step": "In FL: File > Open '%s'." % os.path.basename(dst)}

    @mcp.tool(annotations={"title": "List loadable preset files", "readOnlyHint": True,
                           "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
    def fl_flp_list_presets(
        plugin: Annotated[str, Field(description="Plugin folder name, e.g. 'Harmor', 'Fruity Delay 3', 'LuxeVerb'.")],
        contains: Annotated[str, Field(description="Filter by text in the preset path.")] = "",
    ) -> dict:
        """Preset files fl_flp_load_plugins can load for a plugin (FL 11.5+
        format only)."""
        names = list_presets(plugin, contains)
        return {"plugin": plugin, "count": len(names), "presets": names[:300]}

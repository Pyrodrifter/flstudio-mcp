"""Phase 3 studio tools: undo, channel swing/pitch, playlist tracks, pattern
properties, mixer effect slots, and one-call section writes.

Everything here goes through FL's scripting API (no Piano roll) except the
`notes` parts of fl_write_section, which use the verified Piano-roll bridge.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol
from ..connection import get_bridge
from .pianoroll import PianoRollNote
from .steps import Step, write_steps

_WR = {"readOnlyHint": False, "destructiveHint": False,
       "idempotentHint": True, "openWorldHint": True}
_RO = {"readOnlyHint": True, "destructiveHint": False,
       "idempotentHint": True, "openWorldHint": True}

_ColorArg = Annotated[Optional[str], Field(
    description="Colour as '#RRGGBB' hex; omit to leave unchanged.")]


def _color_params(color: Optional[str]) -> dict:
    if color is None:
        return {}
    h = color.lstrip("#")
    if len(h) != 6:
        raise ValueError("colour must be '#RRGGBB', got %r" % color)
    return {"r": int(h[0:2], 16), "g": int(h[2:4], 16), "b": int(h[4:6], 16)}


class SectionPart(BaseModel):
    channel: int = Field(ge=0, description="Channel-rack index.")
    steps: Optional[List[Step]] = Field(
        None, description="Drum-style 1/16 steps (written via the step sequencer).")
    notes: Optional[List[PianoRollNote]] = Field(
        None, description="Melodic notes with lengths (written via the verified Piano-roll bridge).")
    mode: str = Field("replace", description="'replace' clears this channel in the pattern first; 'append' adds.")


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={"title": "Undo / redo", **_WR, "idempotentHint": False,
                           "destructiveHint": True})
    def fl_undo(
        steps: Annotated[int, Field(ge=0, le=50, description="How many history steps; 0 = only report what would be undone.")] = 1,
        redo: Annotated[bool, Field(description="Redo instead of undo.")] = False,
    ) -> dict:
        """Step FL's own undo history (Ctrl+Z / redo). It is FL's global
        history, so it also undoes edits made by hand -- call with steps=0
        first to see the current step's description (`hint`)."""
        return get_bridge().call(protocol.CMD_UNDO, {"steps": steps, "redo": redo})

    @mcp.tool(annotations={"title": "Project swing", **_WR})
    def fl_swing(
        value: Annotated[Optional[int], Field(ge=0, le=128, description="Swing amount; omit to only read.")] = None,
    ) -> dict:
        """Read (and optionally set) the project-wide swing -- FL's main swing
        knob, which applies to step-sequencer patterns."""
        return get_bridge().call(protocol.CMD_SWING, {"value": value})

    @mcp.tool(annotations={"title": "Channel pitch", **_WR})
    def fl_channel_props(
        channel: Annotated[int, Field(ge=0, description="Channel-rack index.")],
        pitch_cents: Annotated[Optional[float], Field(ge=-4800, le=4800, description="Channel pitch in cents; omit to only read.")] = None,
    ) -> dict:
        """Read (and optionally set) a channel's pitch in cents. Returns the
        value read back after any change. (Swing is project-wide: fl_swing.)"""
        return get_bridge().call(protocol.CMD_CHANNEL_PROPS, {
            "channel": channel, "pitch_cents": pitch_cents})

    @mcp.tool(annotations={"title": "List playlist tracks", **_RO})
    def fl_playlist_tracks(
        start: Annotated[int, Field(ge=1, description="First track (1-based).")] = 1,
        count: Annotated[int, Field(ge=1, le=25, description="How many tracks.")] = 10,
    ) -> dict:
        """Playlist tracks: name, colour, mute, solo. (Clip placement per track
        comes from fl_read_project.)"""
        return get_bridge().call(protocol.CMD_PLAYLIST_TRACKS, {"start": start, "count": count})

    @mcp.tool(annotations={"title": "Set playlist track name/colour/mute", **_WR})
    def fl_set_playlist_track(
        track: Annotated[int, Field(ge=1, description="Playlist track (1-based).")],
        name: Annotated[Optional[str], Field(description="New name; '' restores FL's default ('Track N'); omit to leave.")] = None,
        color: _ColorArg = None,
        mute: Annotated[Optional[bool], Field(description="Mute state; omit to leave.")] = None,
    ) -> dict:
        """Rename, recolour and/or mute one playlist track."""
        return get_bridge().call(protocol.CMD_PLAYLIST_SET_TRACK, {
            "track": track, "name": name, "mute": mute, **_color_params(color)})

    @mcp.tool(annotations={"title": "Set pattern name/colour/length", **_WR})
    def fl_set_pattern(
        pattern: Annotated[int, Field(ge=1, description="Pattern number (1-based).")],
        name: Annotated[Optional[str], Field(description="New name; omit to leave.")] = None,
        color: _ColorArg = None,
        length_beats: Annotated[Optional[int], Field(ge=1, le=1024, description="Length in beats (4 per bar).")] = None,
        select: Annotated[bool, Field(description="Also make it the current pattern.")] = False,
    ) -> dict:
        """Rename, recolour, resize and/or select a pattern."""
        return get_bridge().call(protocol.CMD_PATTERN_SET, {
            "pattern": pattern, "name": name, "length_beats": length_beats,
            "select": select, **_color_params(color)})

    @mcp.tool(annotations={"title": "List mixer effect slots", **_RO})
    def fl_mixer_slots(
        track: Annotated[int, Field(ge=0, description="Mixer track (0 = Master).")],
    ) -> dict:
        """Effects loaded on a mixer track: slot, plugin name, mix level, mute,
        and whether the track's slots are enabled."""
        return get_bridge().call(protocol.CMD_MIXER_SLOTS, {"track": track})

    @mcp.tool(annotations={"title": "Set mixer slot mix/mute", **_WR})
    def fl_set_mixer_slot(
        track: Annotated[int, Field(ge=0, description="Mixer track (0 = Master).")],
        slot: Annotated[Optional[int], Field(ge=0, le=9, description="Effect slot 0-9.")] = None,
        mix: Annotated[Optional[float], Field(ge=0.0, le=1.0, description="Slot wet/dry mix 0..1.")] = None,
        mute: Annotated[Optional[bool], Field(description="Mute (bypass) this slot.")] = None,
        slots_enabled: Annotated[Optional[bool], Field(description="Turn ALL slots on this track on/off.")] = None,
    ) -> dict:
        """Change one effect slot's mix/mute, or switch all of a track's
        effect slots on/off. Returns the slots read back afterwards."""
        return get_bridge().call(protocol.CMD_MIXER_SET_SLOT, {
            "track": track, "slot": slot, "mix": mix, "mute": mute,
            "slots_enabled": slots_enabled})

    @mcp.tool(annotations={"title": "Write a whole section (several parts)", **_WR,
                           "destructiveHint": True, "idempotentHint": False})
    def fl_write_section(
        parts: List[SectionPart],
        pattern: Annotated[Optional[int], Field(ge=1, description="Existing pattern to write into.")] = None,
        new_pattern_name: Annotated[Optional[str], Field(description="Create a new pattern with this name instead.")] = None,
        length_bars: Annotated[Optional[int], Field(ge=1, le=256, description="Set the pattern length first.")] = None,
    ) -> dict:
        """Write drums, bass, chords, leads... into one pattern in one call.
        Each part targets a channel with either `steps` (drums, verified by
        grid readback) or `notes` (melodic, verified by save + .flp re-read).
        Returns per-part results; `ok` is true only if every part verified."""
        bridge = get_bridge()
        if new_pattern_name:
            pat = bridge.call(protocol.CMD_ARRANGE_NEW_PATTERN, {"name": new_pattern_name})["index"]
        elif pattern:
            pat = pattern
        else:
            raise ValueError("give `pattern` or `new_pattern_name`")
        setup = bridge.call(protocol.CMD_PATTERN_SET, {
            "pattern": pat, "select": True,
            "length_beats": length_bars * 4 if length_bars else None})
        results = []
        for part in parts:
            if bool(part.steps) == bool(part.notes):
                results.append({"channel": part.channel, "ok": False,
                                "error": "give exactly one of `steps` or `notes`"})
                continue
            try:
                if part.steps:
                    r = write_steps(bridge, part.channel, part.steps,
                                    clear=part.mode == "replace", pattern=pat)
                else:
                    r = bridge.apply_notes([n.model_dump() for n in part.notes],
                                           part.mode, channel=part.channel)
                    r = {"channel": part.channel, "ok": bool(r.get("ok")),
                         "name": r.get("expected_name"), "verify": r.get("verify"),
                         **({"error": r["error"]} if r.get("error") else {})}
            except Exception as e:
                r = {"channel": part.channel, "ok": False, "error": "%s: %s" % (type(e).__name__, e)}
            results.append(r)
        return {"ok": all(r.get("ok") for r in results), "pattern": pat,
                "pattern_name": setup.get("name"), "parts": results}

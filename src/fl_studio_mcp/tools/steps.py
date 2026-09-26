"""Step-sequencer tools -- channel-addressed note writes with readback.

Unlike the Piano-roll bridge (which writes into whatever channel the Piano roll
happens to show), these address a channel by index through the FL API
(channels.setGridBit / setStepParameterByIndex) and read the grid back, so a
write can't silently land on the wrong instrument. Best for drums and other
one-shot, fixed-length parts on a 1/16 grid.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol
from ..connection import get_bridge

_CHUNK = 32          # steps per SysEx request -- keeps messages small


class Step(BaseModel):
    step: int = Field(ge=0, description="1/16-note step index from the pattern start (16 per bar).")
    velocity: Optional[float] = Field(None, ge=0.0, le=1.0, description="0..1; omit for the channel default.")
    pitch: Optional[int] = Field(None, ge=0, le=127, description="MIDI key; omit for the channel default.")
    pan: Optional[float] = Field(None, ge=0.0, le=1.0, description="0 = left, 0.5 = centre, 1 = right.")
    shift: Optional[int] = Field(None, ge=0, description="Delay in ticks after the step (PPQ/4 ticks per step, 24 at PPQ 96) for swing/humanise; omit for none.")


def write_steps(bridge, channel: int, steps: List[Step], clear: bool = True,
                pattern: Optional[int] = None) -> dict:
    """Chunked steps_write + merged readback result (shared with fl_write_section)."""
    rows = [[s.step, s.velocity, s.pitch, s.pan, s.shift] for s in steps]
    results = []
    for i in range(0, max(len(rows), 1), _CHUNK):
        results.append(bridge.call(protocol.CMD_STEPS_WRITE, {
            "channel": channel, "steps": rows[i:i + _CHUNK],
            "clear": clear and i == 0, "pattern": pattern if i == 0 else None,
            "undo_point": i == 0,        # one undo step per write, not per chunk
        }, timeout=10.0))
    missing = [m for r in results for m in r.get("missing", [])]
    first = results[0]
    return {"ok": not missing, "channel": channel, "name": first.get("name"),
            "pattern": first.get("pattern"), "pattern_name": first.get("pattern_name"),
            "written": sum(r.get("written", 0) for r in results), "missing": missing}


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={"title": "Write step-sequencer steps to a channel",
                           "readOnlyHint": False, "destructiveHint": True,
                           "idempotentHint": True, "openWorldHint": True})
    def fl_write_steps(
        channel: Annotated[int, Field(ge=0, description="Channel-rack index to write into.")],
        steps: List[Step],
        clear: Annotated[bool, Field(description="Clear this channel's existing steps in the pattern first.")] = True,
        pattern: Annotated[Optional[int], Field(ge=1, description="Pattern number (1-based); omit for the current pattern.")] = None,
    ) -> dict:
        """Write drum-style steps (1/16 grid) straight into one channel -- no
        Piano roll involved -- then verify by reading the grid back.

        Use this for kicks/hats/claps/percussion. Steps past the pattern's
        length extend it only if the pattern is long enough; set the length
        first with fl_set_pattern_length (e.g. 32 beats = 8 bars = 128 steps).
        Result `ok` is false if any step failed to read back as set."""
        return write_steps(get_bridge(), channel, steps, clear, pattern)

    @mcp.tool(annotations={"title": "Read a channel's step-sequencer steps",
                           "readOnlyHint": True, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": True})
    def fl_read_steps(
        channel: Annotated[int, Field(ge=0, description="Channel-rack index.")],
        pattern: Annotated[Optional[int], Field(ge=1, description="Pattern number; omit for current.")] = None,
    ) -> dict:
        """List the active 1/16 steps of one channel in a pattern (readback /
        verification after writes)."""
        bridge = get_bridge()
        out, start = [], 0
        first = None
        while start is not None:
            r = bridge.call(protocol.CMD_STEPS_READ, {"channel": channel, "pattern": pattern,
                                                      "start": start})
            first = first or r
            out += r.get("steps", [])
            start = r.get("next_start")
        return {"channel": channel, "name": first.get("name"), "pattern": first.get("pattern"),
                "scanned_steps": first.get("scanned_steps"), "count": len(out), "steps": out}

    @mcp.tool(annotations={"title": "Set pattern length",
                           "readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": True})
    def fl_set_pattern_length(
        beats: Annotated[int, Field(ge=1, le=1024, description="Length in beats (4 per bar): 32 = 8 bars.")],
        pattern: Annotated[Optional[int], Field(ge=1, description="Pattern number; omit for current.")] = None,
    ) -> dict:
        """Set a pattern's length in beats (so step writes past bar 1 stick)."""
        return get_bridge().call(protocol.CMD_PATTERN_SET_LENGTH,
                                 {"beats": beats, "pattern": pattern})

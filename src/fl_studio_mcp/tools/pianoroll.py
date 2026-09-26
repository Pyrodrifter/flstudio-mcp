"""Phase 2 MCP tool -- author notes into FL's piano roll.

Uses the generate-script bridge (pyscript can't read/write files, so the
daemon generates a .pyscript with the notes baked in, then force-focuses FL
and fires the platform run-last-script shortcut). Requires the FL Piano roll
open, and a one-time setup: run 'MCP_Apply' once from the piano-roll Scripting
menu so that 'Run last script again' targets it.
"""

from __future__ import annotations

from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol
from ..connection import get_bridge
from ..pyscript_gen import quantize_notes


class PianoRollNote(BaseModel):
    pitch: int = Field(ge=0, le=127,
                       description="MIDI note (60 = middle C; FL displays it as C5).")
    time_bars: float = Field(0.0, ge=0.0,
                             description="Start, in bars from the pattern start.")
    length_bars: float = Field(1.0, gt=0.0, description="Duration in bars.")
    velocity: float = Field(100 / 127.0, ge=0.0, le=1.0,
                            description="0.0-1.0 (0.787 ~= MIDI velocity 100).")


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "Write piano-roll notes",
        "readOnlyHint": False,
        "destructiveHint": True,   # mode='replace' clears existing notes
        "idempotentHint": False,
        "openWorldHint": True,
    })
    def fl_write_piano_roll_notes(
        notes: List[PianoRollNote],
        mode: Annotated[str, Field(
            description="'replace' clears the pattern first; 'append' adds to it.",
        )] = "replace",
        quantize: Annotated[float, Field(
            description="Optional grid (bars) to snap note starts to before writing: 0.0625=1/16, 0.125=1/8, 0=off.",
        )] = 0.0,
        channel: Annotated[Optional[int], Field(
            ge=0,
            description="Channel-rack index to write into. It is selected (the Piano roll follows "
                        "the selection) and the write is refused if the selection doesn't take; "
                        "afterwards the project is saved and re-read to verify where the notes "
                        "landed. Omit only to write into whatever the Piano roll shows.",
        )] = None,
    ) -> dict:
        """Write notes into one channel of the current pattern via the FL Piano roll.

        Always pass `channel`. Each note: {pitch (MIDI), time_bars, length_bars,
        velocity 0-1}. Set quantize (grid in bars) to snap note starts first.
        With `channel`, the result's `verify` field comes from saving and
        re-reading the .flp: expected vs found notes on that channel, and any
        `misplaced_on` other channels (then ok=false). Needs a saved (named)
        project; otherwise verify is skipped. Setup: run 'MCP_Apply' once from
        the Piano roll Scripting menu per FL session. mode='replace' clears
        that channel's notes in the pattern first.
        """
        arr = [n.model_dump() for n in notes]
        if quantize and quantize > 0:
            arr = quantize_notes(arr, float(quantize))
        return get_bridge().apply_notes(arr, mode, channel=channel)

    @mcp.tool(annotations={
        "title": "Piano roll status (which channel/pattern)",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    })
    def fl_piano_roll_status() -> dict:
        """Read which channel the Piano roll is showing (its caption), the
        selected channel and the current pattern -- i.e. where a note-write
        would land right now."""
        return get_bridge().call(protocol.CMD_PIANOROLL_STATUS, {})

    @mcp.tool(annotations={
        "title": "Quantize piano-roll notes",
        "readOnlyHint": False, "destructiveHint": False,
        "idempotentHint": False, "openWorldHint": True,
    })
    def fl_quantize_pattern(
        grid_bars: Annotated[float, Field(gt=0, description="Snap grid in bars: 0.0625=1/16, 0.125=1/8, 0.25=1/4.")] = 0.0625,
        snap_ends: Annotated[bool, Field(description="Also snap note lengths to the grid.")] = False,
        channel: Annotated[Optional[int], Field(
            ge=0, description="Channel-rack index to quantize (Piano roll is retargeted + verified).",
        )] = None,
    ) -> dict:
        """Quantize the notes ALREADY in the open Piano roll: reads the score,
        snaps note starts (and optionally lengths) to the grid, rewrites -- via
        the pyscript bridge, no dialog. Needs the Piano roll open + MCP_Apply
        armed once this session (same setup as note writing)."""
        return get_bridge().apply_notes([], trigger=True, quantize=float(grid_bars),
                                        snap_ends=snap_ends, channel=channel)

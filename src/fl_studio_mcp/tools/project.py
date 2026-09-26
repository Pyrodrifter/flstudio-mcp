"""Project readback from the saved .flp -- the full-visibility path.

FL's scripting API can't read Piano-roll notes, channel samples/plugins or the
playlist, but the project file can. These tools optionally save first (so the
file is current), then parse it with flp_reader. For never-saved projects they
fall back to FL's newest autosave in Projects/Backup and report its age.
"""
from __future__ import annotations

import time
from typing import Annotated, Optional

from fastmcp import FastMCP
from pydantic import Field

from .. import flp_reader, protocol
from ..connection import get_bridge


def _load(save_first: bool, path: Optional[str]):
    """Return (parsed project, meta) -- meta says which file, how old, and
    whether the save succeeded."""
    meta: dict = {}
    title = None
    if path is None:
        bridge = get_bridge()
        try:
            title = bridge.call(protocol.CMD_PROJECT_INFO, {}).get("title")
        except Exception as e:
            meta["title_error"] = str(e)
        meta["title"] = title
        if save_first:
            before = time.time()
            try:
                res = bridge.call(protocol.CMD_PROJECT_SAVE, {}, timeout=10.0)
            except Exception as e:
                res = {"ok": False, "error": str(e)}
            meta["saved"] = bool(res.get("ok"))
            if not res.get("ok"):
                meta["save_error"] = res.get("error")
            else:
                deadline = before + 8.0
                while time.time() < deadline:
                    f = flp_reader.find_latest(title)
                    if f and flp_reader.file_age_seconds(f) < time.time() - before + 0.5:
                        break
                    time.sleep(0.25)
                time.sleep(0.3)          # let FL finish writing
        path = flp_reader.find_latest(title)
        if path is None:
            raise FileNotFoundError("No .flp found under %s" % flp_reader.project_dirs())
    meta["file"] = path
    meta["file_age_seconds"] = round(flp_reader.file_age_seconds(path), 1)
    if "Backup" in path and "autosaved" in path:
        meta["warning"] = ("Reading FL's autosave (%.0fs old) -- recent edits may be missing. "
                           "Save the project once (Ctrl+S) so reads can save first."
                           % meta["file_age_seconds"])
    return flp_reader.parse(path), meta


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Read project overview (from .flp)", **_RO})
    def fl_read_project(
        save_first: Annotated[bool, Field(description="Save (Ctrl+S) first so the file is current. Ignored for never-saved projects.")] = True,
        path: Annotated[Optional[str], Field(description="Explicit .flp path; omit to use the open project / newest autosave.")] = None,
    ) -> dict:
        """Everything the live API can't see: each channel's plugin/sample,
        every pattern's per-channel note counts and length, and playlist clips
        per arrangement. Reports which file was read and how old it is."""
        proj, meta = _load(save_first, path)
        return {**meta, **flp_reader.summarize(proj)}

    @mcp.tool(annotations={"title": "Read pattern notes (from .flp)", **_RO})
    def fl_read_notes(
        pattern: Annotated[int, Field(ge=1, description="Pattern number (1-based).")],
        channel: Annotated[Optional[int], Field(ge=0, description="Channel-rack index; omit for all channels.")] = None,
        save_first: Annotated[bool, Field(description="Save first so the file is current.")] = True,
        path: Annotated[Optional[str], Field(description="Explicit .flp path.")] = None,
    ) -> dict:
        """Every note in a pattern -- pitch, time_bars, length_bars, velocity
        0..1 -- in the same units fl_write_piano_roll_notes takes, so writes
        can be verified or edited round-trip."""
        proj, meta = _load(save_first, path)
        return {**meta, **flp_reader.notes_view(proj, pattern, channel)}

    @mcp.tool(annotations={"title": "Save project (Ctrl+S)", "readOnlyHint": False,
                           "destructiveHint": False, "idempotentHint": True,
                           "openWorldHint": True})
    def fl_save_project() -> dict:
        """Save the open project in place. Refused for never-saved projects
        (FL would open a Save-As dialog) -- save once manually first."""
        return get_bridge().call(protocol.CMD_PROJECT_SAVE, {}, timeout=10.0)

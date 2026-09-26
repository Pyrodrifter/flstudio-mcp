"""Project readback from the saved .flp -- the full-visibility path.

FL's scripting API can't read Piano-roll notes, channel samples/plugins or the
playlist, but the project file can. These tools optionally save first (so the
file is current), then parse it with flp_reader. For never-saved projects they
fall back to FL's newest autosave in Projects/Backup and report its age.
"""
from __future__ import annotations

import os
import time
from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import flp_reader, flp_writer, protocol
from ..connection import get_bridge


class PlaylistClip(BaseModel):
    pattern: int = Field(ge=1, description="Pattern number.")
    track: int = Field(ge=1, le=500, description="Playlist track (1-based).")
    bar: float = Field(ge=1, description="Start bar as FL shows it (1 = song start).")
    length_bars: float = Field(8, gt=0, description="Clip length in bars.")


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

    @mcp.tool(annotations={"title": "Arrange playlist clips (writes a project copy)",
                           "readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": False, "openWorldHint": True})
    def fl_arrange_playlist(
        clips: List[PlaylistClip],
        arrangement: Annotated[int, Field(ge=0, description="Arrangement index as in fl_read_project (0 = first).")],
        replace: Annotated[bool, Field(description="Drop the arrangement's existing clips instead of adding to them.")] = False,
        output_name: Annotated[Optional[str], Field(description="File name for the copy (default '<project> - Arranged.flp').")] = None,
    ) -> dict:
        """Place pattern clips in the playlist. FL's API can't do this live,
        so this saves the open project, writes a COPY with the clips added
        (every other byte unchanged; the original is never overwritten) and
        re-reads the copy to verify. The user then opens the copy in FL --
        edits made in FL after this call are NOT in the copy."""
        proj, meta = _load(True, None)
        if not meta.get("saved"):
            raise RuntimeError("Could not save the open project first (%s); refusing to write a "
                               "copy that might miss recent edits." % meta.get("save_error"))
        src = meta["file"]
        folder, stem = os.path.dirname(src), os.path.splitext(os.path.basename(src))[0]
        base = os.path.splitext(output_name)[0] if output_name else "%s - Arranged" % stem
        dst, n = os.path.join(folder, base + ".flp"), 2
        while os.path.exists(dst):
            dst, n = os.path.join(folder, "%s %d.flp" % (base, n)), n + 1
        known = set(proj["patterns"])
        bad = sorted({c.pattern for c in clips} - known)
        if bad:
            raise ValueError("patterns %s have no notes in the project (have %s)" % (bad, sorted(known)))
        res = flp_writer.write_clips(src, dst, arrangement, [c.model_dump() for c in clips],
                                     replace=replace)
        out = flp_reader.parse(dst)
        arrs_src = flp_reader.summarize(proj)["arrangements"]
        arrs_out = flp_reader.summarize(out)["arrangements"]
        check = [a for a in arrs_out if a["arrangement"] == arrangement][0]["clips"]
        have = {(c["pattern"], c["track"], c["bar"], c["length_bars"]) for c in check if "pattern" in c}
        missing = [c.model_dump() for c in clips
                   if (c.pattern, c.track, float(c.bar), float(c.length_bars)) not in have]
        before = [a for a in arrs_src if a["arrangement"] == arrangement][0]["clips"]
        unchanged = {
            "channels": out["channels"] == proj["channels"],
            "patterns": out["patterns"] == proj["patterns"],
            "other_arrangements": [a for a in arrs_out if a["arrangement"] != arrangement]
                                  == [a for a in arrs_src if a["arrangement"] != arrangement],
            "existing_clips": replace or all(c in check for c in before),
        }
        return {**res, "source": src, "verified": not missing and all(unchanged.values()),
                "missing": missing, "unchanged": unchanged,
                "next_step": "In FL: File > Open '%s'. It is your current project plus the new "
                             "clips; don't edit in FL before opening it." % os.path.basename(dst)}

    @mcp.tool(annotations={"title": "Save project (Ctrl+S)", "readOnlyHint": False,
                           "destructiveHint": False, "idempotentHint": True,
                           "openWorldHint": True})
    def fl_save_project() -> dict:
        """Save the open project in place. Refused for never-saved projects
        (FL would open a Save-As dialog) -- save once manually first."""
        return get_bridge().call(protocol.CMD_PROJECT_SAVE, {}, timeout=10.0)

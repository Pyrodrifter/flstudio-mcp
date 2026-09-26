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

from .. import flp_performance, flp_reader, flp_writer, protocol
from ..connection import get_bridge


class PlaylistClip(BaseModel):
    pattern: int = Field(ge=1, description="Pattern number.")
    track: int = Field(ge=1, le=500, description="Playlist track (1-based).")
    bar: float = Field(ge=1, description="Start bar as FL shows it (1 = song start).")
    length_bars: float = Field(8, gt=0, description="Clip length in bars.")


class PerfClip(BaseModel):
    pattern: int = Field(ge=1, description="Pattern number.")
    track: int = Field(ge=1, le=500, description="Playlist track (1-based) -- one row of the launch grid.")
    block: int = Field(ge=1, description="Block (1-based) -- one column of the launch grid.")


class PerfTrackSettings(BaseModel):
    motion: Optional[str] = Field(None, description="What plays next after a clip: stay, one_shot, march_wrap, "
                                                     "march_stay, march_stop, random, exclusive_random.")
    press: Optional[str] = Field(None, description="Pad/click behaviour: retrigger, hold_stop, hold_motion, latch.")
    trigger_sync: Optional[str] = Field(None, description="Launch quantize: off, quarter_beat, half_beat, beat, "
                                                           "two_beats, four_beats, auto.")
    position_sync: Optional[str] = Field(None, description="Where a launched clip starts playing from: same values "
                                                            "as trigger_sync.")


def _copy_path(src: str, output_name: Optional[str], suffix: str) -> str:
    folder, stem = os.path.dirname(src), os.path.splitext(os.path.basename(src))[0]
    base = os.path.splitext(output_name)[0] if output_name else "%s - %s" % (stem, suffix)
    dst, n = os.path.join(folder, base + ".flp"), 2
    while os.path.exists(dst):
        dst, n = os.path.join(folder, "%s %d.flp" % (base, n)), n + 1
    return dst


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

    @mcp.tool(annotations={"title": "Read Performance Mode setup (from .flp)", **_RO})
    def fl_perf_read(
        arrangement: Annotated[Optional[int], Field(ge=0, description="Arrangement index; omit for all.")] = None,
        tracks: Annotated[int, Field(ge=1, le=500, description="How many playlist tracks to report settings for.")] = 16,
        save_first: Annotated[bool, Field(description="Save first so the file is current.")] = True,
        path: Annotated[Optional[str], Field(description="Explicit .flp path.")] = None,
    ) -> dict:
        """Performance Mode layout: every time marker (bar, name, type -- 'start'
        ends the performance zone), the zone length in bars, and each playlist
        track's motion / press / trigger_sync / position_sync."""
        _proj, meta = _load(save_first, path)
        return {**meta, **flp_performance.read(meta["file"], arrangement, tracks)}

    @mcp.tool(annotations={"title": "Set up Performance Mode (writes a project copy)",
                           "readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": False, "openWorldHint": True})
    def fl_perf_setup(
        arrangement: Annotated[int, Field(ge=0, description="Arrangement index as in fl_read_project (0 = first).")],
        blocks: Annotated[List[str], Field(min_length=1, description="Block (column) names in order, e.g. "
                                                                     "['Intro', 'Drop', 'Break']. One time marker each.")],
        block_bars: Annotated[float, Field(gt=0, description="Length of every block in bars.")] = 8,
        clips: Annotated[Optional[List[PerfClip]], Field(description="Clips to place: pattern on track (row) in block "
                                                                    "(column). Omit to keep the playlist as it is.")] = None,
        replace_clips: Annotated[bool, Field(description="Drop the arrangement's existing clips first.")] = False,
        track_settings: Annotated[Optional[PerfTrackSettings], Field(description="Applied to every track that has "
                                                                             "a clip in the grid (or to `tracks`).")] = None,
        tracks: Annotated[Optional[List[int]], Field(description="Tracks to apply track_settings to (default: the "
                                                                "tracks used by `clips`).")] = None,
        clear_markers: Annotated[bool, Field(description="Remove the arrangement's existing plain and Start markers.")] = True,
        output_name: Annotated[Optional[str], Field(description="File name for the copy (default '<project> - Performance.flp').")] = None,
    ) -> dict:
        """Build a Performance Mode set in one step: pattern clips in a grid
        (rows = playlist tracks, columns = blocks), a named time marker at the
        start of every block, a Start marker right after the last block (so the
        whole grid is the performance zone), and per-track launch settings.
        FL's API can't do any of this live, so it saves the open project and
        writes a COPY (the original is never overwritten), then re-reads the
        copy to verify. Open the copy in FL and switch on Playlist >
        Performance mode."""
        proj, meta = _load(True, None)
        if not meta.get("saved"):
            raise RuntimeError("Could not save the open project first (%s); refusing to write a "
                               "copy that might miss recent edits." % meta.get("save_error"))
        src = meta["file"]
        dst = _copy_path(src, output_name, "Performance")
        clips = clips or []
        if any(c.block > len(blocks) for c in clips):
            raise ValueError("a clip uses block %d but only %d blocks are named"
                             % (max(c.block for c in clips), len(blocks)))
        bad = sorted({c.pattern for c in clips} - set(proj["patterns"]))
        if bad:
            raise ValueError("patterns %s have no notes in the project (have %s)" % (bad, sorted(proj["patterns"])))
        settings = {k: v for k, v in (track_settings.model_dump() if track_settings else {}).items() if v}
        targets = tracks if tracks is not None else sorted({c.track for c in clips})
        per_track = {int(t): settings for t in targets} if settings else {}

        stage, tmp = src, None
        if clips or replace_clips:
            tmp = dst + ".tmp"
            flp_writer.write_clips(src, tmp, arrangement,
                                   [{"pattern": c.pattern, "track": c.track, "bar": 1 + (c.block - 1) * block_bars,
                                     "length_bars": block_bars} for c in clips], replace=replace_clips)
            stage = tmp
        try:
            res = flp_performance.write(stage, dst, arrangement,
                                        [(1 + k * block_bars, name) for k, name in enumerate(blocks)],
                                        1 + len(blocks) * block_bars, per_track, clear_markers=clear_markers)
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

        check = flp_performance.read(dst, arrangement, max([16] + list(per_track)))["arrangements"][0]
        want = [(1.0 + k * block_bars, n) for k, n in enumerate(blocks)]
        got = [(m["bar"], m["name"]) for m in check["markers"] if m["type"] == "marker"]
        ok_markers = all(w in got for w in want) and check["performance_zone_bars"] == len(blocks) * block_bars
        ok_tracks = all(all(t[f] == v for f, v in per_track[t["track"]].items())
                        for t in check["tracks"] if t["track"] in per_track)
        out = flp_reader.parse(dst)
        unchanged = {"channels": out["channels"] == proj["channels"],
                     "patterns": out["patterns"] == proj["patterns"]}
        return {**res, "source": src, "verified": ok_markers and ok_tracks and all(unchanged.values()),
                "performance_zone_bars": check["performance_zone_bars"], "markers": check["markers"],
                "unchanged": unchanged,
                "next_step": "In FL: File > Open '%s', then Playlist > Performance mode (on)."
                             % os.path.basename(dst)}

    @mcp.tool(annotations={"title": "Save project (Ctrl+S)", "readOnlyHint": False,
                           "destructiveHint": False, "idempotentHint": True,
                           "openWorldHint": True})
    def fl_save_project() -> dict:
        """Save the open project in place. Refused for never-saved projects
        (FL would open a Save-As dialog) -- save once manually first."""
        return get_bridge().call(protocol.CMD_PROJECT_SAVE, {}, timeout=10.0)

"""Piano-roll note authoring -- the generate-script bridge.

FL's pyscript sandbox blocks file I/O (read AND write), so we can't pass note
data via a job file. Instead we GENERATE a .pyscript with the notes baked in
(pyscript_gen), write it into FL's Piano roll scripts folder, then force-focus
FL and fire the platform "Run last script again" shortcut
(Ctrl+Alt+Y on Windows, Cmd+Opt+Y on macOS). FL re-reads the file on that
hotkey, so the fresh notes apply with no manual click.

This runs in a process that can write files + send keystrokes (the daemon, or
a normally-launched MCP server). Under the Store/MSIX Claude Desktop the MCP
server can't, so it delegates here via the daemon's "apply_notes" op.

One-time setup the user must do: run MCP_Apply once from the piano-roll
Scripting menu so it becomes FL's "last script".
"""

from __future__ import annotations

import time

from . import flp_reader, protocol
from .pyscript_gen import write_apply_script, write_quantize_script


def prepare_target(call, channel=None):
    """Open the Piano roll -- on ``channel`` when given -- and read back the
    selection. ``call(cmd, params, timeout=)`` talks to the FL controller.
    The Piano roll follows the selected channel, so (ok, info) is ok only when
    the selection readback is exactly ``channel``; otherwise nothing must be
    written (it would land on the wrong instrument)."""
    info = {}
    try:
        if channel is None:
            info["piano_roll_ensured"] = call(protocol.CMD_ENSURE_PIANO_ROLL, {}, timeout=5.0)
            info["piano_roll"] = call(protocol.CMD_PIANOROLL_STATUS, {}, timeout=5.0)
            return True, info
        tgt = call(protocol.CMD_PIANOROLL_TARGET, {"channel": int(channel)}, timeout=5.0)
    except Exception as e:
        info["error"] = "%s: %s" % (type(e).__name__, e)
        return channel is None, info
    info["expected_channel"] = int(channel)
    info["expected_name"] = tgt.get("name")
    info["piano_roll"] = tgt.get("status")
    if not tgt.get("ok"):
        info["error"] = "%s -- not writing." % (tgt.get("error") or "target failed")
        return False, info
    time.sleep(0.3)                          # let FL settle before the hotkey
    return True, info


def _save_and_parse(call):
    """Ctrl+S the open project, wait for the file to update, parse it."""
    t0 = time.time()
    res = call(protocol.CMD_PROJECT_SAVE, {}, timeout=10.0)
    if not res.get("ok"):
        return None, res.get("error") or "save failed"
    path = None
    while time.time() - t0 < 8.0:
        path = flp_reader.find_latest()
        if path and flp_reader.file_age_seconds(path) < time.time() - t0 + 0.5:
            break
        time.sleep(0.2)
    time.sleep(0.3)                          # let FL finish writing
    return flp_reader.parse(path), None


def verify_write(call, notes, channel, pattern, mode):
    """Save + read the .flp and check the notes landed on ``channel`` in
    ``pattern``. Returns {ok, found, expected, misplaced_on, ...}."""
    time.sleep(0.8)                          # the pyscript runs asynchronously
    proj, err = _save_and_parse(call)
    if proj is None:
        return {"ok": None, "skipped": err}
    tick = proj["ppq"] * 4
    want = {(int(n["pitch"]), int(round(float(n["time_bars"]) * tick))) for n in notes}
    got = (proj["patterns"].get(pattern) or {}).get("notes", [])
    on_target = {(n["key"], n["position"]) for n in got if n["channel"] == channel}
    found = len(want & on_target)
    elsewhere = {}
    for n in got:
        if n["channel"] != channel and (n["key"], n["position"]) in want:
            elsewhere[n["channel"]] = elsewhere.get(n["channel"], 0) + 1
    out = {"ok": found == len(want), "pattern": pattern, "channel": channel,
           "expected": len(want), "found": found, "file": proj["path"]}
    if mode == "replace":
        out["extra_on_target"] = len(on_target - want)
    if elsewhere:
        out["misplaced_on"] = elsewhere
    return out


def targeted_apply(call, notes, mode="replace", trigger=True, quantize=None,
                   snap_ends=False, channel=None, verify=True):
    """prepare_target + apply_notes (+ save/read verification when a channel
    is given): refuse to write when the target isn't selected, and report
    where the notes actually landed."""
    info = {}
    if trigger:
        ok, info = prepare_target(call, channel)
        if not ok:
            return {"ok": False, "triggered": False, **info}
    res = apply_notes(notes, mode, trigger=trigger, quantize=quantize, snap_ends=snap_ends)
    if isinstance(res, dict):
        res.update(info)
        pattern = (info.get("piano_roll") or {}).get("pattern")
        if verify and trigger and channel is not None and quantize is None and notes and pattern:
            try:
                res["verify"] = verify_write(call, notes, int(channel), pattern, mode)
            except Exception as e:
                res["verify"] = {"ok": None, "skipped": "%s: %s" % (type(e).__name__, e)}
            if res["verify"].get("ok") is False:
                res["ok"] = False
    return res


def apply_notes(notes, mode="replace", trigger=True, quantize=None, snap_ends=False):
    """Write a pyscript into MCP_Apply.pyscript and (optionally) trigger FL.

    Normally writes the given notes. If ``quantize`` (grid in bars) is set, writes
    a script that instead reads the score and snaps existing notes to that grid.
    Returns {ok, ..., script, triggered, focused, hint?}.
    """
    if quantize is not None:
        path = write_quantize_script(float(quantize), snap_ends)
        result = {"ok": True, "action": "quantize", "grid_bars": float(quantize),
                  "snap_ends": bool(snap_ends), "script": path}
    else:
        path = write_apply_script(notes, mode)
        result = {"ok": True, "count": len(notes), "script": path, "mode": mode}

    if not trigger:
        result["triggered"] = False
        return result

    try:
        from .pyscript_trigger import trigger_run_last_script
        trig = trigger_run_last_script()
        shortcut = trig.get("shortcut", "Ctrl+Alt+Y")
        result["triggered"] = bool(trig.get("sent_hotkey", True))
        result["focused"] = trig.get("focused", False)
        if trig.get("error"):
            result["error"] = trig["error"]
        # The trigger can't confirm the script actually ran. The Piano roll is
        # auto-opened by the caller, but the shortcut only fires OUR script if
        # MCP_Apply was run once this FL session (no API to arm it). So if notes
        # don't appear, that one-time arm is the cause.
        result["setup"] = ("If notes did not appear: run 'MCP Apply' ONCE from the "
                           "Piano roll Scripting menu this FL session (the only "
                           "manual step -- arms the shortcut; no FL API to automate it).")
        if not result["triggered"]:
            result["hint"] = (
                "Notes written but auto-trigger is unsupported here. Click "
                f"the FL Piano roll and press {shortcut} to apply."
            )
        elif not trig.get("focused"):
            result["hint"] = (
                "Could not focus FL automatically -- click the FL Piano roll "
                f"and press {shortcut}."
            )
    except Exception as e:
        # Script is written regardless; trigger is best-effort.
        result["triggered"] = False
        result["error"] = f"{type(e).__name__}: {e}"
        result["hint"] = (
            f"Notes written but auto-trigger failed ({e}). Click the FL Piano "
            "roll and press the run-last-script shortcut to apply."
        )
    return result

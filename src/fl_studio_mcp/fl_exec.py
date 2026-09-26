"""Run Python inside FL Studio through the controller's `exec` command.

The code runs in FL's own interpreter with every FL module imported
(channels, mixer, patterns, playlist, plugins, transport, ui, arrangement,
general, midi, device, utils). Assign to ``result`` to return a value;
``log(...)`` collects lines. The namespace persists between calls.
Long code is sent in pieces and long results are paged, so neither side
runs into FL's ~1 KB SysEx limit.
"""
from __future__ import annotations

import json
from typing import Any

_CODE_CHUNK = 600
_PAGE = 250         # result chars per reply; JSON escaping can double it on the wire


def run(bridge, code: str, timeout: float = 30.0) -> Any:
    pieces = [code[i:i + _CODE_CHUNK] for i in range(0, len(code), _CODE_CHUNK)] or [""]
    for n, piece in enumerate(pieces[:-1]):
        bridge.call("exec", {"code": piece, "run": False, "reset_code": n == 0}, timeout=timeout)
    r = bridge.call("exec", {"code": pieces[-1], "run": True, "reset_code": len(pieces) == 1,
                             "page": _PAGE}, timeout=timeout)
    buf, total = r["chunk"], r["total"]
    while len(buf) < total:
        for attempt in range(4):             # a lost SysEx reply just gets re-requested
            try:
                buf += bridge.call("exec_fetch", {"offset": len(buf), "page": _PAGE}, timeout=5.0)["chunk"]
                break
            except Exception:
                if attempt == 3:
                    raise
    return json.loads(buf)


def main() -> None:
    """CLI: fl-exec FILE.py  (or '-' for stdin)."""
    import sys
    from .connection import TCPBridge
    src = sys.stdin.read() if len(sys.argv) < 2 or sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8").read()
    out = run(TCPBridge(), src)
    print(json.dumps(out, indent=1))
    sys.exit(0 if out.get("ok") else 1)


if __name__ == "__main__":
    main()

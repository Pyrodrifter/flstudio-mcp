"""fl_exec -- run arbitrary Python inside FL Studio (the full scripting API)."""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import fl_exec
from ..connection import get_bridge


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={"title": "Run Python inside FL Studio", "readOnlyHint": False,
                           "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
    def fl_exec(
        code: Annotated[str, Field(description="Python run in FL's interpreter. FL modules (channels, mixer, "
                                               "patterns, playlist, plugins, transport, ui, arrangement, general, "
                                               "midi, device, utils) are pre-imported. Assign `result` to return "
                                               "JSON-able data; log(...) collects lines. Globals persist between calls.")],
        timeout: Annotated[float, Field(ge=1, le=120)] = 30.0,
    ) -> dict:
        """Escape hatch for anything the dedicated tools don't cover: any FL
        scripting-API call (plugin params, pattern creation, playlist tracks,
        performance clips, mixer routing, ...). Returns {ok, result, log} or
        {ok: false, error}."""
        return fl_exec.run(get_bridge(), code, timeout)

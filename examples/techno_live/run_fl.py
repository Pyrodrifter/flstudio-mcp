"""Host side: run a file inside FL with PATTERNS / ROWS from compose.py injected."""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from fl_studio_mcp import fl_exec
from fl_studio_mcp.connection import TCPBridge
import compose

pats, _clips = compose.build()
head = "PATTERNS = %s\nROWS = %s\n" % (
    json.dumps({k: [p["name"], p["color"]] for k, p in pats.items()}),
    json.dumps([[r[0], r[1]] for r in compose.ROWS]))
code = head + open(sys.argv[1], encoding="utf-8").read()
out = fl_exec.run(TCPBridge(), code, timeout=float(sys.argv[2]) if len(sys.argv) > 2 else 90)
print(json.dumps(out, indent=1)[:3000])

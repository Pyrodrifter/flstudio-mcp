"""Host side: turn the saved project into the finished performance set.

    notes (flp_notes) -> clip grid (flp_writer) -> blocks + Start marker +
    launch settings (flp_performance) -> presets + mixer FX (flp_plugins)

Writes '<project> - Live.flp' next to the source; the source is never touched.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

from fl_studio_mcp import flp_notes, flp_performance, flp_plugins, flp_reader, flp_writer  # noqa: E402
import compose  # noqa: E402

SRC = sys.argv[1]
DST = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(SRC)[0] + " - Live.flp"
GEN = r"C:\Program Files\Image-Line\FL Studio 2026\Data\Patches\Plugin presets\Generators"
FX = r"C:\Program Files\Image-Line\FL Studio 2026\Data\Patches\Plugin presets\Effects"

CHANNEL_PRESETS = {
    compose.ACID: GEN + r"\Harmor\X Olbaid\Lead\Lead Acido.fst",
    compose.BASSLINE: GEN + r"\Harmor\X Olbaid\Bass\Bajo Techno.fst",
    compose.PAD: GEN + r"\Harmless\X Olbaid\Pad\Pad Ether.fst",
    compose.ARP: GEN + r"\Sakura\Sonic Haiku Bank\SY Tech Pizz (Mod Filter).fst",
    compose.PERC: GEN + r"\Sakura\Sonic Haiku Bank\PRC Metallic Bongo.fst",
}
MIXER_FX = [  # (insert, slot, preset)
    (0, 0, FX + r"\Fruity Filter\Default.fst"),                       # DJ filter for the Force knobs
    (1, 0, FX + r"\Fruity Parametric EQ 2\Kick.fst"),
    (3, 0, FX + r"\Fruity Parametric EQ 2\Quick Low Roll-Off.fst"),
    (6, 0, FX + r"\Fruity Blood Overdrive\Drive.fst"),
    (7, 0, FX + r"\Fruity Blood Overdrive\Boost.fst"),
    (8, 0, FX + r"\Fruity Delay 3\Tape.fst"),                         # dub-techno chords
    (9, 0, FX + r"\Vintage Chorus\Juno 6 Mode I.fst"),
    (10, 0, FX + r"\Fruity Phaser\Tech Wash.fst"),
    (12, 0, FX + r"\Vintage Chorus\Retro Chorus MKI.fst"),
    (16, 0, FX + r"\LuxeVerb\Envelope\Duck Big Boomy Warehouse.fst"),
    (4, 0, FX + r"\Fruity Delay 3\Ping pong.fst"),                  # delay send (insert 17 is FL's "Current" track)
]

BLOCK_BARS = 4


def main():
    pats, clips = compose.build()
    tmp = [DST + ".%d.tmp" % i for i in range(4)]
    try:
        r1 = flp_notes.write_patterns(SRC, tmp[0], {k: p["notes"] for k, p in pats.items()})
        r2 = flp_writer.write_clips(tmp[0], tmp[1], 0, [
            {"pattern": p, "track": t, "bar": 1 + (b - 1) * BLOCK_BARS, "length_bars": BLOCK_BARS}
            for p, t, b in clips], replace=True)
        settings = {"motion": "stay", "press": "retrigger", "trigger_sync": "four_beats", "position_sync": "auto"}
        r3 = flp_performance.write(tmp[1], tmp[2], 0,
                                   [(1 + k * BLOCK_BARS, name) for k, name in enumerate(compose.BLOCKS)],
                                   1 + len(compose.BLOCKS) * BLOCK_BARS,
                                   {t: settings for t in range(1, len(compose.ROWS) + 1)})
        ok_presets = {}
        for ch, p in CHANNEL_PRESETS.items():
            try:
                flp_plugins.read_preset(p)
                ok_presets[ch] = p
            except Exception as e:
                print("skip preset", ch, e)
        ok_fx = []
        for ins, slot, p in MIXER_FX:
            try:
                flp_plugins.read_preset(p)
                ok_fx.append((ins, slot, p))
            except Exception as e:
                print("skip fx", ins, e)
        r4 = flp_plugins.apply(tmp[2], DST, ok_presets, ok_fx)
    finally:
        for t in tmp:
            if os.path.exists(t):
                os.remove(t)
    print(r1, r2, r3, r4, sep="\n")

    # Verify by reading the result back.
    proj = flp_reader.parse(DST)
    counts = {k: len(v["notes"]) for k, v in proj["patterns"].items()}
    bad = [k for k, p in pats.items() if counts.get(k) != len(p["notes"])]
    items = proj["arrangements"][0]["items"]
    perf = flp_performance.read(DST, 0, len(compose.ROWS))["arrangements"][0]
    print("patterns with wrong note count:", bad)
    print("clips:", len(items), "expected", len(clips))
    print("markers:", [(m["bar"], m["name"], m["type"]) for m in perf["markers"]])
    print("zone bars:", perf["performance_zone_bars"])
    print("tracks:", {t["track"]: (t["trigger_sync"], t["position_sync"]) for t in perf["tracks"][:3]}, "...")


if __name__ == "__main__":
    main()

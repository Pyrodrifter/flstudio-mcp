"""'Pyro Techno Live' -- a Performance Mode set, written as data.

Every clip is a 4-bar loop in A minor at 130 BPM, so any clip in a row can
follow any other and every row combines with every other. Rows are musical
roles (one clip plays per row at a time in Performance Mode, so variations of
a role never stack); columns are scenes.

Harmony for the parts that move: | Am | Am | F | G | (all parts that don't
move stay on A minor pentatonic, which sits over all four chords).
"""
from __future__ import annotations

PPQ = 96
STEP = PPQ // 4            # one 16th
BAR = 16                   # steps per bar
LOOP = 4 * BAR             # every pattern is 4 bars

# Channel rack (as set up in the project)
KICK, CLAP, HAT, SNARE, RUMBLE, ACID, BASSLINE, STABS, PAD, ARP, PERC, LEAD, DRONE, SUB, PULSE = range(15)

ROOTS = [0, 0, -4, -2]     # A A F G, as offsets from A
CHORDS = [                 # stab / pad voicings per bar
    [57, 60, 64, 67],      # Am7
    [57, 60, 64, 67],      # Am7
    [53, 57, 60, 64],      # Fmaj7
    [55, 59, 62, 64],      # G6
]
PAD_CHORDS = [
    [57, 60, 64, 67, 71],  # Am9
    [57, 60, 64, 67, 71],
    [53, 57, 60, 64, 67],  # Fmaj9
    [55, 59, 62, 64, 69],  # G6/9
]


def n(ch, step, key=60, length=0, vel=100, pan=64):
    """A note in 16th steps (length 0 = a step-sequencer step)."""
    return {"channel": ch, "position": int(round(step * STEP)), "length": int(round(length * STEP)),
            "key": key, "velocity": vel, "pan": pan}


def every_bar(fn):
    out = []
    for bar in range(4):
        out += fn(bar, bar * BAR)
    return out


def seq(ch, root, cells, length=1, accents=(), vel=92, acc=118, bars=4, follow=False, pitch_len=None):
    """Monophonic 16th sequence: ``cells`` is one or more bars of offsets
    (None = rest), repeated to fill ``bars``."""
    out = []
    total = bars * BAR
    for s in range(total):
        c = cells[s % len(cells)]
        if c is None:
            continue
        bar = s // BAR
        key = root + c + (ROOTS[bar] if follow else 0)
        ln = length
        if pitch_len:
            ln = pitch_len.get(s % len(cells), length)
        out.append(n(ch, s, key, ln, acc if (s % len(cells)) in accents else vel))
    return out


# ---------------------------------------------------------------- drums

def kick(variant):
    def base(bar, o):
        return [n(KICK, o + b, vel=118) for b in (0, 4, 8, 12)]
    if variant == "4x4":
        return every_bar(base)
    if variant == "drive":        # ghost kick before the next bar on bars 2 and 4
        return every_bar(lambda bar, o: base(bar, o) + ([n(KICK, o + 14, vel=70)] if bar in (1, 3) else []))
    if variant == "bounce":
        return every_bar(lambda bar, o: base(bar, o) + [n(KICK, o + 7, vel=62)] + ([n(KICK, o + 15, vel=66)] if bar == 3 else []))
    if variant == "broken":
        return every_bar(lambda bar, o: base(bar, o) if bar < 3 else
                         [n(KICK, o + s, vel=v) for s, v in ((0, 118), (3, 96), (6, 104), (10, 100), (12, 118))])
    if variant == "stomp":
        return every_bar(lambda bar, o: base(bar, o) + ([n(KICK, o + 13, vel=80), n(KICK, o + 14, vel=90), n(KICK, o + 15, vel=100)] if bar == 3 else []))
    if variant == "half":
        return every_bar(lambda bar, o: [n(KICK, o, vel=112), n(KICK, o + 8, vel=100)])
    raise KeyError(variant)


def rumble(variant):
    root = 33
    if variant == "16ths":
        return every_bar(lambda bar, o: [n(RUMBLE, o + b + k, root, 1, v) for b in (0, 4, 8, 12) for k, v in ((1, 72), (2, 96), (3, 78))])
    if variant == "offbeat":
        return every_bar(lambda bar, o: [n(RUMBLE, o + b + 2, root, 2, 100) for b in (0, 4, 8, 12)])
    if variant == "roll":
        return every_bar(lambda bar, o: [n(RUMBLE, o + b + k, root, 1, v) for b in (0, 4, 8, 12) for k, v in ((1, 80), (3, 96))])
    if variant == "follow":
        return every_bar(lambda bar, o: [n(RUMBLE, o + b + k, root + ROOTS[bar], 1, v) for b in (0, 4, 8, 12) for k, v in ((1, 72), (2, 96), (3, 78))])
    raise KeyError(variant)


def claps(variant):
    if variant == "2and4":
        return every_bar(lambda bar, o: [n(CLAP, o + 4, vel=108), n(CLAP, o + 12, vel=112)])
    if variant == "ghost":
        return every_bar(lambda bar, o: [n(CLAP, o + 4, vel=106), n(CLAP, o + 12, vel=110),
                                         n(SNARE, o + 7, vel=44), n(SNARE, o + 14, vel=52)])
    if variant == "offset":
        return every_bar(lambda bar, o: [n(CLAP, o + 4, vel=106), n(CLAP, o + 12, vel=110)]
                         + ([n(CLAP, o + 15, vel=82)] if bar in (1, 3) else []))
    if variant == "rollend":      # a one-beat snare flourish at the very end, nothing more
        return every_bar(lambda bar, o: [n(CLAP, o + 4, vel=106), n(CLAP, o + 12, vel=110)]
                         + ([n(SNARE, o + s, vel=v) for s, v in ((12, 60), (13, 72), (14, 86), (15, 100))] if bar == 3 else []))
    if variant == "sparse":
        return every_bar(lambda bar, o: [n(CLAP, o + 12, vel=100)])
    raise KeyError(variant)


def hats(variant):
    if variant == "offbeat":
        return every_bar(lambda bar, o: [n(HAT, o + s, vel=104) for s in (2, 6, 10, 14)])
    if variant == "16ths":
        return every_bar(lambda bar, o: [n(HAT, o + s, vel=(108 if s % 4 == 2 else 58 + (s % 3) * 8),
                                           pan=64 + (6 if s % 2 else -6)) for s in range(16)])
    if variant == "gallop":
        return every_bar(lambda bar, o: [n(HAT, o + s, vel=(106 if s % 4 == 2 else 70)) for s in (2, 3, 6, 7, 10, 11, 14, 15)])
    if variant == "shuffle":
        return every_bar(lambda bar, o: [n(HAT, o + s, vel=v) for s, v in ((2, 104), (6, 100), (7, 56), (10, 104), (14, 100), (15, 60))])
    if variant == "sparse":
        return every_bar(lambda bar, o: [n(HAT, o + s, vel=96) for s in ((2, 10) if bar < 3 else (2, 10, 14))])
    raise KeyError(variant)


def perc(variant):
    if variant == "poly3":        # dotted-8th cycle: a 3-against-4 loop that keeps rotating
        keys = [57, 64, 60]
        return [n(PERC, s, keys[(s // 3) % 3], 1, 92 if (s // 3) % 3 == 0 else 70) for s in range(0, LOOP, 3)]
    if variant == "call":
        return every_bar(lambda bar, o: [n(PERC, o + 3, 57, 1, 90), n(PERC, o + 6, 64, 1, 76),
                                         n(PERC, o + 11, 60, 1, 84)] + ([n(PERC, o + 14, 67, 1, 70)] if bar % 2 else []))
    if variant == "rolls":
        return every_bar(lambda bar, o: [n(SNARE, o + s, vel=v) for s, v in ((1, 30), (5, 36), (9, 30), (13, 40))]
                         + [n(PERC, o + s, 60, 1, 78) for s in (3, 10)])
    if variant == "toms":
        return every_bar(lambda bar, o: [n(PERC, o + s, k, 2, v) for s, k, v in ((2, 52, 88), (6, 55, 80), (9, 57, 84), (14, 52, 74))])
    raise KeyError(variant)


# ---------------------------------------------------------------- bass

def bass(variant):
    if variant == "sub_offbeat":
        return every_bar(lambda bar, o: [n(SUB, o + b + 2, 33, 2, 104) for b in (0, 4, 8, 12)])
    if variant == "sub_follow":
        return every_bar(lambda bar, o: [n(SUB, o + b + 2, 33 + ROOTS[bar], 2, 104) for b in (0, 4, 8, 12)])
    if variant == "sub_long":     # breakdown: whole notes
        return every_bar(lambda bar, o: [n(SUB, o, 33 + ROOTS[bar], 15, 96)])
    if variant == "rolling":      # classic rolling techno bass: skip the kick, play the 3 16ths after it
        return seq(BASSLINE, 45, [None, 0, 0, 0] * 3 + [None, 0, 12, 0], 1, accents=(2, 6, 10, 14), vel=84, acc=108, follow=True)
    if variant == "groove":
        return seq(BASSLINE, 45, [None, None, 0, 12, None, None, 0, None, None, None, 0, 7, None, 0, None, 3],
                   1, accents=(3, 11), vel=90, acc=112, follow=True)
    if variant == "pulse":
        return seq(PULSE, 45, [None, 0, None, 0, None, 0, None, 0, None, 0, None, 0, None, 0, 12, 0],
                   1, accents=(14,), vel=92, acc=110, follow=True)
    raise KeyError(variant)


# ---------------------------------------------------------------- synths

def acid(variant):
    A = 45
    if variant == "hypno":
        bar = [0, None, 12, 0, None, 0, 10, None, 0, 12, None, 7, 0, None, 3, 5]
        return seq(ACID, A, bar, 1, accents=(2, 6, 9, 13), pitch_len={3: 2, 11: 2})
    if variant == "squelch":
        bar = [0, 0, None, 0, 12, None, 0, None, 3, None, 0, 0, None, 15, 12, None]
        return seq(ACID, A, bar, 1, accents=(4, 8, 13), pitch_len={4: 2, 13: 2})
    if variant == "climb":
        two = [0, None, 3, None, 5, None, 7, None, 10, None, 12, None, 10, None, 7, None,
               0, 0, 12, 0, 0, 15, 0, 12, 0, 0, 10, 0, 7, 0, 5, 3]
        return seq(ACID, A, two, 1, accents=(2, 6, 10, 18, 21, 26))
    if variant == "minimal":
        bar = [None, None, 0, None, None, None, 12, None, None, None, 0, None, None, 0, None, None]
        return seq(ACID, A, bar, 2, accents=(6,))
    if variant == "call":
        two = [0, 12, 0, None, 0, 12, 0, None, 7, None, 5, None, 3, None, None, None,
               0, None, None, None, None, None, None, None, None, None, 0, None, 0, None, 12, 10]
        return seq(ACID, A, two, 1, accents=(1, 5, 30))
    raise KeyError(variant)


def stabs(variant):
    def chord(bar, step, length, vel):
        return [n(STABS, step, k, length, vel) for k in CHORDS[bar]]
    if variant == "dub":
        return every_bar(lambda bar, o: chord(bar, o + 3, 2, 96) + chord(bar, o + 10, 2, 84))
    if variant == "offbeats":
        return every_bar(lambda bar, o: [x for s in (2, 6, 10, 14) for x in chord(0, o + s, 1, 100 if s in (6, 14) else 86)])
    if variant == "syncop":
        return every_bar(lambda bar, o: [x for s in (3, 6, 11, 14) for x in chord(bar, o + s, 1, 94)])
    if variant == "sparse":
        return every_bar(lambda bar, o: chord(bar, o + 14, 2, 100))
    raise KeyError(variant)


def arp(variant):
    if variant == "up":
        def f(bar, o):
            tones = CHORDS[bar] + [CHORDS[bar][0] + 12]
            return [n(ARP, o + s, tones[s % 5], 1, 100 if s % 4 == 0 else 78) for s in range(16)]
        return every_bar(f)
    if variant == "threes":
        cyc = [69, 72, 76]
        return [n(ARP, s, cyc[s % 3], 1, 96 if s % 3 == 0 else 74) for s in range(LOOP)]
    if variant == "octaves":
        return every_bar(lambda bar, o: [n(ARP, o + s, 57 + ROOTS[bar] + (12 if s % 2 else 0) + (7 if s % 8 == 6 else 0), 1,
                                           98 if s % 2 else 72) for s in range(16)])
    if variant == "sparkle":
        pat = [(0, 81), (3, 76), (6, 84), (10, 79), (12, 76), (14, 72)]
        return every_bar(lambda bar, o: [n(ARP, o + s, k, 2, 80) for s, k in pat])
    if variant == "down":
        def f(bar, o):
            tones = list(reversed(CHORDS[bar] + [CHORDS[bar][0] + 12]))
            return [n(ARP, o + s, tones[s % 5] + 12, 1, 96 if s % 4 == 0 else 72) for s in range(0, 16)]
        return every_bar(f)
    raise KeyError(variant)


def lead(variant):
    if variant == "riff":         # one-bar hypnotic riff
        cells = [(0, 76, 2), (2, 81, 2), (4, 84, 2), (6, 81, 1), (7, 79, 1), (10, 76, 2), (13, 74, 1), (14, 76, 2)]
        return every_bar(lambda bar, o: [n(LEAD, o + s, k, ln, 92) for s, k, ln in cells])
    if variant == "call":         # long notes, one phrase over the 4 chords
        notes = [(0, 76, 6), (6, 79, 2), (8, 76, 8), (16, 72, 14), (32, 72, 6), (38, 76, 2), (40, 77, 8),
                 (48, 74, 10), (58, 76, 6)]
        return [n(LEAD, s, k, ln, 90) for s, k, ln in notes]
    if variant == "stutter":
        return every_bar(lambda bar, o: [n(LEAD, o + s, 88 if s != 14 else 86, 1, 96 if s % 4 == 0 else 70)
                                         for s in (0, 2, 3, 6, 8, 10, 11, 14)])
    if variant == "answer":
        cells = [(0, 76, 2), (2, 81, 2), (4, 84, 2), (6, 81, 1), (7, 79, 1), (10, 76, 2)]
        tail = [[(13, 74, 1), (14, 76, 2)], [(13, 79, 1), (14, 81, 2)], [(13, 77, 1), (14, 76, 2)], [(12, 74, 2), (14, 71, 2)]]
        return every_bar(lambda bar, o: [n(LEAD, o + s, k, ln, 92) for s, k, ln in cells + tail[bar]])
    raise KeyError(variant)


def pad(variant):
    if variant == "chords":
        return every_bar(lambda bar, o: [n(PAD, o, k, 16, 84) for k in PAD_CHORDS[bar]])
    if variant == "static":
        return [n(PAD, s, k, 32, 80) for s in (0, 32) for k in (57, 64, 67, 71, 72)]
    if variant == "low":
        return every_bar(lambda bar, o: [n(PAD, o, k - 12, 16, 84) for k in CHORDS[bar]])
    if variant == "pulse":        # 8th-note gated chords
        return every_bar(lambda bar, o: [n(PAD, o + s, k, 1, 76 if s % 4 else 88) for s in range(0, 16, 2) for k in PAD_CHORDS[bar]])
    raise KeyError(variant)


def drone(variant):
    if variant == "root":
        return [n(DRONE, 0, k, 64, 80) for k in (45, 52)]
    if variant == "fifths":
        return every_bar(lambda bar, o: [n(DRONE, o, 45 + ROOTS[bar] + d, 16, 78) for d in (0, 7)])
    if variant == "high":
        return [n(DRONE, 0, k, 64, 70) for k in (69, 76, 81)]
    raise KeyError(variant)


# ---------------------------------------------------------------- the set

# (row name, colour, [(variant label, notes)])
ROWS = [
    ("Kick", 0xE63946, [("4x4", kick("4x4")), ("Drive", kick("drive")), ("Bounce", kick("bounce")),
                        ("Broken", kick("broken")), ("Stomp", kick("stomp")), ("Half", kick("half"))]),
    ("Rumble", 0x9D0208, [("16ths", rumble("16ths")), ("Offbeat", rumble("offbeat")), ("Roll", rumble("roll")),
                          ("Follow", rumble("follow"))]),
    ("Clap", 0xF4A261, [("2 & 4", claps("2and4")), ("Ghost", claps("ghost")), ("Offset", claps("offset")),
                        ("Roll End", claps("rollend")), ("Sparse", claps("sparse"))]),
    ("Hats", 0xE9C46A, [("Offbeat", hats("offbeat")), ("16ths", hats("16ths")), ("Gallop", hats("gallop")),
                        ("Shuffle", hats("shuffle")), ("Sparse", hats("sparse"))]),
    ("Perc", 0xFFB703, [("Poly 3", perc("poly3")), ("Call", perc("call")), ("Rolls", perc("rolls")),
                        ("Toms", perc("toms"))]),
    ("Bass", 0x7B2CBF, [("Sub Off", bass("sub_offbeat")), ("Sub Follow", bass("sub_follow")),
                        ("Rolling", bass("rolling")), ("Groove", bass("groove")), ("Pulse", bass("pulse")),
                        ("Sub Long", bass("sub_long"))]),
    ("Acid", 0x2DC653, [("Hypno", acid("hypno")), ("Squelch", acid("squelch")), ("Climb", acid("climb")),
                        ("Minimal", acid("minimal")), ("Call", acid("call"))]),
    ("Stabs", 0x00B4D8, [("Dub", stabs("dub")), ("Offbeats", stabs("offbeats")), ("Syncop", stabs("syncop")),
                         ("Sparse", stabs("sparse"))]),
    ("Arp", 0x4361EE, [("Up", arp("up")), ("Threes", arp("threes")), ("Octaves", arp("octaves")),
                       ("Sparkle", arp("sparkle")), ("Down", arp("down"))]),
    ("Lead", 0xF72585, [("Riff", lead("riff")), ("Call", lead("call")), ("Stutter", lead("stutter")),
                        ("Answer", lead("answer"))]),
    ("Pad", 0x48CAE4, [("Chords", pad("chords")), ("Static", pad("static")), ("Low", pad("low")),
                       ("Pulse", pad("pulse"))]),
    ("Drone", 0x6A4C93, [("Root", drone("root")), ("Fifths", drone("fifths")), ("High", drone("high"))]),
]

BLOCKS = ["Warm Up", "Groove", "Hypnotic", "Acid", "Deep", "Peak", "Breakdown", "Afterhours"]

# Scene layout: for each row, the variant (1-based) in each block, 0 = empty.
SCENES = {
    #            WarmUp Groove Hypno Acid Deep Peak Break After
    "Kick":    [1, 2, 1, 3, 4, 5, 6, 2],
    "Rumble":  [2, 1, 3, 1, 4, 1, 0, 2],
    "Clap":    [0, 1, 2, 1, 5, 4, 5, 3],
    "Hats":    [5, 1, 2, 3, 4, 2, 5, 4],
    "Perc":    [2, 1, 1, 3, 4, 3, 2, 1],
    "Bass":    [1, 2, 3, 4, 5, 3, 6, 1],
    "Acid":    [0, 0, 4, 1, 2, 3, 4, 5],
    "Stabs":   [4, 1, 0, 3, 1, 2, 0, 4],
    "Arp":     [0, 3, 2, 0, 1, 5, 4, 2],
    "Lead":    [0, 0, 1, 3, 0, 4, 2, 1],
    "Pad":     [2, 1, 0, 0, 3, 1, 1, 4],
    "Drone":   [1, 2, 1, 2, 3, 2, 3, 1],
}


def build():
    """-> patterns {num: {name, color, notes}}, clips [(pattern, track, block)]"""
    pats, index = {}, {}
    num = 1
    for row, color, variants in ROWS:
        for v, (label, notes) in enumerate(variants, 1):
            pats[num] = {"name": "%s - %s" % (row, label), "color": color, "notes": notes, "row": row}
            index[(row, v)] = num
            num += 1
    clips = []
    for track, (row, _c, _v) in enumerate(ROWS, 1):
        for block, v in enumerate(SCENES[row], 1):
            if v:
                clips.append((index[(row, v)], track, block))
    return pats, clips


if __name__ == "__main__":
    pats, clips = build()
    print(len(pats), "patterns,", sum(len(p["notes"]) for p in pats.values()), "notes,", len(clips), "clips")
    for k, p in pats.items():
        end = max(x["position"] + x["length"] for x in p["notes"]) / (PPQ * 4)
        print(k, p["name"], len(p["notes"]), "notes, ends bar %.2f" % end)

# Runs INSIDE FL: sculpt the plugins whose presets can't be loaded from files.
out = {}

LEAD, DRONE, SUB, PULSE = 11, 12, 13, 14
S = {
    LEAD: [("Env Amp Attack", 0.002), ("Env Amp Decay", 0.35), ("Env Amp Sustain", 0.30), ("Env Amp Release", 0.25),
           ("F1 Cutoff", 2400), ("F1 Resonance", 0.30), ("Analog 1 O2 Volume", -4), ("Analog 1 O2 Fine", 0.08),
           ("Master Volume", -9)],
    DRONE: [("Env Amp Attack", 1.5), ("Env Amp Decay", 1.0), ("Env Amp Sustain", 1.0), ("Env Amp Release", 3.0),
            ("F1 Cutoff", 900), ("F1 Resonance", 0.15), ("Analog 1 O2 Volume", -3), ("Analog 1 O2 Fine", 0.12),
            ("Analog 1 O3 Volume", -8), ("Analog 1 O3 Coarse", -12), ("Master Volume", -11)],
    SUB: [("Harmonics Level", -24), ("Sub Level", -3), ("Amp Envelope Release", 0.06), ("Output Level", -4)],
    PULSE: [("Harmonics Level", 0), ("Morph", 45), ("Detune", 20), ("Filter Cutoff", 1500), ("Filter Resonance", 0.3),
            ("Amp Envelope Decay", 0.18), ("Amp Envelope Sustain", 0.2), ("Amp Envelope Release", 0.08),
            ("Output Level", -6)],
}
for ch, items in S.items():
    got = []
    for name, v in items:
        try:
            got.append("%s=%s" % (name, set_num(ch, name, v, settle=0.12)))
        except Exception as e:
            got.append("%s!%s" % (name, e))
    out[ch] = got
result = out

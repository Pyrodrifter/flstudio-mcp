# Runs INSIDE FL after fl_helpers.py. Channel rack, mixer, patterns, playlist
# tracks. PATTERNS and ROWS are injected by the host script as JSON literals.
log_ = []

CHANNELS = [  # name, colour, mixer insert, volume (0..1, 0.78 = 0 dB-ish)
    ("Kick", 0xE63946, 1, 0.80), ("Clap", 0xF4A261, 2, 0.66), ("Hat", 0xE9C46A, 3, 0.58),
    ("Snare", 0xF77F00, 4, 0.60), ("Rumble 808", 0x9D0208, 5, 0.62), ("Acid", 0x2DC653, 6, 0.64),
    ("Bassline", 0x7B2CBF, 7, 0.70), ("Stabs", 0x00B4D8, 8, 0.62), ("Pad", 0x48CAE4, 9, 0.60),
    ("Arp", 0x4361EE, 10, 0.60), ("Perc", 0xFFB703, 11, 0.62), ("Lead", 0xF72585, 12, 0.66),
    ("Drone", 0x6A4C93, 13, 0.56), ("Sub", 0x5A189A, 14, 0.74), ("Pulse Bass", 0x9B5DE5, 15, 0.64),
]
for ch, (name, col, ins, vol) in enumerate(CHANNELS):
    channels.setChannelName(ch, name)
    channels.setChannelColor(ch, rgb(col))
    channels.setTargetFxTrack(ch, ins)
    channels.setChannelVolume(ch, vol)
    mixer.setTrackName(ins, name)
    mixer.setTrackColor(ins, rgb(col))

# Send buses
mixer.setTrackName(16, "Reverb Send"); mixer.setTrackColor(16, rgb(0x8ECAE6))
mixer.setTrackName(17, "Delay Send"); mixer.setTrackColor(17, rgb(0x219EBC))
SENDS = {16: {4: 0.15, 6: 0.25, 8: 0.35, 9: 0.40, 10: 0.30, 11: 0.25, 12: 0.30, 13: 0.45, 2: 0.12},
         17: {6: 0.20, 8: 0.35, 10: 0.25, 12: 0.30, 11: 0.15}}
for bus, srcs in SENDS.items():
    for src, lvl in srcs.items():
        mixer.setRouteTo(src, bus, True)
        mixer.setRouteToLevel(src, bus, lvl)
mixer.afterRoutingChanged()

# Mixer levels (0.8 = 0 dB)
for ins, v in {1: 0.80, 2: 0.72, 3: 0.66, 4: 0.64, 5: 0.70, 6: 0.70, 7: 0.74, 8: 0.66, 9: 0.62,
               10: 0.64, 11: 0.66, 12: 0.68, 13: 0.60, 14: 0.78, 15: 0.70, 16: 0.66, 17: 0.62}.items():
    mixer.setTrackVolume(ins, v)

# Swing / tempo
mixer.setCurrentTempo(130000) if hasattr(mixer, "setCurrentTempo") else None

# Patterns: name, colour, fixed 4-bar length
for num, (name, col) in PATTERNS.items():
    num = int(num)
    patterns.jumpToPattern(num)
    patterns.setPatternName(num, name)
    patterns.setPatternColor(num, rgb(col))
    patterns.setPatternLength(num, 64)          # 16th steps (FL 26.1)
patterns.jumpToPattern(1)

# Playlist tracks = performance rows
for t, (name, col) in enumerate(ROWS, 1):
    playlist.setTrackName(t, name)
    playlist.setTrackColor(t, rgb(col))

result = {"channels": channels.channelCount(), "patterns": patterns.patternCount(),
          "lens": [patterns.getPatternLength(k) for k in (1, 30, 55)]}

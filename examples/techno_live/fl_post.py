# Runs INSIDE FL after opening the built set (needs fl_helpers.py first).
# Everything here is stored in the project once saved.
out = {}
def setp(t, s, name, v):
    k = param_index(t, name, s); plugins.setParamValue(v, k, t, s); return plugins.getParamValueString(k, t, s)

# -- mixer layout: Snare shares the Clap insert, insert 4 becomes the delay send
channels.setTargetFxTrack(3, 2)
mixer.setTrackName(2, "Clap / Snare")
mixer.setTrackName(4, "Delay Send"); mixer.setTrackColor(4, rgb(0x219EBC))
channels.setChannelName(4, "Rumble 808")
for src, lvl in {6: 0.20, 8: 0.35, 10: 0.25, 12: 0.30, 11: 0.15}.items():
    mixer.setRouteTo(src, 4, True)
    mixer.setRouteToLevel(src, 4, lvl)
for src, lvl in {2: 0.12, 6: 0.25, 8: 0.35, 9: 0.40, 10: 0.30, 11: 0.25, 12: 0.30, 13: 0.45}.items():
    mixer.setRouteTo(src, 16, True)
    mixer.setRouteToLevel(src, 16, lvl)
mixer.afterRoutingChanged()
for t, v in {0: 0.74, 1: 0.80, 2: 0.72, 3: 0.66, 4: 0.62, 5: 0.68, 6: 0.60, 7: 0.64, 8: 0.62, 9: 0.62,
             10: 0.64, 11: 0.66, 12: 0.68, 13: 0.58, 14: 0.78, 15: 0.70, 16: 0.66}.items():
    mixer.setTrackVolume(t, v)

# -- send effects
out["verb"] = [setp(16, 0, "Output dry level", 0.0), set_num(16, "Output wet level", 1.5, 0, settle=0.05),
               setp(16, 0, "Feedforward amp 1", 0.0), setp(16, 0, "Feedforward amp 2", 0.0),
               set_num(16, "Feedforward unpitched", 100, 0, settle=0.05), set_num(16, "Reverb decay", 3.2, 0, settle=0.05),
               set_num(16, "Input low cut", 180, 0, settle=0.05)]
k = param_index(4, "Output dry", 0); plugins.setParamValue(0.0, k, 4, 0)
k = param_index(4, "Feedback level", 0); plugins.setParamValue(0.36, k, 4, 0)      # ~45 %
k = param_index(4, "Output wet", 0); plugins.setParamValue(0.85, k, 4, 0)
# dub tape delay on the stabs insert
k = param_index(8, "Feedback level", 0); plugins.setParamValue(0.416, k, 8, 0)      # 52 %
k = param_index(8, "Output wet", 0); plugins.setParamValue(0.45, k, 8, 0)
# master DJ filter: plain low-pass, wide open
setp(0, 0, "High pass", 0.0); setp(0, 0, "Cutoff frequency", 1.0)

# -- Pigments: wavetable towards saw + unison
for ch, pos, voices, det in ((11, 0.66, 3, 12), (12, 0.45, 5, 18)):
    setp(ch, -1, "Wavetable 1 Position", pos)
    out[ch] = [set_num(ch, "Wavetable 1 Unison Voices", voices, settle=0.12),
               set_num(ch, "Wavetable 1 Unison Detune", det, settle=0.12)]
result = out

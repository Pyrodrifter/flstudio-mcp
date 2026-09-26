# Pyro Techno Live — a Performance Mode set built from code

Turns a project with 15 channels (4 drum samples, FLEX, 2× Harmor, 2× Harmless,
2× Sakura, 2× Pigments, 2× Pure SUB) into a complete techno live set at 130 BPM
in A minor, using only the MCP's tools:

| step | how | file |
|---|---|---|
| names, colours, routing, sends, pattern names/lengths, playlist rows | `fl_exec` (live API) | `fl_setup.py` |
| Pigments / Pure SUB sound design | `fl_exec`, parameter search by displayed value | `fl_sound.py` |
| 55 patterns / 1 618 notes | `flp_notes` | `compose.py` |
| 83-clip grid, 8 block markers + Start, launch sync | `flp_writer`, `flp_performance` | `build.py` |
| Harmor / Harmless / Sakura presets, 11 mixer effects | `flp_plugins` | `build.py` |
| effect settings, delay/reverb sends, levels | `fl_exec` | `fl_post.py` |

```
fl-exec fl_helpers.py                  # helper functions inside FL
python run_fl.py fl_setup.py           # live setup
python run_fl.py fl_sound.py 300       # synth sound design
# save in FL, then:
python build.py "<project>.flp"        # -> "<project> - Live.flp"
# open it in FL, then:
fl-exec fl_helpers.py && fl-exec fl_post.py
```

## Playing it

Rows (playlist tracks) are roles; only one clip per row plays at a time, so
variations never stack. Every clip is a 4-bar loop and launches on the next
bar with its position kept in phase with the others, so anything goes with
anything.

| row | variations |
|---|---|
| Kick | 4x4, Drive, Bounce, Broken, Stomp, Half |
| Rumble | 16ths, Offbeat, Roll, Follow |
| Clap | 2 & 4, Ghost, Offset, Roll End, Sparse |
| Hats | Offbeat, 16ths, Gallop, Shuffle, Sparse |
| Perc | Poly 3, Call, Rolls, Toms |
| Bass | Sub Off, Sub Follow, Rolling, Groove, Pulse, Sub Long |
| Acid | Hypno, Squelch, Climb, Minimal, Call |
| Stabs | Dub, Offbeats, Syncop, Sparse |
| Arp | Up, Threes, Octaves, Sparkle, Down |
| Lead | Riff, Call, Stutter, Answer |
| Pad | Chords, Static, Low, Pulse |
| Drone | Root, Fifths, High |

Scenes (columns): Warm Up → Groove → Hypnotic → Acid → Deep → Peak →
Breakdown → Afterhours. The master has a Fruity Filter first in the chain for
DJ-style sweeps.

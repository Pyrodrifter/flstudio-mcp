# Runs INSIDE FL (via fl_exec). Defines helpers in the persistent namespace.
import re


def rgb(c):
    return utils.RGBToColor((c >> 16) & 255, (c >> 8) & 255, c & 255) if utils else c


def _num(s):
    """'1.50 ms' -> 0.0015, '2.4 kHz' -> 2400, '-6.00 dB' -> -6.0, '50.0 %' -> 50.0"""
    m = re.search(r"-?\d+(\.\d+)?", s or "")
    if not m:
        return None
    v = float(m.group(0))
    u = s[m.end():].strip().lower()
    if u.startswith("ms"):
        v /= 1000.0
    elif u.startswith("khz"):
        v *= 1000.0
    return v


def param_index(ch, name, slot=-1):
    for k in range(plugins.getParamCount(ch, slot)):
        if plugins.getParamName(k, ch, slot) == name:
            return k
    raise KeyError("%s: no param %r" % (plugins.getPluginName(ch, slot), name))


def set_num(ch, name, target, slot=-1, tol=0.01, settle=0.0):
    """Bisect the 0..1 value until the displayed number reaches ``target``
    (seconds, Hz, dB, %, plain). Assumes a rising display."""
    k = param_index(ch, name, slot)
    lo, hi = 0.0, 1.0
    for _ in range(18):
        mid = (lo + hi) / 2
        plugins.setParamValue(mid, k, ch, slot)
        if settle:
            time.sleep(settle)          # VSTs update their display text asynchronously
        v = _num(plugins.getParamValueString(k, ch, slot))
        if v is None:
            break
        if abs(v - target) <= tol * max(1.0, abs(target)):
            break
        if v < target:
            lo = mid
        else:
            hi = mid
    return plugins.getParamValueString(k, ch, slot)


def set_enum(ch, name, label, slot=-1):
    k = param_index(ch, name, slot)
    for i in range(0, 201):
        plugins.setParamValue(i / 200.0, k, ch, slot)
        if plugins.getParamValueString(k, ch, slot).strip().lower() == label.lower():
            return label
    raise ValueError("%s: %r not found" % (name, label))


def preset_names(ch):
    return [plugins.getName(ch, -1, midi.FPN_Preset, k) for k in range(plugins.getPresetCount(ch))]


def current_preset(ch):
    channels.showEditor(ch, 1)
    cap = ui.getFocusedFormCaption() or ""
    return cap.split("")[0].strip()


def goto_preset(ch, name):
    names = preset_names(ch)
    want = names.index(name)
    cur = current_preset(ch)
    i = names.index(cur) if cur in names else -1
    steps = want - i
    for _ in range(abs(steps)):
        (plugins.nextPreset if steps > 0 else plugins.prevPreset)(ch)
    got = current_preset(ch)
    channels.showEditor(ch, 0)
    return got


result = "helpers ready"

"""Reliability gating of transcribed panel facts (knowledge_base/factnorm.py): synthetic readings only, no private data.

Rule (user 2026-11-13): values that are not reliable must not be used. Tier A = clean, B = minor doubt (never used for numbers), C = excluded.
Run: python -I tests/test_facts_reliability.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "knowledge_base"))
import factnorm as fn  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not ok:
        fails.append(name)


def rd(label="x", value=1.0, conf=0.95, note="", legible="yes"):
    return {"label": label, "value": value, "conf": conf, "note": note, "legible": legible}


# ---- label parsing
check("motor roles", fn.parse_label("34 samXE (110216) Readback (user)", "motor_rbv")[:3] == ("samxe", "samXE (110216)".replace(" (110216)", ""), "rbv_user")
      or fn.parse_label("34 samXE (110216) Readback (user)", "motor_rbv")[0] == "samxe")
check("compact window roles", fn.parse_label("36 samZE [compact] entry", "motor_setpoint")[2] == "setpoint"
      and fn.parse_label("36 samZE [compact] step", "motor_step")[2] == "step" and fn.parse_label("36 samZE [compact]", "motor_rbv")[2] == "rbv")
check("slit fields", fn.parse_label("W_Beam H SIZE", "slit_size")[2:3] == ("size_h",) and fn.parse_label("Kohzu_E_dn V CENTER", "slit_center")[2:3] == ("center_v",))
check("serials and spaces do not split a device", fn.parse_label("35 samYE  (102416) Tweak", "motor_step")[0] == fn.parse_label("35 samYE Tweak", "motor_step")[0] == "samye")
check("pv prefix -> hutch", fn.pv_hutch("1ide1:m34") == "E" and fn.pv_hutch("1ida:m30") == "A" and fn.pv_hutch("") == "")

# ---- reading-level flags
check("clean reading is tier A", fn.tier_of(fn.reading_flags(rd())) == "A")
check("conf 0.85 -> B", fn.tier_of(fn.reading_flags(rd(conf=0.85))) == "B")
check("conf 0.7 -> C", fn.tier_of(fn.reading_flags(rd(conf=0.7))) == "C")
check("null value -> C", fn.tier_of(fn.reading_flags(rd(value=None))) == "C")
check("'last digit cropped' -> B (not usable for numbers, not discarded as a guess)", fn.tier_of(fn.reading_flags(rd(note="last digit cropped"))) == "B")
for note in ("assumed limit", "inferred from the column order", "value differs from the log text", "label may be truncated on screen", "hidden by the text cursor",
             "entered from memory", "uncertain", "covered by a tooltip", "no printed label"):
    check(f"note '{note}' -> C", fn.tier_of(fn.reading_flags(rd(note=note))) == "C")
check("title-cropped label -> C (device unknown)", fn.tier_of(fn.reading_flags(rd(label="(title cropped, column 3)"))) == "C")
check("partial image + conf 0.95 -> B", fn.tier_of(fn.reading_flags(rd(legible="partial"))) == "B")
check("illegible image -> C", fn.tier_of(fn.reading_flags(rd(legible="no"))) == "C")


# ---- objective cross-checks inside one window
def win(rows):
    return [{"quantity": q, "value": v} for q, v in rows]


def flagged(rows):
    out = fn.group_checks(win(rows))
    return {i for i, f in out.items() if f}


pos = [("rbv_user", 1.0), ("rbv_dial", 2.0), ("drive_user", 1.0), ("drive_dial", 2.0), ("hi_user", 9.0), ("hi_dial", 10.0), ("lo_user", -9.0), ("lo_dial", -8.0)]
check("positive-direction motor, consistent -> nothing flagged", not flagged(pos))
neg = [("rbv_user", 0.65), ("rbv_dial", 1.35), ("drive_user", 0.65), ("drive_dial", 1.35), ("hi_user", 5.6), ("hi_dial", 10.0), ("lo_user", -8.0), ("lo_dial", -3.6)]
check("reversed-direction motor (dial = c - user, limits swapped) is NOT a false alarm", not flagged(neg))
bad = list(pos)
bad[1] = ("rbv_dial", 2.5)                                   # a misread digit in one readback
check("misread dial readback flagged by the offset check", flagged(bad) == {0, 1}, str(flagged(bad)))
sparse = [("rbv_user", 1.0), ("rbv_dial", 2.0), ("hi_dial", 10.0), ("lo_user", -9.0)]
check("too few redundant pairs -> nothing flagged (no false alarm)", not flagged(sparse))
out = fn.group_checks(win([("rbv_user", 5.0), ("hi_user", 3.0), ("lo_user", -3.0)]))
check("readback above its hi limit flagged", any("rbv>hi" in f for f in out.values()))
out = fn.group_checks(win([("hi_user", -3.0), ("lo_user", 3.0)]))
check("hi <= lo flagged", any("hi<=lo" in f for f in out.values()))
out = fn.group_checks(win([("size_h", -0.5)]))
check("negative slit size flagged", any("negative_size" in f for f in out.values()))

print("facts reliability OK" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)

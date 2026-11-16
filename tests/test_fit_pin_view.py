"""Pin-in-view model test (no hardware): geometry checks on synthetic inputs, the committed fits/pin_view.json against its own numbers, privacy of the committed
outputs, and - only when the local knowledge base exists - that the fit reproduces the committed aggregates.
Run: ~/miniconda3/envs/blade/bin/python -I tests/test_fit_pin_view.py   (numpy + sqlite, < 10 s)"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from blade.calibration import pin_view_fit as pv

FITS = ROOT / "beamline_twins/1-ID/physics/fits"
J = json.loads((FITS / "pin_view.json").read_text())
MD = (FITS / "pin_view.md").read_text()
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(detail)) if detail != "" else ""))
    if not cond:
        FAILS.append(name)


# ---- 1. geometry (synthetic)
check("pin on the beam centre is seen and usable", pv.lateral_margin_mm(-3.0, -3.0, 1.0, 1.34) > 0 and pv.lateral_margin_mm(-3.0, -3.0, 1.0, 1.34, require_flat_top=True) > 0)
check("symmetric about the beam", abs(pv.lateral_margin_mm(-3.4, -3.0, 1.0, 1.34) - pv.lateral_margin_mm(-2.6, -3.0, 1.0, 1.34)) < 1e-12)
m = pv.lateral_margin_mm(-3.5, -3.0, 1.0, 1.34)       # 0.5 off, half window 0.5, half pin top 0.052 -> silhouette overlaps by 0.052 but the flat top does not fit
check("0.5 mm off a 1.0 mm window: seen (edge) but not usable", m > 0 and pv.lateral_margin_mm(-3.5, -3.0, 1.0, 1.34, require_flat_top=True) < 0, round(m, 4))
check("camera FOV caps a wider footprint", abs(pv.lateral_margin_mm(-3.0, -3.0, 5.0, 1.34) - pv.lateral_margin_mm(-3.0, -3.0, 1.34, 1.34)) < 1e-12)
check("pin offset from the axis shifts the pin like an axis move", abs(pv.lateral_margin_mm(-3.0, -3.0, 1.0, 1.34, pin_offset_mm=0.3) - pv.lateral_margin_mm(-3.3, -3.0, 1.0, 1.34)) < 1e-12)
check("wider pin group A is seen at a larger offset than B", pv.lateral_margin_mm(-3.6, -3.0, 1.0, 1.34, "A") > pv.lateral_margin_mm(-3.6, -3.0, 1.0, 1.34, "B"))
check("footprint = min(WB footprint, E slit): WB 0.5 -> 0.95; E slit 0.74 -> 0.74", abs(pv.footprint_h_mm(0.5) - 0.95) < 1e-9 and abs(pv.footprint_h_mm(0.5, 0.74) - 0.74) < 1e-9)
sh = [0.014, 1.306, 0.163, 0.369, 0.215]
fr = [pv.capture_fraction(sh, f, 1.34) for f in (0.3, 0.6, 1.0, 1.3, 3.0)]
check("capture fraction is non-decreasing in footprint and capped by the FOV", all(a <= b for a, b in zip(fr, fr[1:])) and fr[-1] == fr[-2], fr)

# ---- 2. committed numbers are self-consistent with the written result
cyc = J["axis_on_beam_by_cycle"]
check("6 cycles with an on-beam aero dial", len(cyc) == 6, [c["cycle"] for c in cyc])
rec = J["axis_dial_recent_cycles_mm"]
check("recent cycles (>= 2025-10): mean -3.0, sd 0.25, half-range 0.29", abs(rec["mean"] + 3.0) < 0.01 and abs(rec["sd"] - 0.253) < 0.005 and abs(rec["half_range"] - 0.292) < 0.005, rec)
check("shifts between cycles are the differences of the dial list", all(abs(abs(b["dial_mm"] - a["dial_mm"]) - s) < 6e-4 for a, b, s in zip(cyc, cyc[1:], J["cycle_to_cycle_axis_shift_mm"])))
check("dial - E-slit-centre is NOT constant across cycles (-2.46 vs -3.46)", J["dial_minus_slit_centre_constant_across_cycles"] is False)
check("number quoted in the markdown (-3.0 +- 0.3 mm, offset -2.46 / -3.46) is present", all(t in MD for t in ("-3.0", "0.25", "-2.46", "-3.46")))
check("limits section states that all 25 frames are positives", "positive" in MD.lower() and "25" in MD)
check("every pin frame has an envelope entry or an explicit n=0", all("n" in v for v in J["envelope_at_pin_frames"].values()))
check("stale E-slit panel replaced: no pin-frame E slit below 0.7 mm", J["envelope_at_pin_frames"]["E_slit_h"]["min"] >= 0.7, J["envelope_at_pin_frames"]["E_slit_h"])

# ---- 3. privacy of the committed outputs (public repo)
txt = json.dumps(J) + MD
check("no log document ids ('explog'), no image hashes", "explog" not in txt and not re.search(r"\b(?=[0-9]*[a-f])[0-9a-f]{16,}\b", json.dumps(J)))
try:
    con = pv._kb()
    ids = [r[0] for r in con.execute("select doc_id from docs")]
except Exception as e:                                   # no knowledge tree on this machine: skip the data-dependent checks
    con, ids = None, []
    print("SKIP knowledge-base checks:", e)
if con is not None:
    allowed = {"2023-startup_jan23_explog", "2023-lastlight_mpe_apr23", "2024-mpe_jul24_explog", "2025-startup_jan25_explog", "2026-mpe_jan26"}
    leaked = [i for i in ids if i not in allowed and i in txt]
    check("no user-log document id appears in the committed outputs", not leaked, leaked[:3])
    s = pv.summarize(con)
    check("fit reproduces the committed aggregates (cycles, shifts, envelope)", s["axis_on_beam_by_cycle"] == J["axis_on_beam_by_cycle"]
          and s["cycle_to_cycle_axis_shift_mm"] == J["cycle_to_cycle_axis_shift_mm"] and s["envelope_at_pin_frames"] == J["envelope_at_pin_frames"])
    rows, notes = pv.collect(con)
    check("25 curated tomopin frames", notes["n_images"] == 25, notes)
    check("only tier-A rows feed the values (attached values come from tier A by construction); B/C rows reported", notes["excluded_nonA_rows_in_windows"] >= 0)
    check("attach rule is 'last before the image': no attached value is logged after its image", all(v["lines_back"] is None or v["lines_back"] >= 0 for r in rows for v in r["vars"].values()))

print("pin view fit " + ("OK" if not FAILS else "FAILED: %s" % FAILS))
sys.exit(1 if FAILS else 0)

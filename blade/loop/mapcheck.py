"""Evidence for the control<->PV mapping, from what the read-only probe already read. PROPOSES; never edits `control_pv_map.json` (a human verifies and edits).

A motor's soft limits (.LLM / .HLM, user frame) and the simulator's limits for the same control describe the same travel. If the widths agree, the offset (and the
sign, if the limits are mirrored) follows - that is evidence for `sim = scale * raw + offset`, not proof: two different motors can have equal travel. The output says
exactly that and lists what the person must still confirm (compare one live readback with the panel).

    python -m blade.loop.mapcheck pending/desc_probe_<UTC>.csv        # CSV written by beamline_twins/tools/probe_readonly.py --run"""
import csv
import sys
from pathlib import Path
from ..instrument import pvmap
from ..vbl.world import control_specs


def read_probe_csv(path):
    vals = {}
    for row in csv.DictReader(open(path)):
        if row.get("status") == "ok":
            vals[row["pv"]] = row["value"]
    return vals


def limits_evidence(probe_values, twin="1-ID", rel_tol=2e-3):
    """[{control, pv, real_limits, sim_limits, candidates:[{scale, offset, evidence}], ...}] for every listed mapping entry that has both limits in the probe."""
    specs = control_specs(twin)
    out = []
    for name, e in pvmap.load_controls(twin).items():
        try:
            llm, hlm = float(probe_values[f"{e.pv}.LLM"]), float(probe_values[f"{e.pv}.HLM"])
        except (KeyError, ValueError):
            out.append({"control": name, "pv": e.pv, "status": e.status, "note": "limits not in the probe data"})
            continue
        if name not in specs or specs[name][0] is None:
            continue
        lo, hi = specs[name][0], specs[name][1]
        w_real, w_sim = hlm - llm, hi - lo
        cands = []
        if w_real > 0 and abs(w_real - w_sim) <= rel_tol * max(w_sim, 1.0):
            cands.append({"scale": 1.0, "offset": round(lo - llm, 6), "evidence": f"travel {w_real:.4g} equals the simulator's {w_sim:.4g}; limits shifted by {lo - llm:+.4g}"})
        if w_real > 0 and abs(w_real - w_sim) <= rel_tol * max(w_sim, 1.0):
            cands.append({"scale": -1.0, "offset": round(lo + hlm, 6), "evidence": "same travel, mirrored axis (only if the sign is known to be opposite)"})
        out.append({"control": name, "pv": e.pv, "status": e.status, "real_limits": [llm, hlm], "sim_limits": [lo, hi], "candidates": cands,
                    "to_do": "confirm with ONE live readback against the panel before setting status 'verified' and the numbers in control_pv_map.json"})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    for r in limits_evidence(read_probe_csv(Path(argv[0]))):
        print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())

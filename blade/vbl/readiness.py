"""Truth scoring of a virtual-beamline state: hidden truth vs settings as a checklist with tolerances. FOR TESTS / SCORING ONLY (reveals the answers); the procedures never call it."""
import math
import numpy as np
from .world import SLIT_IDS, FS_IDS


def readiness(world):
    """Hidden truth vs settings, as a checklist with tolerances. FOR TESTS/SCORING (reveals the answers)."""
    c, T, sim = world.s["ctl"], world.s["truth"], world.sim
    E = c["hem.energy"]
    rep = {}
    # flux
    f_now = world.source_flux()
    gopt = world.optimal_gap(E)
    sv = dict(world.s)
    rep["undulator_gap_error_mm"] = c["und.gap"] + (world.s["gap_hyst"]) - gopt
    rep["th2_error_deg"] = world.th2_error_deg()
    rep["source_flux_relative_to_best"] = f_now / max(world.best_amp(E) * world.ring_scale(), 1e-9)
    # energy: mu_t of the foil at the current state vs target b
    el = "Re"
    b = sim["foils"]["b"][el]
    mu = -math.log(world._foil_T_smooth(el, world.energy_actual_keV()))
    rep["energy_mu_t_Re"] = mu
    rep["energy_mu_t_error"] = mu - b
    # steering / hotspot vs WB slit centre (in urad)
    xp, yp = world.steer_rad()
    wbl, wbh = world.slit_edges("wbSlits", "h")
    wvl, wvh = world.slit_edges("wbSlits", "v")
    zwb = world.z["wbSlits"]
    rep["wb_slit_centre_minus_hotspot_um"] = {"h": ((wbl + wbh) / 2 - xp * zwb * 1e3) * 1e3, "v": ((wvl + wvh) / 2 - yp * zwb * 1e3) * 1e3}
    # slits
    sl = {}
    for sid in SLIT_IDS[1:] + FS_IDS:
        lo, hi = world.slit_edges(sid, "h")
        vlo, vhi = world.slit_edges(sid, "v")
        bc = world.beam_centre(world.z[sid])
        sl[sid] = {"h_um": ((lo + hi) / 2 - bc[0]) * 1e3, "v_um": ((vlo + vhi) / 2 - bc[1]) * 1e3}
    rep["slit_centre_minus_beam_um"] = sl
    # cameras
    cams = {}
    for cam, cc in sim["cameras"].items():
        if not isinstance(cc, dict) or "stage" not in cc:
            continue
        zc, uc, vc, p, rows, cols = world.camera_view(cam)
        bc = world.beam_centre(zc)
        cams[cam] = {"beam_minus_camera_axis_px": {"h": (bc[0] - uc) / p, "v": -(bc[1] - vc) / p}, "focus_error_mm": world.camera_focus_error_mm(cam)}
    rep["cameras"] = cams
    # pin / axis (px on gh1)
    ps = world.pin_state(0.0)
    p = world.cams["gh1"]["pixel_um"] * 1e-3
    rep["axis"] = {"a_px": ps["a"] / p, "b_px": ps["b"] / p, "axis_minus_beam_px": (ps["c"] - world.beam_centre(world.z["samE"])[0]) / p,
                   "tilt_rx_deg": T["pin"]["tilt_rx_deg"] + c["samE.rx"]}
    tol = {"undulator_gap_error_mm": 0.02, "th2_error_deg": 0.0007, "energy_mu_t_error": 0.1}
    rep["ok"] = {"gap": abs(rep["undulator_gap_error_mm"]) < tol["undulator_gap_error_mm"], "th2": abs(rep["th2_error_deg"]) < tol["th2_error_deg"],
                 "energy": abs(rep["energy_mu_t_error"]) < tol["energy_mu_t_error"],
                 "steering_wb_vs_hotspot": max(abs(v) for v in rep["wb_slit_centre_minus_hotspot_um"].values()) < 60.0,
                 "slits_E": all(max(abs(v) for v in sl[k].values()) < 100.0 for k in ("slitEus", "slitEds"))}
    rep["tolerances"] = tol
    return rep

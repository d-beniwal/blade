"""Fit the tomo pin into the field of view of a tomo camera: if the pin is recognised in the frame, centre its axis on the lit footprint and put its tip a fixed fraction below the top
of the footprint, so the whole cone is visible. This is the "tomo-pin fit" button of the virtual-beamline page.

It is a FINE move for a pin that is already (at least partly) in the picture. It never searches: if no pin is recognised the answer is `found: False` with the reason and nothing moves
(use `pin_find.find_pin` to search for a pin that is not in view yet).

Recognition is `analysis.pin.measure.measure_frame` (the code validated on the real alignment frames). Moves use the sample stage of the E hutch (aero X moves the pin axis sideways,
samE.y moves it vertically) with the static image-shift signs of `sim.json stage_E` (`col_per_base`, `row_per_y`: mm of image shift per mm of motor). On an instrument that cannot be written
(the real beamline) `set` raises ReadOnlyError, so there it can only be used with `apply=False`, which reports the moves it WOULD make (a proposal)."""
import numpy as np
from ._util import accepts_world
from ..analysis.pin.measure import measure_frame

TOP_FRAC = 0.2           # the tip goes this fraction of the footprint height below its top edge (same convention as `assess_view`)
TOL_PX = 4.0             # converged when the axis and the tip are within this many full-resolution pixels of their targets
MAX_STEP_MM = 1.5        # never move a motor more than this in one go: a bad recognition must not fling the stage across its travel


def _position(m):
    """(axis column, tip row, how) of the recognised pin in full-resolution pixels, or (None, None, reason)."""
    v = m.get("view") or {}
    if m.get("usable") and m.get("pin_col_raw") is not None and m.get("top_row") is not None:
        return float(m["pin_col_raw"]), float(m["top_row"]), "whole pin in view"
    loc = v.get("locate")
    if v.get("state") == "partial" and loc and loc.get("axis_col") is not None and loc.get("top_row") is not None:
        return float(loc["axis_col"]), float(loc["top_row"]), "pin partly in view (position from the cone model)"
    if v.get("state") == "partial":
        return None, None, ("a pin-like dark object is partly in view but its edges are not reliable enough to position it (%s); not guessed - move it into the lit area by hand "
                            "or use the pin search" % ("; ".join(m.get("reasons") or []) or "unreliable edges"))
    return None, None, v.get("why") or "; ".join(m.get("reasons") or []) or m.get("message", "no pin recognised")


@accepts_world
def fit_pin_in_view(inst, cam="gh1", apply=True, max_iter=4):
    """Look, and if the pin is recognised, move aero X and samE.y until its axis sits on the footprint centre and its tip at TOP_FRAC of the footprint height (at most `max_iter`
    looks). `apply=False` measures once and returns the moves it would make without making them. Returns {found, state, moved, converged, moves, controls, offsets_px, frames, reason}."""
    sE = inst.sim["stage_E"]
    kx, ky = float(sE["col_per_base"]), float(sE["row_per_y"])
    p_mm = inst.cams[cam]["pixel_um"] * 1e-3                      # full-resolution frames: bin 1
    lo_x, hi_x = inst.spec("samE.aerox")[:2]
    lo_y, hi_y = inst.spec("samE.y")[:2]
    log, frames, moved = [], 0, False
    for it in range(max_iter if apply else 1):
        m = measure_frame(inst.frame(cam, bin_=1).astype(float), inst.ctl("samE.ry"))
        frames += 1
        state = (m.get("view") or {}).get("state", "unknown")
        col, row, how = _position(m)
        if col is None:
            return {"found": False, "state": state, "moved": moved, "frames": frames, "reason": how, "log": log,
                    "note": "nothing was recognised as the tomo pin in this frame; use the pin search (vbl_find_pin) to bring it into view first" if not moved else
                            "the pin was lost after a move"}
        b = m["beam"]
        tgt_col, tgt_row = float(b["cx"]), float(b["box"][2]) + TOP_FRAC * float(b["height"])
        dcol, drow = tgt_col - col, tgt_row - row                 # image shift still needed (px): + = right / down
        off = {"axis_col_px": round(col, 1), "tip_row_px": round(row, 1), "target_col_px": round(tgt_col, 1), "target_row_px": round(tgt_row, 1),
               "to_move_px": [round(dcol, 1), round(drow, 1)]}
        d_ax = float(np.clip(dcol * p_mm / kx, -MAX_STEP_MM, MAX_STEP_MM))       # image shift (mm) = col_per_base * d(aero X)
        d_y = float(np.clip(drow * p_mm / ky, -MAX_STEP_MM, MAX_STEP_MM))        # image shift (mm) = row_per_y * d(samE.y)
        ax0, y0 = inst.ctl("samE.aerox"), inst.ctl("samE.y")
        ax1, y1 = float(np.clip(ax0 + d_ax, lo_x, hi_x)), float(np.clip(y0 + d_y, lo_y, hi_y))
        log.append({"look": it + 1, "how": how, **off, "d_aerox_mm": round(ax1 - ax0, 4), "d_samE_y_mm": round(y1 - y0, 4)})
        done = abs(dcol) <= TOL_PX and abs(drow) <= TOL_PX
        if not apply:
            return {"found": True, "state": state, "moved": False, "converged": done, "frames": frames, "log": log, "offsets_px": off,
                    "proposed": {"samE.aerox": ax1, "samE.y": y1}, "note": "apply=False: nothing was moved"}
        if done:
            return {"found": True, "state": state, "moved": moved, "converged": True, "frames": frames, "log": log, "offsets_px": off,
                    "controls": {"samE.aerox": ax0, "samE.y": y0}}
        inst.set("samE.aerox", ax1)
        inst.set("samE.y", y1)
        moved = True
    # out of iterations: report where it ended
    m = measure_frame(inst.frame(cam, bin_=1).astype(float), inst.ctl("samE.ry"))
    col, row, how = _position(m)
    return {"found": col is not None, "state": (m.get("view") or {}).get("state", "unknown"), "moved": moved, "converged": False, "frames": frames + 1, "log": log,
            "controls": {"samE.aerox": inst.ctl("samE.aerox"), "samE.y": inst.ctl("samE.y")}, "reason": None if col is not None else how}

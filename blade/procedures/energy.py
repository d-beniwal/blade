"""Energy and flux procedures (undulator gap, Th2, foil-edge energy calibration). They act only through the `Instrument` interface (blade/instrument/base.py), so the same
code runs on the simulator and, once it is allowed to command the beamline, on the real machine. On a read-only instrument every `set` raises ReadOnlyError."""
import numpy as np
from scipy.optimize import curve_fit
from scipy.special import erf
from ..physics import core as pcore, undulator as pund
from ..analysis.frame import fit_peak
from ._util import accepts_world


@accepts_world
def open_gap(inst, gap=9.5):
    """'Open to ~9.5 mm first, then setundgap': approach the working gap from the open side so the hysteresis is repeatable."""
    inst.set("und.gap", max(inst.ctl("und.gap"), gap) + 0.3)


@accepts_world
def nominal_gap(inst, E_keV=None, apply=False):
    """Gap for the best harmonic at the mono energy from the (inferred) period: the operator's starting guess before a gap scan."""
    E = inst.ctl("hem.energy") if E_keV is None else E_keV
    u = inst.sim["undulator"]
    best = None
    for k in pund.harmonics_from_sim(inst.sim):
        try:
            g = pund.gap_for_energy_mm(E, k, u["period_mm"], coef=pund.coef_from_sim(inst.sim))
        except ValueError:
            continue
        a = pund.harm_amp_from_sim(inst.sim, k, g)
        if g >= u["gap_limits_mm"][0] and (best is None or a > best[1]):
            best = (g, a, k)
    if best is None:
        raise ValueError("no harmonic reaches this energy inside the gap limits")
    if apply:
        inst.set("und.gap", float(best[0]))
    return {"gap_mm": best[0], "harmonic": best[2], "E_keV": E, "applied": bool(apply)}


@accepts_world
def gap_scan(inst, centre, half_range=0.2, n=40, ic="icB1", apply=True):
    """undscangap: scan the gap high -> low around `centre` against an IC at the current mono energy; returns the curve and the peak; with apply=True
    sets the gap to the fitted peak (approached from the open side, as the logs insist)."""
    gaps = np.linspace(centre + half_range, centre - half_range, n)
    inst.set("und.gap", min(gaps[0] + 0.3, inst.sim["undulator"]["gap_limits_mm"][1]))      # open first
    counts = []
    for g in gaps:
        inst.set("und.gap", float(g))
        inst.wait(1.0)
        counts.append(inst.ic_kHz(ic))
    pk, fwhm = fit_peak(gaps, counts)
    if apply:
        inst.set("und.gap", min(pk + 0.3, inst.sim["undulator"]["gap_limits_mm"][1]))
        inst.set("und.gap", pk)
    return {"gap": gaps.tolist(), "counts_kHz": [round(c, 2) for c in counts], "peak_gap_mm": pk, "fwhm_mm": fwhm, "max_kHz": float(max(counts)), "ic": ic, "applied": apply}


@accepts_world
def th2_scan(inst, half_range=0.004, n=21, ic="icB1", apply=True):
    """Tweak Th2 across +-half_range deg (the logs only tweak by hand in 0.0002 deg steps; a scan is the same thing done systematically)."""
    c0 = inst.ctl("hem.th2_offset")
    xs = np.linspace(c0 - half_range, c0 + half_range, n)
    vals = []
    for x in xs:
        inst.set("hem.th2_offset", float(x))
        vals.append(inst.ic_kHz(ic))
    pk, fwhm = fit_peak(xs, vals)
    inst.set("hem.th2_offset", pk if apply else c0)
    return {"th2_offset": xs.tolist(), "counts_kHz": [round(v, 2) for v in vals], "peak_th2_offset_deg": pk, "fwhm_deg": fwhm, "applied": apply}


@accepts_world
def select_edge(inst, element="Re"):
    """Set the HEM energy readout to the tabulated K-edge energy of the foil (the energy the operator works at for that edge; the true edge is offset by
    the hidden energy miscalibration, which E scan / calibrate energy then find)."""
    E = float(pcore.edge_keV(element))
    inst.set("hem.energy", E)
    return {"element": element, "edge_keV": round(E, 4), "hem.energy": E}


@accepts_world
def edge_scan(inst, element="Re", half_range_keV=0.12, n=49, apply=False):
    """E_scan: with the foil in, step the HEM energy across the foil K edge, record mu_t, fit mu_t(E) = dif + b*(1+erf((E-pos)/wid))/2 (the beamline's
    E_scan.gpl form). Returns the fit and the energy at which mu_t = b (the operators' calibrated energy). Restores foil/energy unless apply=True."""
    e0 = inst.ctl("hem.energy")
    foil0 = inst.ctl("foilB.pos")
    inst.set("foilB.pos", element)
    Es = np.linspace(e0 - half_range_keV, e0 + half_range_keV, n)
    mu = []
    for E in Es:
        inst.set("hem.energy", float(E))
        inst.wait(5.0)
        mu.append(inst.mu_t())
    mu = np.array(mu, float)
    f = lambda E, dif, b, pos, wid: dif + b * 0.5 * (1 + erf((E - pos) / wid))
    try:
        p, _ = curve_fit(f, Es, mu, p0=[mu.min(), mu.max() - mu.min(), Es[np.argmax(np.gradient(mu))], 0.06], maxfev=8000)
        dif, b, pos, wid = [float(v) for v in p]
        wid = abs(wid)
    except Exception as e:
        dif = b = pos = wid = float("nan")
    Etar = None
    if np.isfinite(b):
        lo, hi = Es.min(), Es.max()
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if f(mid, dif, b, pos, wid) < b else (lo, mid)
        Etar = 0.5 * (lo + hi)
    inst.set("hem.energy", float(Etar if (apply and Etar) else e0))
    if not apply:
        inst.set("foilB.pos", foil0)
    return {"energy_keV": Es.tolist(), "mu_t": [round(float(v), 4) for v in mu], "fit": {"dif": dif, "b": b, "pos_keV": pos, "wid_keV": wid},
            "energy_for_mu_t_equals_b_keV": Etar, "element": element, "applied": apply}


@accepts_world
def calibrate_energy(inst, element="Re", target_b=None, max_iter=4):
    """Energy calibration the way the operators do it: E_scan fit -> adjust the Th1 offset (userTran3) until mu_t = b at the HEM readout energy -> re-check
    with mu_t. Th1 offset moves the real energy by -45 eV per mdeg at 71.7 keV. Returns the final mu_t and offset."""
    E_read = inst.ctl("hem.energy")
    d = pcore.d_spacing_cubic(pcore.SI_A, (1, 1, 1))
    hist = []
    for it in range(max_iter):
        sc = edge_scan(inst, element, apply=False)
        fit = sc["fit"]
        if not np.isfinite(fit["b"]):
            raise RuntimeError("edge fit failed (is the beam on the B ICs and the energy within 0.12 keV of the edge?)")
        b = fit["b"] if target_b is None else target_b
        # real-energy shift needed so that the edge sits where mu_t = b at the readout energy: dE = (energy found) - (readout)
        dE = sc["energy_for_mu_t_equals_b_keV"] - E_read
        # raising the Th1 offset lowers the real energy: dE/doffset = dEdtheta (keV/deg)
        dEdth = pcore.energy_shift_from_angle_keV(E_read, d, 1e-3) / 1e-3
        inst.set("hem.th1_offset", float(inst.ctl("hem.th1_offset") + dE / dEdth))
        inst.set("foilB.pos", element)
        mu = float(np.mean([inst.mu_t() for _ in range(3)]))
        inst.set("foilB.pos", "out")
        hist.append({"iteration": it, "edge_fit": fit, "shift_keV": dE, "th1_offset": inst.ctl("hem.th1_offset"), "mu_t_after": mu})
        if abs(mu - b) < 0.05:
            break
    return {"converged": abs(mu - b) < 0.08, "mu_t": mu, "b": b, "th1_offset": inst.ctl("hem.th1_offset"), "history": hist}


@accepts_world
def tune_energy_flux(inst, element="Re", ic="icB1"):
    """Energy + flux part of the start-of-beamtime sequence on its own (no camera): HEM at the foil edge, nominal gap, gap scan, Th2 scan, energy calibration on
    the foil edge (E_scan -> Th1 offset), Th2 and gap again. Leaves the instrument with the settings that maximise the flux at the calibrated energy."""
    steps = {}
    steps["edge"] = select_edge(inst, element)
    g = nominal_gap(inst)
    open_gap(inst, g["gap_mm"])
    inst.set("und.gap", g["gap_mm"])
    steps["gap_wide"] = {k: v for k, v in gap_scan(inst, inst.ctl("und.gap"), 0.30, 61, ic).items() if k in ("peak_gap_mm", "max_kHz")}
    steps["th2"] = {k: v for k, v in th2_scan(inst, 0.006, 31, ic).items() if k in ("peak_th2_offset_deg", "fwhm_deg")}
    steps["gap_fine"] = {k: v for k, v in gap_scan(inst, inst.ctl("und.gap"), 0.10, 41, ic).items() if k in ("peak_gap_mm", "max_kHz")}
    cal = calibrate_energy(inst, element)
    steps["energy"] = {k: cal[k] for k in ("converged", "mu_t", "b", "th1_offset")}
    steps["th2_after"] = {k: v for k, v in th2_scan(inst, 0.004, 21, ic).items() if k in ("peak_th2_offset_deg",)}
    steps["gap_after"] = {k: v for k, v in gap_scan(inst, inst.ctl("und.gap"), 0.06, 31, ic).items() if k in ("peak_gap_mm", "max_kHz")}
    return steps

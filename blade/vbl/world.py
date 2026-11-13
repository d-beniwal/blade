"""Virtual 1-ID beamline: the state, the hidden truth and the physics that turn control settings into beam position, size, flux and ion-chamber counts.

SIMULATION ONLY - nothing here talks to EPICS or hardware. The numbers come from beamline_twins/<bl>/sim.json (each tagged log / code / assumed).

What it models (every item traced to the logs in beamline_twins/1-ID/physics/):
  * beam path = linear ray optics (point `theta` of emission + finite source `s`): u(z) = A theta + E s + B, so slits, lenses, penumbra and the
    focus come out of ONE mechanism. Each axis (h, v) is independent. Edges of every slit are projected onto a camera plane with their own
    geometric penumbra (source size x distance ratio) and Fresnel fringes (see imaging.py).
  * beam intensity = Gaussian in angle (sigma set by the logged WB-slit flux ratio) x ring current x undulator harmonic peak (gap vs mono energy,
    ~1 % wide, with hysteresis and wander) x monochromator Th2 rocking curve (with thermal shift) x slit fractions x foil/attenuator transmission.
  * mono energy: Th1 = Bragg(E) + offset; the REAL energy differs by the hidden offset error (45 eV per mdeg at 71.7 keV); a foil K-edge scan (mu*t)
    is how the operators calibrate it.
  * ion chambers: rate = flux x calibration + dark floor, clipped at 1e6/s.
  * hidden truth (random per seed): beam steering error, slit zeros, camera stage zeros, undulator gap error, Th1/Th2 errors, lens tilt optima,
    camera focus, pin offsets. The operator never sees them; they are found by scans exactly as at the beamline.
State is a plain JSON dict (`self.s`) so it can be saved between tool calls / CLI calls and shared with the GUI."""
import json
import math
import zlib
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.special import erf
from .. import paths
from ..physics import core as pcore, undulator as pund, lens as plens

TWIN = "1-ID"
SQ2 = math.sqrt(2.0)


@lru_cache(maxsize=4)
def load_sim(twin=TWIN):
    return json.loads((paths.TWINS_DIR / twin / "sim.json").read_text())


def _profile_cameras():
    """Camera pixel sizes come from the profile (the one place BLADE keeps them)."""
    from .. import twin_api
    return twin_api.read_profile("s1id")["cameras"]


def stable_seed(*parts):
    """Deterministic 32-bit seed from any parts (Python's hash() of strings changes between processes; the simulator must not)."""
    return zlib.crc32(repr(parts).encode()) & 0xFFFFFFFF


def _phi(x):
    return 0.5 * (1.0 + erf(x / SQ2))


SLIT_IDS = ["wbSlits", "slitB", "slitCus", "slitCds", "slitEus", "slitEds"]
FS_IDS = ["fsB", "fsE"]                  # fast shutters act as fixed-size apertures (3.0 x 1.7 mm) whose centre can be misaligned
APERTURE_IDS = SLIT_IDS + FS_IDS
LENS_IDS = list(plens.LENSES_1ID)               # lens4B, lens5B, lens1C..4C, lens1E..4E
LENS_Z_KEY = {"lens4B": "stackB1", "lens5B": "stackB2"}
STAGES = ["tomoB", "tomoC", "tomoE", "tomoEds"]
CAMERAS = ["gh1", "pg1", "pg5", "retiga2"]


class VirtualBeamline:
    name = "vbl"

    # ------------------------------------------------------------------------------------------------------------------------------ setup
    def __init__(self, state=None, seed=0, scenario="startup", twin=TWIN):
        self.twin = twin
        self.sim = load_sim(twin)
        self.z = {k: v for k, v in self.sim["z_m"].items() if not k.startswith("_")}
        self.cams = _profile_cameras()
        self.last_meta = {}
        if state is None:
            state = self._new_state(seed, scenario)
        self.s = state

    # defaults of every control (what the operator panel shows after a reset) ------------------------------------------------------------
    def _default_controls(self):
        sim = self.sim
        c = {"ring.current": sim["source"]["ring_current_mA"], "und.gap": 10.025, "steer.xp": 0.0, "steer.yp": 0.0,
             "hem.energy": 71.676, "hem.th1_offset": sim["hem"]["th1_offset_deg"], "hem.th2_offset": sim["hem"]["th2_offset_deg"],
             "foilB.pos": "out", "attenB.pos": 0, "attenC.pos": 0, "shutter_a": 1, "fsB": 1, "fsE": 1}
        for sid in SLIT_IDS:
            sl = sim["slits"][sid]
            c[f"{sid}.hsize"], c[f"{sid}.vsize"] = sl["size_default"]
            c[f"{sid}.hcenter"], c[f"{sid}.vcenter"] = sl["center_default"]
        fs = sim["fast_shutters"]
        for sid in FS_IDS:
            c[f"{sid}.hsize"], c[f"{sid}.vsize"] = fs[sid]["hsize"], fs[sid]["vsize"]
            c[f"{sid}.hcenter"], c[f"{sid}.vcenter"] = fs["centre_default"]
        xo = sim["lenses"]["x_out_mm"]
        for ln in LENS_IDS:
            c[f"{ln}.x"], c[f"{ln}.y"], c[f"{ln}.th"], c[f"{ln}.phi"] = xo, 0.0, 0.0, 0.0     # parked out of the beam
        ts = sim["tomo_stages"]
        for st in STAGES:
            c[f"{st}.x"], c[f"{st}.y"] = ts[st]["out_x_mm"], 0.0
        for cam in CAMERAS:
            c[f"{cam}.exposure"], c[f"{cam}.focus"] = 0.1, 0.0
        sE = sim["stage_E"]
        c.update({"samE.x": sE["x_ref_mm"], "samE.y": sE["y_ref_mm"], "samE.z": sE["pin_z_ref_mm"], "samE.ry": 0.0, "samE.aerox": sE["aerox_ref_mm"],
                  "samE.rx": 0.0, "samE.rz": 0.0})
        return c

    def _new_state(self, seed, scenario):
        rng = np.random.default_rng(seed)
        sim, sc = self.sim, self.sim["truth_scales"]
        ctl = self._default_controls()
        g = lambda scale: float(rng.normal(0, scale))
        truth = {
            "steer_xp_urad": g(sc["steer_err_urad"]), "steer_yp_urad": g(sc["steer_err_urad"] * 0.6),
            "gap_err_mm": g(sc["gap_err_mm"]), "th1_err_mdeg": g(sc["th1_err_mdeg"]), "th2_err_deg": g(sc["th2_err_deg"]),
            "th1_drift_mdeg_per_h": g(0.15), "steer_drift_urad_per_h": g(0.3),
            "slit_zero": {sid: [g(self._zero_spread(sid)), g(self._zero_spread(sid))] for sid in APERTURE_IDS},
            "lens_tilt_err_deg": {ln: g(sim["lenses"]["truth_tilt_error_deg"]) for ln in LENS_IDS},
            "lens_zero": {ln: [g(0.08), g(0.08)] for ln in LENS_IDS},
            "cam_zero": {cam: [g(sc["camera_zero_mm"]), g(sc["camera_zero_mm"])] for cam in CAMERAS},
            "cam_focus_true": {cam: g(sc["focus_err_mm"]) for cam in CAMERAS},
            "pin": dict(sim["stage_E"]["truth"]), "texture_seed": int(seed),
        }
        s = {"seed": seed, "scenario": scenario, "ctl": ctl, "truth": truth, "t_s": 0.0, "gap_dir": "close", "gap_hyst": 0.0,
             "th2_thermal_deg": 0.0, "n_acq": 0, "log": [], "calib": {}}
        self.s = s
        # camera stage zeros: the logs zero the stage on the hotspot, so the beam is within the stage's reach (near x = 0 +- 1 mm, never beyond the soft limits)
        sg = sim["tomo_stages"]
        for cam in CAMERAS:
            zc = sim["z_m"][sim["cameras"][cam]["z_key"]]
            ub, vb = self.beam_centre(zc)
            xb, yb = float(rng.uniform(-0.4, 1.2)), float(rng.uniform(-0.8, 0.8))
            truth["cam_zero"][cam] = [ub - sg["xsign"] * xb, vb - sg["ysign"] * yb]
        if scenario == "startup":
            ctl["samE.y"] = 26.0          # sample stage lifted: the pin is out of the beam while the beam is being set up
            # start with the beam already on the gh1 camera (user request 2026-11-12): camera 0.15-0.3 mm off the hotspot, downstream slits open, exposure set to see it
            for sid in ("slitB", "slitCus", "slitCds", "slitEus", "slitEds"):
                ctl[f"{sid}.hsize"] = ctl[f"{sid}.vsize"] = 2.5
            st = sim["cameras"]["gh1"]["stage"]
            zc = sim["z_m"][sim["cameras"]["gh1"]["z_key"]]
            ub, vb = self.beam_centre(zc)
            xs, ys = float(rng.uniform(0.15, 0.3)) * rng.choice([-1, 1]), float(rng.uniform(0.15, 0.3)) * rng.choice([-1, 1])
            truth["cam_zero"]["gh1"] = [ub - sg["xsign"] * (0.3 - xs), vb - sg["ysign"] * (0.1 - ys)]
            ctl[f"{st}.x"], ctl[f"{st}.y"] = 0.3, 0.1
            ctl["gh1.exposure"] = float(np.clip(0.035 / max(self.source_flux(), 1e-3), 0.05, 10.0))
        if scenario in ("aligned", "ready_for_pin", "camera_in_beam"):
            self._make_aligned(scenario)
        elif scenario != "startup":
            raise ValueError("scenario must be 'startup' (everything misaligned), 'camera_in_beam' (beam on gh1, rest unoptimised), "
                             "'ready_for_pin' (beam + flux good, pin in view: for `blade align`) or 'aligned'")
        return s

    def _zero_spread(self, sid):
        sp = self.sim["slits"]["truth_zero_spread_mm"]
        return sp.get(sid, sp["default"])

    def _make_aligned(self, scenario):
        """Set the truth so the instrument is well aligned (used for tests and the pin / alignment scenarios): the truth follows the settings."""
        s, sim, T, c = self.s, self.sim, self.s["truth"], self.s["ctl"]
        T["steer_xp_urad"], T["steer_yp_urad"] = 0.0, 0.0
        T["slit_zero"] = {sid: [0.0, 0.0] for sid in APERTURE_IDS}
        T["gap_err_mm"], T["th1_err_mdeg"], T["th2_err_deg"] = 0.0, 0.0, 0.0
        T["th1_drift_mdeg_per_h"] = T["steer_drift_urad_per_h"] = 0.0
        for k in T["lens_tilt_err_deg"]:
            T["lens_tilt_err_deg"][k] = 0.0
            T["lens_zero"][k] = [0.0, 0.0]
        c["und.gap"] = self.optimal_gap(c["hem.energy"])
        s["th2_thermal_deg"] = self._thermal_target()
        c["hem.th2_offset"] = self.sim["hem"]["th2_offset_deg"] + T["th2_err_deg"] + s["th2_thermal_deg"]      # Th2 peaked
        c["hem.th1_offset"] = self.th1_true_offset()
        self.calibrate_energy_model("Re")                                                                       # energy calibrated on the foil edge (mu_t = b)
        # E camera on the beam, pin in view; focus ok
        cam = "gh1"
        T["cam_focus_true"] = {k: 0.0 for k in CAMERAS}
        st = sim["cameras"][cam]["stage"]
        ub, vb = self.beam_centre(sim["z_m"][sim["cameras"][cam]["z_key"]])
        sg = sim["tomo_stages"]
        T["cam_zero"][cam] = [ub - sg["xsign"] * 0.30, vb - sg["ysign"] * 0.10]
        c[f"{st}.x"], c[f"{st}.y"] = 0.30, 0.10
        if scenario in ("camera_in_beam", "ready_for_pin", "aligned"):
            c["samE.y"] = self.sim["stage_E"]["y_ref_mm"] if scenario != "camera_in_beam" else 26.0
        if scenario in ("ready_for_pin", "aligned"):
            c["slitEus.hsize"], c["slitEus.vsize"] = 0.65, 0.52
            c["slitEds.hsize"], c["slitEds.vsize"] = 1.2, 1.0
            c["slitB.hsize"] = c["slitB.vsize"] = 2.0
            c["slitCus.hsize"] = c["slitCus.vsize"] = 1.5
            c["slitCds.hsize"] = c["slitCds.vsize"] = 1.5
            for sid in APERTURE_IDS:      # open slits centred on the beam
                z = self.z[sid]
                uc, vc = self.beam_centre(z)
                c[f"{sid}.hcenter"] = (uc - 0.0) / sim["slits"]["hsign"]
                c[f"{sid}.vcenter"] = vc
            c["wbSlits.hsize"] = c["wbSlits.vsize"] = 0.3
            c["fsB.hcenter"] = c["fsE.hcenter"] = 0.0
            for sid in FS_IDS:
                uc, vc = self.beam_centre(self.z[sid])
                c[f"{sid}.hcenter"], c[f"{sid}.vcenter"] = uc, vc
            uc, vc = self.beam_centre(self.z["wbSlits"])
            c["wbSlits.hcenter"], c["wbSlits.vcenter"] = uc, vc
            T["pin"]["axis_u_mm"] = self.beam_centre(self.z["samE"])[0] + T["pin"]["c_axis_off_beam_mm"]

    # ------------------------------------------------------------------------------------------------------------------------------ helpers
    def ctl(self, name):
        return self.s["ctl"][name]

    def spec(self, name):
        """(lo, hi, unit, description) of a control for validation / GUI."""
        return control_specs(self.twin)[name]

    def advance(self, dt_s):
        """Advance the virtual clock (mono thermal state relaxes, steering and Th1 drift)."""
        s = self.s
        s["t_s"] += dt_s
        tau = self.sim["hem"]["thermal"]["tau_s"]
        tgt = self._thermal_target()
        s["th2_thermal_deg"] += (tgt - s["th2_thermal_deg"]) * (1.0 - math.exp(-dt_s / tau))

    def _thermal_target(self):
        th = self.sim["hem"]["thermal"]
        wb = self.ctl("wbSlits.hsize") * self.ctl("wbSlits.vsize")
        return th["th2_shift_deg_per_kW"] * th["power_kW_per_mm2"] * wb * self.ring_scale()

    def ring_scale(self):
        return self.ctl("ring.current") / self.sim["source"]["ring_current_mA"]

    def log(self, msg):
        self.s["log"].append(f"t={self.s['t_s']:.0f}s {msg}")
        del self.s["log"][:-200]

    # ------------------------------------------------------------------------------------------------------------------------------ mono / ID
    def th1_true_offset(self):
        T = self.s["truth"]
        return self.sim["hem"]["th1_offset_deg"] + (T["th1_err_mdeg"] + T["th1_drift_mdeg_per_h"] * self.s["t_s"] / 3600.0) * 1e-3

    def energy_actual_keV(self):
        """Energy that really leaves the mono: Th1 motor angle minus the TRUE offset (operators set the offset via the foil-edge calibration)."""
        E = self.ctl("hem.energy")
        d = pcore.d_spacing_cubic(pcore.SI_A, (1, 1, 1))
        # the Th1 calc record is Th1 = s*theta_B + offset (s = 1.0001973, fitted to the printed outputs); the crystals sit at the physical angle, so the
        # operator-calibrated offset is the true one only at the calibration energy: reference shift (s-1)*theta_B(E_cal) keeps E_actual(E_cal) exact
        th_motor = pcore.HEM_TH1_SCALE * pcore.bragg_angle_deg(E, d) + self.ctl("hem.th1_offset")
        ref = (pcore.HEM_TH1_SCALE - 1.0) * pcore.bragg_angle_deg(pcore.HEM_CAL_E_KEV, d)
        Ea = pcore.energy_from_bragg_keV(th_motor - self.th1_true_offset() - ref, d)
        # a Th2 detuning also drags the energy readout (log: Th2 tweak moved mu_t 1.299 -> 1.334): about 0.3 x the Th1 sensitivity
        k = self.sim["hem"]["th2_energy_coupling"]
        dEdth = pcore.energy_shift_from_angle_keV(E, d, 1e-3) / 1e-3          # keV per degree (negative)
        return Ea + k * dEdth * self.th2_error_deg()

    def calibrate_energy_model(self, el="Re"):
        """Set hem.th1_offset (analytic, no IC noise) so the foil's mu_t equals its edge step b - what the operators do with Emon / E_scan. Used for the
        'aligned' scenarios and tests; the operator-style procedure with noisy ICs is procedures.calibrate_energy()."""
        b = self.sim["foils"]["b"][el]
        d = pcore.d_spacing_cubic(pcore.SI_A, (1, 1, 1))
        e0 = pcore.edge_keV(el)
        lo, hi = e0 - 0.4, e0 + 0.4
        mu = lambda E: -math.log(self._foil_T_smooth(el, E))
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if mu(mid) < b else (lo, mid)
        target = 0.5 * (lo + hi)
        for _ in range(6):
            err = target - self.energy_actual_keV()
            self.s["ctl"]["hem.th1_offset"] += err / (pcore.energy_shift_from_angle_keV(self.ctl("hem.energy"), d, 1e-3) / 1e-3)
        return target

    def th2_error_deg(self):
        """Th2 detuning from the rocking-curve optimum (deg): set offset - (true offset + thermal shift)."""
        T = self.s["truth"]
        return self.ctl("hem.th2_offset") - (self.sim["hem"]["th2_offset_deg"] + T["th2_err_deg"] + self.s["th2_thermal_deg"])

    def th2_factor(self):
        w = self.sim["hem"]["th2_rocking_fwhm_deg"] / 2.3548
        return math.exp(-0.5 * (self.th2_error_deg() / w) ** 2)

    def gap_actual(self):
        return self.ctl("und.gap") + self.s["gap_hyst"]

    def und_coef(self):
        """Field coefficients (a, b, c) of the undulator K(gap) model: sim.json `undulator.k_coef` (fitted to the logs) or the module default."""
        k = self.sim["undulator"].get("k_coef")
        return tuple(k) if k else pund.HALBACH_HYBRID_NDFEB

    def harmonics(self):
        u = self.sim["undulator"]
        return [int(n) for n in (u["flux_model"]["harmonics"] if u.get("flux_model") else u["harmonic_amplitude"])]

    def harm_amp(self, n, gap):
        """Relative peak flux of harmonic n with the (true) gap `gap`: the Bessel flux factor of the undulator at that K (log-calibrated, see
        blade.physics.undulator.harmonic_amplitude) when sim.json has `flux_model`, else the old constant per harmonic."""
        u = self.sim["undulator"]
        fm = u.get("flux_model")
        if fm:
            return pund.harmonic_amplitude(int(n), gap, u["period_mm"], fm["exponent"], coef=self.und_coef())
        return u["harmonic_amplitude"][str(int(n))]

    def harmonic_peaks(self, E_keV=None, gap=None):
        """[(n, E_n(gap))] of the undulator at the (true) gap."""
        u = self.sim["undulator"]
        g = (self.gap_actual() if gap is None else gap) - self.s["truth"]["gap_err_mm"]
        return [(n, pund.harmonic_energy_keV(g, n, u["period_mm"], coef=self.und_coef())) for n in self.harmonics()]

    def id_flux(self, E_keV=None):
        """Relative undulator flux at the energy the mono selects: sum over harmonics of a ~1 % wide peak (log: 0.07-0.1 mm in gap at n=7)."""
        u = self.sim["undulator"]
        E = self.energy_actual_keV() if E_keV is None else E_keV
        tot = 0.0
        g_true = self.gap_actual() - self.s["truth"]["gap_err_mm"]
        for n, En in self.harmonic_peaks():
            # relative FWHM of the flux-vs-gap peak: n-independent `rel_fwhm` (fitted/physical) or the old per-harmonic scaling
            w = (u["rel_fwhm"] if "rel_fwhm" in u else u["rel_fwhm_per_harmonic"] * n) * En / 2.3548
            tot += self.harm_amp(n, g_true) * math.exp(-0.5 * ((En - E) / w) ** 2)
        return tot

    def optimal_gap(self, E_keV, n=None):
        """Gap (set value) that peaks the best harmonic at E, given the truth (the answer an operator finds by a gap scan)."""
        u, T = self.sim["undulator"], self.s["truth"]
        best = None
        for nn in ([n] if n else self.harmonics()):
            try:
                g0 = pund.gap_for_energy_mm(E_keV, nn, u["period_mm"], coef=self.und_coef())
            except ValueError:
                continue
            g = g0 + T["gap_err_mm"]
            if g < u["gap_limits_mm"][0]:
                continue
            a = self.harm_amp(nn, g0)
            if best is None or a > best[1]:
                best = (g, a, nn)
        if best is None:
            raise ValueError("no harmonic reaches this energy inside the gap limits")
        return best[0]

    # ------------------------------------------------------------------------------------------------------------------------------ steering and beam centre
    def steer_rad(self):
        T, c, u = self.s["truth"], self.s["ctl"], self.sim["undulator"]
        g = self.gap_actual() - 10.0
        dg = u["steering_per_gap_urad_per_mm"] * g
        drift = T["steer_drift_urad_per_h"] * self.s["t_s"] / 3600.0
        return ((T["steer_xp_urad"] + c["steer.xp"] + dg + drift) * 1e-6, (T["steer_yp_urad"] + c["steer.yp"] + 0.5 * dg + drift) * 1e-6)

    def beam_centre(self, z_m):
        """Centre of the (un-focused) beam at distance z_m: (u_mm, v_mm) = angle x z. Lenses are NOT included (see trace())."""
        xp, yp = self.steer_rad()
        return xp * z_m * 1e3, yp * z_m * 1e3

    # ------------------------------------------------------------------------------------------------------------------------------ slits
    def slit_edges(self, sid, axis):
        """(lo, hi) of the slit opening in LAB coordinates (mm): zero offset + centre -/+ size/2. h uses the sign convention of sim.json."""
        c, T, sg = self.s["ctl"], self.s["truth"]["slit_zero"][sid], self.sim["slits"]["hsign"]
        if axis == "h":
            cen, size, z0 = sg * c[f"{sid}.hcenter"] + T[0], c[f"{sid}.hsize"], 0
        else:
            cen, size = c[f"{sid}.vcenter"] + T[1], c[f"{sid}.vsize"]
        return cen - size / 2.0, cen + size / 2.0

    # ------------------------------------------------------------------------------------------------------------------------------ ray optics
    def lens_geom(self, ln):
        """Lens stack `ln` as the beam sees it, or None when its window does not overlap the beam (parked at x ~ 25 mm, or moved far in x / y).
        Returns {"f_m": focal length of the focusing axis (m; negative = diverging, i.e. tilted the other way; None if the tilt gives no power),
        "axis": 'h' or 'v' (the axis that focuses), "c": {"h": window centre u mm, "v": window centre v mm}}.
        The window (clear aperture, both directions) sits at lens zero + the x (horizontal, +u assumed) and y (vertical) motors; it counts as 'in the beam'
        when it overlaps the beam's +-4 sigma at that distance in BOTH directions. The tilt gives the power on the focusing axis only."""
        L, c, T, sim = plens.LENSES_1ID[ln], self.s["ctl"], self.s["truth"], self.sim
        zl = self.lens_z(ln)
        zu, zv = T["lens_zero"][ln]
        cu, cv = zu + c[f"{ln}.x"], zv + c[f"{ln}.y"]
        bu, bv = self.beam_centre(zl)
        reach = 0.5 * sim["lenses"]["aperture_mm"] + 4.0 * self.sigma_theta() * zl * 1e3
        if abs(cu - bu) > reach or abs(cv - bv) > reach:
            return None
        axis = "v" if L["orientation"] in ("upr", "up", "inv", "down") else "h"
        motor = "th" if axis == "v" else "phi"
        # tilt is measured relative to the lens zero; sign convention as blade.physics.lens.focus_motor_target
        tilt = c[f"{ln}.{motor}"] - L["zero_deg"] - T["lens_tilt_err_deg"][ln]
        if L["orientation"] in ("upr", "up", "out", "ob"):
            tilt = -tilt
        delta = plens.lens_delta(L["material"], max(self.energy_actual_keV(), 10.0))
        f_m = plens.prism_focal_length_m(tilt, delta, L["tooth_um"])
        return {"f_m": f_m if abs(f_m) >= 1e-6 else None, "axis": axis, "c": {"h": cu, "v": cv}}

    def lens_z(self, ln):
        return self.z.get(LENS_Z_KEY.get(ln, ln))

    def trace(self, axis, z_cam_m, with_lenses=True):
        """Trace the linear ray map for one axis up to z_cam_m. Returns dict: map at the camera (A, E, B), the list of apertures
        [(z, A, E, B, lo, hi, id)] and the allowed emission-angle interval [th_lo, th_hi] (rad, relative to the nominal axis; None -> blocked).
        Units: mm and rad; z in mm internally."""
        S = self.sim
        events = []
        for sid in APERTURE_IDS:
            if self.z[sid] < z_cam_m:
                lo, hi = self.slit_edges(sid, axis)
                events.append((self.z[sid], "ap", sid, (lo, hi)))
        if with_lenses:
            ap = S["lenses"]["aperture_mm"]
            for ln in LENS_IDS:
                zl = self.lens_z(ln)
                if zl is not None and zl < z_cam_m:
                    g = self.lens_geom(ln)
                    if g:
                        events.append((zl, "ap", ln + ".aperture", (g["c"][axis] - ap / 2, g["c"][axis] + ap / 2)))     # the window clips both directions
                        if g["axis"] == axis and g["f_m"]:
                            events.append((zl, "lens", ln, (g["f_m"] * 1e3, g["c"][axis])))
        events.sort(key=lambda e: (e[0], 0 if e[1] == "ap" else 1))
        A, E, B, C, F, D = 0.0, 1.0, 0.0, 1.0, 0.0, 0.0     # u = A th + E s + B ; u' = C th + F s + D   (z=0: u = s, u' = th)
        zprev = 0.0
        aps = []
        lo_th, hi_th = -1e9, 1e9
        for z, kind, name, data in events:
            dz = (z - zprev) * 1e3
            A, E, B = A + dz * C, E + dz * F, B + dz * D
            zprev = z
            if kind == "ap":
                lo, hi = data
                aps.append((z, A, E, B, lo, hi, name))
                if abs(A) < 1e-6:                          # aperture at a focus: passes iff the focal spot lies inside
                    if not (lo <= B <= hi):
                        lo_th, hi_th = 1.0, -1.0
                else:
                    t1, t2 = (lo - B) / A, (hi - B) / A
                    lo_th, hi_th = max(lo_th, min(t1, t2)), min(hi_th, max(t1, t2))
            else:
                f_mm, centre = data
                C, F, D = C - A / f_mm, F - E / f_mm, D - (B - centre) / f_mm
        dz = (z_cam_m - zprev) * 1e3
        A, E, B = A + dz * C, E + dz * F, B + dz * D
        return {"A": A, "E": E, "B": B, "aps": aps, "th": (lo_th, hi_th) if lo_th < hi_th else None}

    def sigma_theta(self):
        """Angular sigma of the beam (rad): the logged WB-slit flux ratio fixes sigma = 0.14 mm at the WB slits."""
        return self.sim["source"]["beam_sigma_at_wb_mm"] / (self.z["wbSlits"] * 1e3)

    def angle_fraction(self, axis, z_m, with_lenses=True):
        """Fraction of the beam's angular distribution that passes every aperture upstream of z_m (one axis)."""
        tr = self.trace(axis, z_m, with_lenses)
        if tr["th"] is None:
            return 0.0
        th0 = self.steer_rad()[0 if axis == "h" else 1]
        sg = self.sigma_theta()
        return float(_phi((tr["th"][1] - th0) / sg) - _phi((tr["th"][0] - th0) / sg))

    # ------------------------------------------------------------------------------------------------------------------------------ attenuation
    def _foil_transmission(self, E_keV):
        """Transmission of the foil + attenuators that are in the beam, smoothed by the mono bandwidth (edge width in sim.json)."""
        pos = self.ctl("foilB.pos")
        T = 1.0
        if pos != "out":
            T *= self._foil_T_smooth(pos, E_keV)
        return T

    def _atten_T(self, wheel, E_keV, upto_z):
        T = 1.0
        for name, key in (("attenB", "attenB_cu_mm"), ("attenC", "attenC_cu_mm")):
            if self.z[name] < upto_z:
                ent = self.sim["foils"][key][int(self.ctl(f"{name}.pos"))]
                mat, mm = ("Cu", ent) if not isinstance(ent, (list, tuple)) else (ent[0], ent[1])       # entry = mm of Cu, or [material, mm]
                if mm > 0:
                    T *= pcore.transmission(mat, mm, E_keV)
        return T

    def foil_thickness_mm(self, el):
        """Foil thickness [mm] that gives the logged edge step b (mu_t above minus below the edge) for this element."""
        cache = self.__dict__.setdefault("_ftk", {})
        if el not in cache:
            e0 = pcore.edge_keV(el)
            dmu = pcore.mu_per_cm(el, e0 + 0.3) - pcore.mu_per_cm(el, e0 - 0.3)          # 1/cm
            cache[el] = 10.0 * self.sim["foils"]["b"].get(el, self.sim["foils"]["ut_default"]) / dmu
        return cache[el]

    def edge_wid_keV(self, E_keV):
        """erf width of an edge scan: wid = E * 23 urad / tan(theta_B) (log fits at Tb/Yb/Re/Au)."""
        d = pcore.d_spacing_cubic(pcore.SI_A, (1, 1, 1))
        th = math.radians(pcore.bragg_angle_deg(E_keV, d))
        return E_keV * self.sim["hem"]["edge_wid_rad"] / math.tan(th)

    def _mu_table(self, el):
        """mu(E) of the foil element on a 1 eV grid around its K edge (xraydb, vectorised; computed once)."""
        cache = self.__dict__.setdefault("_mut", {})
        if el not in cache:
            e0 = pcore.edge_keV(el)
            E = np.arange(e0 - 1.5, e0 + 1.5, 0.0005)
            cache[el] = (E, self._mu_direct(el, E))
        return cache[el]

    @staticmethod
    def _mu_direct(el, E_keV):
        """mu(E) [1/cm] of the element straight from xraydb (vectorised, any energy)."""
        from ..physics.core import _xdb
        return np.asarray(_xdb().material_mu(el, np.asarray(E_keV, float) * 1000.0, density=pcore.material_density(el)), float)

    def _foil_T_smooth(self, el, E_keV):
        """Foil transmission at the mono energy, smoothed by the edge width wid(E) (erf edge as in the E_scan fits)."""
        Eg, mu = self._mu_table(el)
        sig = self.edge_wid_keV(E_keV) / SQ2
        xs = np.linspace(-4.0, 4.0, 61)
        w = np.exp(-0.5 * xs ** 2)
        w /= w.sum()
        Es = E_keV + xs * sig
        m = np.interp(Es, Eg, mu)
        far = (Es < Eg[0]) | (Es > Eg[-1])             # beyond the fine table: smooth tails, evaluate directly (np.interp would clamp them)
        if far.any():
            m[far] = self._mu_direct(el, Es[far])
        return float(np.sum(w * np.exp(-m * self.foil_thickness_mm(el) / 10.0)))

    def transmission_to(self, z_m):
        """Product of foil (hutch B) and attenuator transmissions upstream of z_m."""
        E = self.energy_actual_keV()
        T = 1.0
        if self.z["foilB"] < z_m:
            T *= self._foil_transmission(E)
        return T * self._atten_T(None, E, z_m)

    # ------------------------------------------------------------------------------------------------------------------------------ flux
    def beam_open(self, z_m):
        """False if a closed shutter blocks the beam upstream of z_m."""
        c = self.s["ctl"]
        if not c["shutter_a"] and z_m > self.z["shutter_a"]:
            return False
        if not c["fsB"] and z_m > self.z["fsB"]:
            return False
        if not c["fsE"] and z_m > self.z["fsE"]:
            return False
        return True

    def source_flux(self):
        """Relative flux (1.0 = the logged reference state: WB 0.3x0.3 mm centred, gap/Th2 optimal) BEFORE any slit: ring x undulator x Th2."""
        return self.ring_scale() * self.id_flux() * self.th2_factor()

    def flux_at(self, z_m):
        """Relative flux (units of the reference state's un-slitted flux) reaching plane z_m: apertures (both axes) x attenuation x shutters."""
        if not self.beam_open(z_m):
            return 0.0
        return self.source_flux() * self.angle_fraction("h", z_m) * self.angle_fraction("v", z_m) * self.transmission_to(z_m)

    def best_amp(self, E_keV):
        """Amplitude of the harmonic an operator would choose at E (the best reachable), so the IC reference (176 kHz) is the well-tuned state at any energy."""
        u = self.sim["undulator"]
        best = 0.0
        for k in self.harmonics():
            try:
                g = pund.gap_for_energy_mm(E_keV, k, u["period_mm"], coef=self.und_coef())
            except ValueError:
                continue
            if g >= u["gap_limits_mm"][0]:
                best = max(best, self.harm_amp(k, g))
        return best or 1.0

    def ref_flux(self):
        """Un-slitted flux of the reference state (WB 0.3x0.3 mm centred, gap/Th2 optimal, best harmonic): sets the IC calibration so icB1 = 176 kHz there."""
        sg = self.sigma_theta()
        half = 0.15 / (self.z["wbSlits"] * 1e3)
        f1 = float(_phi(half / sg) - _phi(-half / sg))
        return f1 * f1 * self.best_amp(self.ctl("hem.energy"))

    def flux_energy_factor(self):
        """Flux relative to its value at 71.7 keV for a well-tuned chain (sim.json `ic.flux_vs_energy_knots`, fitted to logged IC rates; 1 if absent)."""
        kn = self.sim["ic"].get("flux_vs_energy_knots")
        if not kn:
            return 1.0
        E, f = zip(*kn)
        return float(np.interp(self.ctl("hem.energy"), E, f))

    def ic_kHz(self, ic):
        z = self.z[ic]
        ics = self.sim["ic"]
        rate = ics["ref_kHz_at_icB1"] * self.flux_at(z) / self.ref_flux() * self.flux_energy_factor()
        dark = ics.get("dark_kHz_by_ic", {}).get(ic, ics["dark_kHz"])
        rng = np.random.default_rng(stable_seed(self.s["seed"], self.s["n_acq"], ic, round(self.s["t_s"])))
        rate = rate * (1.0 + rng.normal(0, 0.004)) + dark * (1 + rng.normal(0, 0.05))
        return float(min(rate, ics["max_kHz"]))

    def mu_t(self):
        """mu*t of the calibration foil as the operators measure it (Emon): ln(I before foil / I after), icB5 -> icB8, minus the foil-out ratio."""
        if self.ctl("foilB.pos") == "out":
            return None
        before, after = self.ic_kHz("icB5"), self.ic_kHz("icB8")
        dark = self.sim["ic"]["dark_kHz"]
        t_att = self._atten_T(None, self.energy_actual_keV(), self.z["icB8"])       # the B attenuator wheel sits between icB5 and icB8: Emon takes it out of the ratio
        return float(math.log(max(before - dark, 1e-6) / max((after - dark) / t_att, 1e-6)))

    # ------------------------------------------------------------------------------------------------------------------------------ cameras
    def camera_view(self, cam):
        """Camera geometry: (z_m, centre u mm, centre v mm, pixel_mm, rows, cols). The centre is the lab position of the optical axis."""
        cc = self.sim["cameras"][cam]
        st, sg = cc["stage"], self.sim["tomo_stages"]
        zc = self.z[cc["z_key"]]
        zx, zy = self.s["truth"]["cam_zero"][cam]
        u = zx + sg["xsign"] * self.ctl(f"{st}.x")
        v = zy + sg["ysign"] * self.ctl(f"{st}.y")
        return zc, u, v, self.cams[cam]["pixel_um"] * 1e-3, cc["rows"], cc["cols"]

    def camera_focus_error_mm(self, cam):
        return self.ctl(f"{cam}.focus") - self.s["truth"]["cam_focus_true"][cam]

    # ------------------------------------------------------------------------------------------------------------------------------ pin
    def pin_state(self, omega=None):
        """Pin geometry in the lab at rotation `omega`: dict with u (mm, horizontal position of the pin axis at the sample), v_top (mm, top flat),
        a, b, c (mm) in the BLADE convention x(w) = c + a cos w + b sin w, tilt of the pin axis in the image (rad)."""
        c, T, g = self.s["ctl"], self.s["truth"]["pin"], self.sim["stage_E"]
        sE = self.sim["stage_E"]
        w = math.radians(c["samE.ry"] if omega is None else omega)
        axis_u = T.get("axis_u_mm")
        if axis_u is None:
            axis_u = self.beam_centre(self.z["samE"])[0] + T["c_axis_off_beam_mm"]
        axis_u += g["col_per_base"] * (c["samE.aerox"] - sE["aerox_ref_mm"])
        a = T["a_mm"] + g["col_per_x"] * (c["samE.x"] - sE["x_ref_mm"])
        L = sE["pin"]["length_mm"]
        b = T["b_mm"] + g["k_z"] * (c["samE.z"] - sE["pin_z_ref_mm"]) + L * math.tan(math.radians(T["tilt_rx_deg"] + c["samE.rx"]))
        tilt_img = math.radians(T["tilt_rz_deg"] + c["samE.rz"])
        u = axis_u + a * math.cos(w) + b * math.sin(w) + L * math.tan(tilt_img) * 0.0
        v_top = T["pin_top_v_mm"] + (-g["row_per_y"]) * (c["samE.y"] - sE["y_ref_mm"])
        return {"u": u, "v_top": v_top, "a": a, "b": b, "c": axis_u, "tilt_img": tilt_img, "omega": c["samE.ry"] if omega is None else omega}

    # ------------------------------------------------------------------------------------------------------------------------------ actions
    def set(self, name, value):
        """Set one control (the simulated 'move'): validates the range, applies side effects (undulator hysteresis, thermal clock), advances time,
        and returns the readback. Raises ValueError for an unknown name or a value outside the limits."""
        sp = control_specs(self.twin)
        if name not in sp:
            raise ValueError(f"unknown control '{name}'. Use list_controls.")
        lo, hi, unit, _ = sp[name]
        c = self.s["ctl"]
        if isinstance(c[name], str) or name.endswith(".pos") and name.startswith("foil"):
            options = self.sim["foils"]["elements"] + ["out"]
            if value not in options:
                raise ValueError(f"{name} must be one of {options}")
        else:
            value = float(value) if not name.endswith((".pos", "shutter_a", "fsB", "fsE")) else int(value)
            if lo is not None and not (lo <= value <= hi):
                raise ValueError(f"{name}={value} outside the limits [{lo}, {hi}] {unit}")
        old = c[name]
        if name == "und.gap" and value != old:             # re-sending the same gap is not a move: no new hysteresis state
            self.s["gap_dir"] = "open" if value > old else "close"
            self.s["gap_hyst"] = self.sim["undulator"]["hysteresis_mm"] if self.s["gap_dir"] == "open" else 0.0
        if name.endswith((".hsize", ".vsize", ".hcenter", ".vcenter")):
            value = round(value * 1000.0) / 1000.0              # 1 um resolution
        dt = 1.0
        if isinstance(old, (int, float)) and not isinstance(old, bool):
            span = abs(value - old)
            dt = 1.0 + (span / 2.0 if name.startswith(("tomo", "samE.x", "samE.z", "samE.aerox")) else (span / 30.0 if name.endswith((".ry", ".th", ".phi")) else 0.2))
        c[name] = value
        self.advance(min(dt, 600.0))
        self.log(f"set {name} {old} -> {value}")
        return c[name]

    def snapshot(self):
        """All control values (the 'operator panel') plus derived readbacks. Never includes the hidden truth."""
        s = self.s
        out = {"controls": dict(s["ctl"]), "time_s": s["t_s"], "scenario": s["scenario"], "energy_readout_keV": s["ctl"]["hem.energy"],
               "th1_deg": pcore.hem_th1_deg(s["ctl"]["hem.energy"], s["ctl"]["hem.th1_offset"]),
               "z2_mm": pcore.hem_z2_mm(s["ctl"]["hem.energy"]),
               "th2_deg": pcore.hem_th2_deg(s["ctl"]["hem.energy"], s["ctl"]["hem.th2_offset"]),
               "chi2_deg": pcore.hem_chi2_deg(s["ctl"]["hem.energy"]),
               "ic_kHz": {ic: round(self.ic_kHz(ic), 2) for ic in self.sim["ic"]["ids"]}, "mu_t": self.mu_t()}
        return out

    def get_state(self):
        return self.s

    def truth_report(self):
        """THE ANSWERS (hidden truth vs current settings) - for tests, scoring and debugging, not for the operator/agent."""
        from .procedures import readiness
        return readiness(self)


@lru_cache(maxsize=4)
def control_specs(twin=TWIN):
    """{control name: (lo, hi, unit, description)} for every settable control."""
    sim = load_sim(twin)
    sp = {"ring.current": (0.0, 220.0, "mA", "ring current"), "und.gap": (sim["undulator"]["gap_limits_mm"][0], sim["undulator"]["gap_limits_mm"][1], "mm", "undulator gap (open before scanning: hysteresis)"),
          "steer.xp": (-60.0, 60.0, "urad", "horizontal beam steering (angle)"), "steer.yp": (-60.0, 60.0, "urad", "vertical beam steering (angle)"),
          "hem.energy": (*sim["hem"]["energy_range_keV"], "keV", "HEM energy (readout; sets Th1, Th2, Z2)"),
          "hem.th1_offset": (0.40, 0.55, "deg", "Th1 offset in userTran3 (energy calibration knob: -45 eV per mdeg at 71.7 keV)"),
          "hem.th2_offset": (0.10, 0.22, "deg", "Th2 offset (peaks the flux on the rocking curve)"),
          "foilB.pos": (None, None, "", "calibration foil: 'out' or an element (Re, Au, ...)"),
          "attenB.pos": (0, len(sim["foils"]["attenB_cu_mm"]) - 1, "idx", "B attenuator wheel position"),
          "attenC.pos": (0, len(sim["foils"]["attenC_cu_mm"]) - 1, "idx", "C attenuator wheel position"),
          "shutter_a": (0, 1, "", "A hutch shutter (1 open)"), "fsB": (0, 1, "", "B fast shutter (1 open)"), "fsE": (0, 1, "", "E fast shutter (1 open)")}
    for sid in SLIT_IDS:
        m = sim["slits"][sid]["size_max"]
        sp[f"{sid}.hsize"], sp[f"{sid}.vsize"] = (0.0, m, "mm", "slit opening"), (0.0, m, "mm", "slit opening")
        sp[f"{sid}.hcenter"], sp[f"{sid}.vcenter"] = (-5.0, 5.0, "mm", "slit centre"), (-5.0, 5.0, "mm", "slit centre")
    xo = sim["lenses"]["x_out_mm"]
    for ln in LENS_IDS:
        sp[f"{ln}.x"], sp[f"{ln}.y"] = (-30.0, 30.0, "mm", "lens x (0 = in the beam, ~25 = parked out)"), (-10.0, 10.0, "mm", "lens y")
        sp[f"{ln}.th"], sp[f"{ln}.phi"] = (-2.0, 2.0, "deg", "tilt about the horizontal axis (vertical focus)"), (-2.0, 2.0, "deg", "tilt about the vertical axis (horizontal focus)")
    ts = sim["tomo_stages"]
    for st in STAGES:
        sp[f"{st}.x"] = (*ts[st]["x_limits_mm"], "mm", f"tomo stage horizontal (in the beam near 0; out = {ts[st]['out_x_mm']})")
        sp[f"{st}.y"] = (*ts[st]["y_limits_mm"], "mm", "tomo stage vertical")
    for sid in FS_IDS:
        h, v = sim["fast_shutters"][sid]["hsize"], sim["fast_shutters"][sid]["vsize"]
        sp[f"{sid}.hsize"], sp[f"{sid}.vsize"] = (h, h, "mm", "fast-shutter opening (fixed)"), (v, v, "mm", "fast-shutter opening (fixed)")
        sp[f"{sid}.hcenter"], sp[f"{sid}.vcenter"] = (-5.0, 5.0, "mm", "fast-shutter blade centre"), (-5.0, 5.0, "mm", "fast-shutter blade centre")
    for cam in CAMERAS:
        sp[f"{cam}.exposure"], sp[f"{cam}.focus"] = (0.001, 10.0, "s", "camera exposure"), (-3.0, 3.0, "mm", "objective focus position")
    sp.update({"samE.x": (-9.907, 10.193, "mm", "pin horizontal (+x moves the pin image left)"), "samE.y": (-0.1, 29.81, "mm", "pin vertical"),
               "samE.z": (-9.971, 10.129, "mm", "pin along the beam"), "samE.ry": (-186.0, 186.0, "deg", "rotation omega"),
               "samE.aerox": (-8.585, 8.497, "mm", "Aero X base: moves the whole rotation axis"), "samE.rx": (-10.0, 10.0, "deg", "tilt Rx"),
               "samE.rz": (-8.1, 8.1, "deg", "tilt Rz")})
    return sp

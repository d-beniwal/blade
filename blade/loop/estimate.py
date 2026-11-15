"""Estimate: fit the simulator's HIDDEN quantities so that it reproduces what was observed on the real beamline.

The simulator has controls (which sync copies from the real beamline) and a hidden truth (what the controls alone cannot tell: the energy readback offset Th1, the
Th2 detuning, the undulator gap error, the orbit steering ...). `fit` varies chosen truth parameters until the simulator's prediction of the observations matches the
data (bounded least squares; uncertainties from the Jacobian). Observations can come from anywhere that is READ-ONLY: a snapshot, a frame, a scan the operator ran
(ion-chamber vs control), a logged scan.

    obs = [scan_observation("gap scan", "und.gap", gaps, counts, ic="icB1"), value_observation("mu_t", predict_mu_t, 1.31, 0.02)]
    res = fit(model, ["gap_err_mm", "th1_err_mdeg"], obs);  apply_estimate(model, res)

What each parameter needs (identifiability): gap_err_mm <- a gap scan (peak position); th2_err_deg <- a Th2 scan; th1_err_mdeg <- mu_t of a foil near its edge;
steer_xp/yp_urad <- beam centroid minus footprint centre on a camera frame. A single IC value cannot separate these (flux depends on all of them): `fit` reports
the sigma, and a parameter with a huge sigma is NOT identified by the data given."""
from dataclasses import dataclass, field
from typing import Callable
import numpy as np
from scipy.optimize import least_squares
from ..instrument.sim import SimInstrument

# name -> (lo, hi, characteristic scale for the finite-difference step)
PARAMS = {
    "th1_err_mdeg": (-8.0, 8.0, 0.5),
    "th2_err_deg": (-0.012, 0.012, 0.0004),
    "gap_err_mm": (-0.12, 0.12, 0.004),
    "steer_xp_urad": (-30.0, 30.0, 2.0),
    "steer_yp_urad": (-30.0, 30.0, 2.0),
}


@dataclass
class Observation:
    name: str
    predict: Callable[[SimInstrument], np.ndarray]        # runs on a private noiseless copy of the model with the trial truth
    observed: np.ndarray
    sigma: float | np.ndarray = 1.0
    normalize: bool = False                               # compare curves up to a common scale (ion-chamber gain/scale unknown)

    def residual(self, pred):
        pred, obs = np.atleast_1d(np.asarray(pred, float)), np.atleast_1d(np.asarray(self.observed, float))
        if self.normalize:
            pred, obs = pred / max(float(pred.max()), 1e-12), obs / max(float(obs.max()), 1e-12)
        return ((pred - obs) / self.sigma).ravel()


def scan_observation(name, control, xs, ys, ic="icB1", sigma=0.02, detector=None, normalize=True, setup=None):
    """A scan: the operator (or a log) moved `control` through `xs` IN THIS ORDER (order matters for the undulator's hysteresis) and recorded `ys` with a detector -
    by default the ion chamber `ic`, or any `detector(model) -> float`. `setup(model)` runs first (e.g. put the foil in). Ion-chamber curves are compared
    NORMALISED (gain unknown; sigma = relative noise of the normalised curve); pass normalize=False for absolute quantities such as mu_t."""
    xs = [float(x) for x in xs]
    det = detector or (lambda m: m.ic_kHz(ic))

    def predict(m):
        if setup:
            setup(m)
        out = []
        for x in xs:
            m.set(control, x)
            out.append(det(m))
        return np.array(out, float)
    return Observation(name, predict, np.asarray(ys, float), sigma, normalize=normalize)


def edge_scan_observation(energies, mu_t_values, element="Re", sigma=0.03):
    """E_scan: with the foil in, the HEM readout energy stepped through `energies` (keV) and the foil's mu*t recorded: the step position pins the energy offset (Th1)."""
    return scan_observation(f"E_scan({element})", "hem.energy", energies, mu_t_values, detector=lambda m: m.mu_t(), normalize=False, sigma=sigma,
                            setup=lambda m: m.set("foilB.pos", element))


def value_observation(name, predict, value, sigma):
    """A single measured number and a function giving the model's prediction of it (`predict(model) -> float`)."""
    return Observation(name, lambda m: np.array([predict(m)], float), np.array([value], float), sigma)


def mu_t_observation(value, element="Re", sigma=0.03):
    """mu*t of the calibration foil (operators' Emon: ln of the IC ratio across the foil), measured at the CURRENT controls; constrains the energy offset."""
    def predict(m):
        m.set("foilB.pos", element)
        v = np.mean([m.mu_t() for _ in range(3)])
        return float(v)
    return value_observation(f"mu_t({element})", predict, value, sigma)


def frame_observation(name, camera, features, sigma_px=3.0, bin_=4):
    """Camera-frame features (beam centroid minus footprint centre, in px of the binned frame) measured on the real frame; the model renders its own frame and the SAME
    analysis gives the prediction. `features` = (dx_px, dy_px) from `beam_offset_px`."""
    def predict(m):
        return np.array(beam_offset_px(m.frame(camera, bin_=bin_)), float)
    return Observation(name, predict, np.array(features, float), sigma_px)


def beam_offset_px(img):
    """(dx, dy) in frame px: the intensity centroid of the beam minus the centre of its footprint box. Steering moves the beam inside the window the slits cut, so this
    changes smoothly with steering (the 'hotspot' pixel jumps in coarse blocks and is dominated by the texture's hot core, which makes a poor fit feature)."""
    from ..analysis.frame import analyze_frame
    an = analyze_frame(img, 1.0)
    if not an.get("beam"):
        return (0.0, 0.0)
    b = an["box_px"]
    return (an["centroid_px"]["x"] - (b["x0"] + b["x1"]) / 2.0, an["centroid_px"]["y"] - (b["y0"] + b["y1"]) / 2.0)


@dataclass
class FitResult:
    params: list
    values: dict
    sigma: dict
    cost_before: float
    cost_after: float
    n_obs: int
    converged: bool
    identified: dict = field(default_factory=dict)       # parameter -> True if sigma is small compared with its bounds

    def to_dict(self):
        return {"values": self.values, "sigma": self.sigma, "identified": self.identified, "cost_before": self.cost_before, "cost_after": self.cost_after,
                "n_obs": self.n_obs, "converged": self.converged}


def _truth_get(m, name):
    return float(m.world.s["truth"][name])


def _truth_set(m, name, v):
    m.world.s["truth"][name] = float(v)


def fit(model: SimInstrument, params, observations, max_nfev=60):
    """Fit `params` (names in PARAMS) of `model`'s hidden truth to `observations`. The model itself is NOT modified (use `apply_estimate`)."""
    for p in params:
        if p not in PARAMS:
            raise ValueError(f"unknown parameter {p!r}; known: {sorted(PARAMS)}")
    base = model.copy(noiseless=True)
    x0 = np.array([_truth_get(base, p) for p in params])
    lo, hi = np.array([PARAMS[p][0] for p in params]), np.array([PARAMS[p][1] for p in params])
    step = np.array([PARAMS[p][2] for p in params])
    x0 = np.clip(x0, lo + 1e-9, hi - 1e-9)

    def resid_x(x):
        out = []
        for ob in observations:
            m = base.copy(noiseless=True)
            for p, v in zip(params, x):
                _truth_set(m, p, v)
            out.append(ob.residual(ob.predict(m)))
        return np.concatenate(out)

    # optimise in u = (x - x0) / step: the finite-difference step is then ~0.5 * step for every parameter (a relative step on a value near 0 would be ~1e-8,
    # below the resolution of image features) and the problem is well scaled
    def resid(u):
        return resid_x(x0 + step * u)

    def jac(u, h=0.5):                       # forward difference with an ABSOLUTE step h in u (= h * step in the parameter), independent of the scipy version
        f0 = resid(u)
        cols = []
        for i in range(len(u)):
            du = np.zeros(len(u))
            du[i] = h if u[i] + h <= (hi[i] - x0[i]) / step[i] else -h
            cols.append((resid(u + du) - f0) / du[i])
        return np.array(cols).T

    r0 = resid(np.zeros(len(params)))
    sol = least_squares(resid, np.zeros(len(params)), jac=jac, bounds=((lo - x0) / step, (hi - x0) / step), max_nfev=max_nfev, loss="soft_l1", f_scale=2.0)
    sol.x = x0 + step * sol.x
    sol.jac = sol.jac / step[None, :]
    J = sol.jac
    dof = max(len(sol.fun) - len(params), 1)
    try:
        cov = np.linalg.inv(J.T @ J) * float(np.sum(sol.fun ** 2) / dof)
        sig = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        sig = np.full(len(params), np.inf)
    ident = {p: bool(s < 0.25 * (hi[i] - lo[i])) for i, (p, s) in enumerate(zip(params, sig))}
    return FitResult(list(params), dict(zip(params, map(float, sol.x))), dict(zip(params, map(float, sig))), float(0.5 * np.sum(r0 ** 2)), float(0.5 * np.sum(sol.fun ** 2)),
                     len(sol.fun), bool(sol.success), ident)


def apply_estimate(model: SimInstrument, result: FitResult, only_identified=True):
    """Write the fitted truth into `model` (only parameters the data identified, by default). Returns the names applied."""
    done = []
    for p, v in result.values.items():
        if only_identified and not result.identified.get(p, False):
            continue
        _truth_set(model, p, v)
        done.append(p)
    model._post()
    return done

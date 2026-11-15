"""Stand-in 'real' beamline for dry runs and tests: a simulator with its OWN hidden truth, scanned by a pretend operator. SIMULATION ONLY.

The loop is validated (and demonstrated in the GUI / by agents) without touching anything real: `stand_in(seed)` is the 'real' beamline (random hidden truth,
thermally settled, HEM at the foil edge, nominal gap), `operator_scans(real)` is the data an operator would record on it (E scan, gap scan, Th2 scan), the
model is a different simulator that knows none of it. `dry_run` runs the closed loop and reports how much better the stand-in's TRUE state is afterwards."""
import numpy as np
from ..instrument.sim import SimInstrument
from . import estimate as ES, run as R
from .. import procedures as P


def stand_in(seed=21, element="Re"):
    real = SimInstrument(seed=seed, scenario="startup")
    P.select_edge(real, element)
    g = P.nominal_gap(real)["gap_mm"]
    P.open_gap(real, g)
    real.set("und.gap", g)                       # the operators' starting point: edge energy, nominal gap
    real.wait(3 * 3600)                          # a beamline that has been running: the mono is thermally settled
    return real


def operator_scans(real, el="Re"):
    """What an operator would record (scans through the control system); here the stand-in is scanned. Leaves `real` where it was."""
    E0 = float(real.ctl("hem.energy"))
    g0, th0 = real.ctl("und.gap"), real.ctl("hem.th2_offset")
    Es = list(np.linspace(E0 - 0.12, E0 + 0.12, 33))
    foil0 = real.ctl("foilB.pos")
    real.set("foilB.pos", el)
    mus = []
    for e in Es:
        real.set("hem.energy", float(e))
        mus.append(real.mu_t())
    real.set("foilB.pos", foil0)
    real.set("hem.energy", E0)
    xs = [g0 + 0.6] + list(np.linspace(g0 + 0.3, g0 - 0.3, 41))
    ys = []
    for x in xs:
        real.set("und.gap", float(x))
        ys.append(real.ic_kHz("icB1"))
    real.set("und.gap", g0)
    xt = list(np.linspace(th0 - 0.005, th0 + 0.005, 21))
    yt = []
    for x in xt:
        real.set("hem.th2_offset", float(x))
        yt.append(real.ic_kHz("icB1"))
    real.set("hem.th2_offset", th0)
    return [ES.edge_scan_observation(Es, mus, el), ES.scan_observation("gap scan", "und.gap", xs, ys, "icB1", 0.02), ES.scan_observation("th2 scan", "hem.th2_offset", xt, yt, "icB1", 0.02)]


def score(r):
    """Lower is better; from the stand-in's hidden truth (scoring only): gap, Th2, energy and flux in units of their tolerances."""
    t = r.truth()
    return abs(t["undulator_gap_error_mm"]) / 0.02 + abs(t["th2_error_deg"]) / 0.001 + abs(t["energy_mu_t_error"]) / 0.05 + (1 - t["source_flux_relative_to_best"]) / 0.02


PARAMS = ["th1_err_mdeg", "gap_err_mm", "th2_err_deg"]


def dry_run(seed=21, model_seed=0, iterations=2):
    """Closed loop on a stand-in. Returns a JSON-safe summary: scores before/after each turn, the proposal, the estimates against the stand-in's hidden truth."""
    real = stand_in(seed)
    model = SimInstrument(seed=model_seed, scenario="startup")
    truth = dict(real.world.s["truth"])
    truth["th1_err_mdeg"] = (real.world.th1_true_offset() - real.sim["hem"]["th1_offset_deg"]) * 1e3
    hist = R.closed_loop(real, model, P.tune_energy_flux, observe=operator_scans, estimate_params=PARAMS, max_iter=iterations, score=score, tol=2.5)
    t = real.truth()
    turns = []
    for h in hist:
        r = h["result"]
        turns.append({"iteration": h["iteration"], "score_before": h.get("score_before"), "score_after": h.get("score_after"), "status": r.status,
                      "estimate": r.estimate, "proposal": r.proposal.to_dict() if r.proposal else None, "notes": r.notes})
    return {"simulation_only": True, "seed": seed, "model_seed": model_seed, "truth": {k: truth[k] for k in PARAMS}, "turns": turns,
            "final": {"gap_error_mm": t["undulator_gap_error_mm"], "th2_error_deg": t["th2_error_deg"], "mu_t_error": t["energy_mu_t_error"], "flux_vs_best": t["source_flux_relative_to_best"]}}

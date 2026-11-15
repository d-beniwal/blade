"""Loop tools for the MCP server. NOTHING here commands the real beamline: `loop_real_snapshot` performs channel-access GETs only (blade/instrument/readonly.py),
everything else works on files or on simulators. Read playbooks/loop.md first (resource blade://playbook/loop)."""
import json
from pathlib import Path
from ..paths import ROOT, RUNS_DIR
from ..registry import tool, playbook
from ..instrument import pvmap
from ..instrument.sim import SimInstrument
from . import sync as S, estimate as ES, optimize as O, demo, mapcheck
from .. import procedures as P

playbook("loop", ROOT / "playbooks" / "loop.md")
PROCEDURES = {"tune_energy_flux": P.tune_energy_flux, "gap_scan": P.gap_scan, "th2_scan": P.th2_scan, "calibrate_energy": P.calibrate_energy, "nominal_gap": P.nominal_gap}


def _dir(sub):
    d = RUNS_DIR / "loop" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool("loop", needs_run=False)
def loop_status(twin: str = "1-ID") -> dict:
    """What the read-only sync can see: the control<->PV mapping (only 'verified' entries with numeric scale+offset feed the simulator), the ion chambers with a
    scaler channel, and the safety statement. Call first."""
    return {"read_only": True, "writes_to_real_beamline": "none exist in BLADE (user decision 2026-11-15)", "coverage": pvmap.coverage(twin),
            "how_to_verify": "compare one live readback with the panel, then edit beamline_twins/<bl>/control_pv_map.json (status, scale, offset, note) and add the evidence to verify.json"}


@tool("loop", needs_run=False)
def loop_real_snapshot(camera: str | None = None, backend: str = "auto") -> dict:
    """READ-ONLY snapshot of the real beamline: channel-access GETs of every mapped PV and ion-chamber channel (+ one camera frame if `camera` is given). Saves it under
    runs/loop/snapshots/ and returns the summary (what was usable, what is unmapped and why). Needs pyepics or the EPICS `caget` and the beamline network. Use only
    when the user is on the beamline network and wants a read."""
    from ..instrument.epics import EpicsReader
    inst = EpicsReader(backend=backend)
    snap = S.take(inst, camera=camera, frame_dir=_dir("frames") if camera else None)
    f = S.save(snap, _dir("snapshots") / f"snapshot_{snap.utc.replace(':', '')}.json")
    return {"saved": f.name, "utc": snap.utc, "n_controls_usable": len(snap.controls), "unmapped": snap.unmapped, "ics_kHz_raw": snap.ics_kHz, "frame": snap.frame}


@tool("loop", needs_run=False)
def loop_list_snapshots() -> dict:
    """Snapshots saved by loop_real_snapshot (newest last)."""
    fs = sorted(_dir("snapshots").glob("snapshot_*.json"))
    return {"snapshots": [f.name for f in fs]}


@tool("loop", needs_run=False)
def loop_propose(snapshot: str, procedure: str = "tune_energy_flux", scans: list[dict] | None = None, estimate: list[str] | None = None, model_seed: int = 0) -> dict:
    """Sync a fresh simulator to a saved snapshot, optionally fit hidden quantities from operator scans, run `procedure` on a COPY and return the PROPOSED control
    changes (data only - nothing is applied anywhere). scans: [{"kind": "gap"|"th2"|"edge", "xs": [...], "ys": [...], "ic": "icB1", "element": "Re"}] (the data an operator
    recorded; order matters); estimate: parameter names to fit (th1_err_mdeg, gap_err_mm, th2_err_deg, steer_xp_urad, steer_yp_urad). procedure: one of %s.""" % sorted(PROCEDURES)
    if snapshot != Path(snapshot).name or procedure not in PROCEDURES:
        raise ValueError(f"snapshot must be a file name from loop_list_snapshots and procedure one of {sorted(PROCEDURES)}")
    d = json.loads((_dir("snapshots") / snapshot).read_text())
    snap = S.Snapshot(**{k: d[k] for k in ("source", "utc", "controls", "unmapped", "ics_kHz", "raw", "frame") if k in d})
    model = SimInstrument(seed=model_seed, scenario="startup")
    rep = S.apply(model, snap)
    est = None
    if scans and estimate:
        obs = []
        for sc in scans:
            k = sc["kind"]
            if k == "gap":
                obs.append(ES.scan_observation("gap scan", "und.gap", sc["xs"], sc["ys"], sc.get("ic", "icB1")))
            elif k == "th2":
                obs.append(ES.scan_observation("th2 scan", "hem.th2_offset", sc["xs"], sc["ys"], sc.get("ic", "icB1")))
            elif k == "edge":
                obs.append(ES.edge_scan_observation(sc["xs"], sc["ys"], sc.get("element", "Re")))
            else:
                raise ValueError(f"unknown scan kind {k!r}")
        res = ES.fit(model, estimate, obs)
        est = {**res.to_dict(), "applied": ES.apply_estimate(model, res)}
    prop = O.propose(model, PROCEDURES[procedure])
    return {"sync": {k: rep[k] for k in ("assigned", "skipped", "not_in_snapshot", "assumptions")}, "estimate": est, "proposal": prop.to_dict(),
            "note": "PROPOSAL ONLY: BLADE cannot command the beamline; a person applies it. Values are in simulator coordinates unless 'real_display' is given (verified mapping)."}


@tool("loop", needs_run=False)
def loop_dry_run(seed: int = 21, model_seed: int = 0, iterations: int = 2) -> dict:
    """Run the whole loop on a STAND-IN beamline (a simulator with a different hidden truth): sync, estimate from operator scans, propose, apply to the stand-in,
    repeat. Reports the score of the stand-in's true state before/after and how well the hidden quantities were recovered. SIMULATION ONLY."""
    out = demo.dry_run(seed, model_seed, iterations)
    (_dir("dryrun") / "last.json").write_text(json.dumps(out, default=float))
    return out


@tool("loop", needs_run=False)
def loop_mapping_evidence(probe_csv: str) -> dict:
    """From a CSV written by the read-only probe (beamline_twins/tools/probe_readonly.py --run), propose control<->PV transforms by comparing motor soft limits with the
    simulator's limits. EVIDENCE ONLY: a person must confirm and edit control_pv_map.json."""
    p = Path(probe_csv)
    if not p.is_file():
        raise ValueError(f"{probe_csv}: no such file")
    return {"evidence": mapcheck.limits_evidence(mapcheck.read_probe_csv(p))}

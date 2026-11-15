"""Run: one turn of the loop - read, sync, estimate, optimise, propose - and, for dry runs on a stand-in beamline, apply and go round again.

    result = iterate(real, model, procedure, ...)        # `real` is read-only (EpicsReader) or a stand-in simulator; `model` is a SimInstrument
    history = closed_loop(stand_in, model, procedure, observe=..., max_iter=3)   # ONLY for a stand-in 'real' that can be written (a simulator)

`iterate` never writes to `real`. `closed_loop` applies the proposal to `real` through `Proposal.apply`, which raises ReadOnlyError on a read-only instrument, so it
cannot be pointed at the real beamline: it stops with status 'proposal only'. The observations that identify the hidden quantities (scans, a frame) come from the
caller via `observe(real) -> [Observation]` (for the real beamline: data the operator took or the logs hold; for a stand-in: the test scans it)."""
from dataclasses import dataclass, field
from ..instrument.base import Instrument, ReadOnlyError
from ..instrument.sim import SimInstrument
from . import sync as S, estimate as ES, optimize as O


@dataclass
class IterationResult:
    snapshot: S.Snapshot
    sync: dict
    comparison: dict
    estimate: dict | None
    proposal: O.Proposal | None
    status: str = "ok"
    notes: list = field(default_factory=list)

    def to_dict(self):
        return {"status": self.status, "snapshot": {k: v for k, v in self.snapshot.to_dict().items() if k != "raw"}, "sync": self.sync, "comparison": self.comparison,
                "estimate": self.estimate, "proposal": self.proposal.to_dict() if self.proposal else None, "notes": self.notes}


def iterate(real: Instrument, model: SimInstrument, procedure=None, proc_args=(), proc_kw=None, observe=None, estimate_params=None, camera=None, log=None):
    """One read -> sync -> (estimate) -> propose turn. `log(kind, msg, data)` (e.g. Run.log) receives a short record of each stage."""
    say = log or (lambda *a, **k: None)
    snap = S.take(real, camera=camera)
    say("snapshot", f"read {len(snap.controls)} controls, {len(snap.ics_kHz)} ion chambers from {snap.source}; {len(snap.unmapped)} not usable", {"unmapped": list(snap.unmapped)})
    rep = S.apply(model, snap)
    say("sync", f"model took {len(rep['assigned'])} controls; {len(rep['not_in_snapshot'])} kept their previous values (real value unknown)", {"skipped": rep["skipped"]})
    cmp_ = S.compare(model, snap)
    est = None
    notes = []
    if observe and estimate_params:
        obs = observe(real)
        res = ES.fit(model, estimate_params, obs)
        applied = ES.apply_estimate(model, res)
        est = {**res.to_dict(), "applied": applied}
        say("estimate", "fitted " + ", ".join(f"{k}={v:+.4g}" for k, v in res.values.items()) + f"; applied {applied}", est)
        if len(applied) < len(estimate_params):
            notes.append(f"parameters not identified by the data (not applied): {sorted(set(estimate_params) - set(applied))}")
    prop = None
    if procedure is not None:
        prop = O.propose(model, procedure, *proc_args, **(proc_kw or {}))
        say("proposal", f"{prop.procedure}: {len(prop.changes)} change(s) proposed", prop.to_dict())
    return IterationResult(snap, rep, cmp_, est, prop, "ok", notes)


def closed_loop(real: Instrument, model: SimInstrument, procedure, proc_args=(), proc_kw=None, observe=None, estimate_params=None, camera=None, max_iter=3,
                score=None, tol=None, log=None):
    """Iterate and APPLY on `real` until `score(real)` (lower is better) is below `tol` or max_iter turns. Refuses a read-only `real` (stops with 'proposal only')."""
    history = []
    for k in range(max_iter):
        r = iterate(real, model, procedure, proc_args, proc_kw, observe, estimate_params, camera, log)
        entry = {"iteration": k, "result": r}
        if score is not None:
            entry["score_before"] = score(real)
        try:
            r.proposal.apply(real)
        except ReadOnlyError as e:
            r.status = "proposal only"
            r.notes.append(str(e))
            history.append(entry)
            break
        if score is not None:
            entry["score_after"] = score(real)
        history.append(entry)
        if score is not None and tol is not None and entry["score_after"] < tol:
            break
    return history

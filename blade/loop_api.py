"""Data for the Sync & Loop page (`/loop`): the read-only mapping coverage, saved real-beamline snapshots, and the stand-in dry run. Nothing here commands anything; the
dry run only changes simulators."""
import json
from . import config as cfg
from .paths import RUNS_DIR
from .instrument import pvmap


def _dir(sub):
    d = RUNS_DIR / "loop" / sub
    d.mkdir(parents=True, exist_ok=True)
    return d


def state(twin=None):
    twin = twin or "1-ID"
    ctl = pvmap.load_controls(twin)
    snaps = []
    for f in sorted(_dir("snapshots").glob("snapshot_*.json"))[-10:]:
        try:
            d = json.loads(f.read_text())
            snaps.append({"name": f.name, "utc": d.get("utc"), "source": d.get("source"), "usable": len(d.get("controls", {})), "unmapped": len(d.get("unmapped", {})),
                          "ics": len(d.get("ics_kHz", {}))})
        except Exception:
            continue
    last = _dir("dryrun") / "last.json"
    return {"twin": twin, "read_only": True,
            "mapping": [{"control": n, "pv": e.pv_name, "unit": e.unit, "status": e.status, "usable": e.usable, "why": e.why_unusable(), "scale": e.scale, "offset": e.offset,
                         "source": e.source, "note": e.note} for n, e in ctl.items()],
            "ics": [{"ic": i, "counts_pv": c.counts_pv, "time_pv": c.time_pv, "preamp": c.preamp} for i, c in pvmap.load_ics(twin).items()],
            "snapshots": snaps, "dry_run": json.loads(last.read_text()) if last.is_file() else None}


def dry_run(body):
    from .loop import demo
    out = demo.dry_run(int(body.get("seed", 21)), int(body.get("model_seed", 0)), int(body.get("iterations", 2)))
    (_dir("dryrun") / "last.json").write_text(json.dumps(out, default=float))
    return out

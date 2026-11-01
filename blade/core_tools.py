"""Core BLADE tools (module-independent): profiles, run lifecycle, notes. Registered through blade.registry."""
import json
from . import config as cfg
from .registry import tool
from .session import Run
from .paths import RUNS_DIR


@tool("core", needs_run=False)
def list_profiles() -> dict:
    """List beamline profiles with their stations (hutches), cameras and enabled backends. Call first to learn what can be run."""
    out = {}
    for n in cfg.profiles():
        p = json.loads((cfg.profile_dir(n) / "default_config.json").read_text())
        out[n] = {"beamline": p.get("beamline"), "backends": p.get("backends"), "cameras": sorted(p.get("cameras", {})),
                  "stations": sorted(p.get("stations", {})), "default_station": p.get("default_station")}
    return {"default": cfg.PROFILE, "profiles": out}


@tool("core", moves=True, needs_run=False)
def new_run(profile: str | None = None, station: str | None = None, backend: str = "sim", camera: str | None = None, seed: int = 0) -> dict:
    """Start a new run (becomes the current run). backend='sim' (default) is the simulator; backend='epics' connects to the REAL beamline and must be used
    only when the user said they are on the beamline and authorised hardware access. `station` is the hutch whose motors/geometry apply (default: the
    profile's default_station); `camera` is a camera name from the profile (e.g. gh1)."""
    run = Run.create(backend, seed, None, camera, profile, station)
    return {"run": run.dir.name, "dir": str(run.dir), "profile": cfg.PROFILE, "station": cfg.STATION, "beamline": cfg.BEAMLINE,
            "backend": backend, "camera": camera, "pixel_um": cfg.PIXEL_UM}


@tool("core")
def run_status(run) -> dict:
    """Current positions, last fit, calibration and status of the run."""
    return {"run": run.dir.name, "profile": cfg.PROFILE, "station": cfg.STATION, "positions": run.inst.positions(),
            "last_fit": run.state["last_fit"], "calibration": run.state["calibration"], "status": run.state["status"],
            "events": run.n_events(), "pixel_um": cfg.PIXEL_UM}


@tool("core", needs_run=False)
def list_runs() -> dict:
    """List run ids (oldest first) and which one is current."""
    cur = (RUNS_DIR / "CURRENT").read_text().strip() if (RUNS_DIR / "CURRENT").exists() else None
    return {"current": cur, "runs": sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir()) if RUNS_DIR.exists() else []}


@tool("core")
def add_note(run, text: str) -> dict:
    """Add a note to the run log (shown live in `blade gui`). Use it to explain what you are doing and why."""
    run.log("note", text, {"agent": True})
    return {"ok": True}


@tool("core")
def finish_run(run, status: str = "ok", summary: str = "") -> dict:
    """Mark the run finished (status e.g. 'ok' or 'failed') with a short summary."""
    run.state["status"] = status
    run.save()
    run.log("run_finished", f"Run finished: {status}. {summary}", {"status": status, "summary": summary})
    return {"ok": True}

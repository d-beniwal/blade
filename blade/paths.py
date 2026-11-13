"""Filesystem anchors for BLADE.

Two worlds, kept apart on purpose:

* the CODE tree (`ROOT`, this repo): profiles, playbooks, the beamline-twin descriptions, tools. Shareable with other people / beamlines.
* the KNOWLEDGE tree (`KNOWLEDGE_ROOT`, outside the repo): everything that may be sensitive or unpublished - experiment logs and their index, the
  knowledge base built from them, raw beamline data, reference photos/screenshots, alignment run folders, scratch work.

Nothing in the code tree hard-codes where the knowledge tree is. It is resolved, first match wins, from:

  1. `$BLADE_KNOWLEDGE` (the root folder), else
  2. the `root` key of a knowledge config file: `$BLADE_KNOWLEDGE_CONFIG`, else `<repo>/knowledge.json` (git-ignored, per workstation),
     else `~/.config/blade/knowledge.json`, else
  3. `<repo>/knowledge_local/` (git-ignored; an empty tree, so a fresh clone works and never touches anyone else's data).

Inside the root the layout is `<root>/<beamline>/<kind>/` (beamline = twin id, default `1-ID`; kinds in `KINDS`). Any single kind can be
re-pointed with the config key `paths` (`{"kb": "/x/kb"}` or per beamline `{"kb": {"1-ID": "/x/kb"}}`) or its own environment variable
(`KINDS[kind]["env"]`; legacy names `KB_ROOT`, `BLADE_RUNS`, `BLADE_LOGINDEX_DIR` still work). `python -m blade.paths` prints what resolves to what.
See `knowledge.example.json`."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent                       # repo root (holds profiles/, playbooks/, beamline_twins/)
DEFAULT_PROFILE = "s1id"
DEFAULT_BEAMLINE = os.environ.get("BLADE_BEAMLINE", "1-ID")         # twin id; names the per-beamline folder inside the knowledge root

# kind -> (folder name inside <root>/<beamline>/, env override, what it holds)
KINDS = {
    "kb":          dict(dir="kb",          env=("BLADE_KB", "KB_ROOT"),   doc="knowledge base built from the logs: kb.sqlite, images, facts, procedures"),
    "logs_index":  dict(dir="logs_index",  env=("BLADE_LOGINDEX_DIR",),   doc="extracted text + SQLite index of the experiment logs"),
    "logs_src":    dict(dir="logs_src",    env=("BLADE_LOGS_SRC",),       doc="the raw experiment-log documents (docx/xlsx/...) the index is built from"),
    "data":        dict(dir="data",        env=("BLADE_DATA",),           doc="raw beamline data: scans, frames, pictures, screenshots"),
    "twin_photos": dict(dir="twin_photos", env=("BLADE_TWIN_PHOTOS",),    doc="reference photos / CS-Studio screenshots cited by the twin's photos.json"),
    "runs":        dict(dir="runs",        env=("BLADE_RUNS",),           doc="alignment run folders, live frames, virtual-beamline sessions"),
    "edits":       dict(dir="edits",       env=("BLADE_EDITS",),          doc="audit log (edits.jsonl) of every change made through the GUI editor"),
    "scratch":     dict(dir="scratch",     env=("BLADE_SCRATCH",),        doc="exploratory work and caches"),
    # not produced by BLADE: an existing checkout/download that is only READ
    "cs_displays": dict(dir="cs_displays", env=("BLADE_CS_DISPLAYS",),    doc="the beamline's CS-Studio/Phoebus display files (.bob) = ground truth for device and PV names"),
}


def _config():
    cands = ([Path(os.environ["BLADE_KNOWLEDGE_CONFIG"]).expanduser()] if os.environ.get("BLADE_KNOWLEDGE_CONFIG") else []) \
        + [ROOT / "knowledge.json", Path.home() / ".config" / "blade" / "knowledge.json"]
    for f in cands:
        if f.is_file():
            try:
                return f, json.loads(f.read_text())
            except ValueError as e:
                raise SystemExit(f"{f}: not valid JSON ({e})")
    return None, {}


CONFIG_FILE, _CFG = _config()


def _resolve_root():
    if os.environ.get("BLADE_KNOWLEDGE"):
        return Path(os.environ["BLADE_KNOWLEDGE"]).expanduser()
    if _CFG.get("root"):
        return Path(_CFG["root"]).expanduser()
    return ROOT / "knowledge_local"


KNOWLEDGE_ROOT = _resolve_root()


def knowledge_dir(kind, beamline=None):
    """Folder for `kind` ('kb', 'runs', ...) of `beamline` (twin id; default 1-ID). The folder may not exist (callers decide what that means)."""
    if kind not in KINDS:
        raise KeyError(f"unknown knowledge kind '{kind}' (known: {', '.join(KINDS)})")
    bl = beamline or DEFAULT_BEAMLINE
    for v in KINDS[kind]["env"]:
        if os.environ.get(v):
            return Path(os.environ[v]).expanduser()
    o = (_CFG.get("paths") or {}).get(kind)
    if isinstance(o, dict):
        o = o.get(bl)
    if o:
        return Path(o).expanduser()
    return KNOWLEDGE_ROOT / bl / KINDS[kind]["dir"]


RUNS_DIR = knowledge_dir("runs")
PROFILES_DIRS = ([Path(os.environ["BLADE_PROFILES_DIR"]).expanduser()] if os.environ.get("BLADE_PROFILES_DIR") else []) + [ROOT / "profiles"]
TWINS_DIR = Path(os.environ["BLADE_TWINS_DIR"]).expanduser() if os.environ.get("BLADE_TWINS_DIR") else ROOT / "beamline_twins"   # beamline twins (profile key "twin" names the folder)


def describe(beamline=None):
    """[(kind, path, exists, doc)] for every kind - what `python -m blade.paths` prints."""
    return [(k, knowledge_dir(k, beamline), knowledge_dir(k, beamline).exists(), v["doc"]) for k, v in KINDS.items()]


if __name__ == "__main__":
    print(f"code tree      : {ROOT}")
    print(f"knowledge root : {KNOWLEDGE_ROOT}   (config: {CONFIG_FILE or 'none -> default'}; override with $BLADE_KNOWLEDGE)")
    print(f"beamline       : {DEFAULT_BEAMLINE}")
    for k, p, ex, doc in describe():
        print(f"  {k:12s} {'ok     ' if ex else 'MISSING'} {p}   # {doc}")

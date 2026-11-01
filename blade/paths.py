"""Filesystem anchors for BLADE, all derived from this file's location (the repo can live anywhere)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent                       # repo root (holds profiles/, playbooks/, runs/)
RUNS_DIR = Path(os.environ["BLADE_RUNS"]).expanduser() if os.environ.get("BLADE_RUNS") else ROOT / "runs"
PROFILES_DIRS = ([Path(os.environ["BLADE_PROFILES_DIR"]).expanduser()] if os.environ.get("BLADE_PROFILES_DIR") else []) + [ROOT / "profiles"]
DEFAULT_PROFILE = "s1id"

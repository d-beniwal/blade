#!/usr/bin/env python
"""Run BLADE from a checkout without installing it:  python -I launch.py align <cmd> ...   |   python -I launch.py gui   |   python -I launch.py profiles
(After `pip install -e .` the same commands are just `blade align ...`, `blade gui`, `blade profiles`.)"""
import sys
sys.dont_write_bytecode = True   # no __pycache__ dirs outside runs/
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blade.cli import main  # noqa: E402

if __name__ == "__main__":
    main()

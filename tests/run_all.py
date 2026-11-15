"""Run every tests/test_*.py (each is a standalone script) in parallel and print a pass/fail table.
Simulation/offline only - no test touches hardware.

    python tests/run_all.py                 # all tests
    python tests/run_all.py physics vbl     # only tests whose name contains one of the words
    python tests/run_all.py --timeout 900   # per-test timeout in seconds (default 600)
    python tests/run_all.py --json out.json # also write the results
Exit status is 0 only if every selected test passed."""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(path, timeout):
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-I", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        status, out = ("pass" if p.returncode == 0 else "FAIL"), p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        status, out = "TIMEOUT", (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    return {"test": path.name, "status": status, "seconds": round(time.time() - t0, 1), "tail": out.strip().splitlines()[-6:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words", nargs="*")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--json")
    a = ap.parse_args()
    tests = sorted((ROOT / "tests").glob("test_*.py")) + [ROOT / "tests" / "scripted_agent.py"]
    tests = [t for t in tests if t.exists() and (not a.words or any(w in t.name for w in a.words))]
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda t: run(t, a.timeout), tests))
    for r in res:
        print(f"{r['status']:8s} {r['seconds']:7.1f}s  {r['test']}")
        if r["status"] != "pass":
            for line in r["tail"]:
                print("          |", line)
    bad = [r for r in res if r["status"] != "pass"]
    print(f"\n{len(res) - len(bad)}/{len(res)} passed")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

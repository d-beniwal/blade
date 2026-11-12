"""GUI launch test (no hardware, stdlib only): `serve(open_page=...)` opens the right URL, a second launch reuses the running GUI instead of
starting another, a foreign process on the port is reported, and the `blade-gui` script parses and passes its arguments through.
Run: python -I tests/test_gui_launch.py"""
import os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade import gui


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


opened = []
gui.webbrowser.open = lambda url, *a, **k: opened.append(url) or True     # never open a real browser in the test

port = free_port()
threading.Thread(target=gui.serve, args=(port, "twin"), daemon=True).start()
for _ in range(50):
    if gui._is_blade_gui(port):
        break
    time.sleep(0.1)
assert gui._is_blade_gui(port)
time.sleep(0.6)
assert opened == [f"http://localhost:{port}/twin"], opened                 # opened the twin page once the server was listening

gui.serve(port, "monitor")                                                  # second launch: returns immediately (does not block), reuses the first
assert opened[-1] == f"http://localhost:{port}/" and len(opened) == 2, opened
gui.serve(port)                                                             # no --open: nothing opened
assert len(opened) == 2

foreign = socket.socket()                                                   # something that is not BLADE on the port -> clear error, no crash loop
foreign.bind(("127.0.0.1", 0)); foreign.listen(1)
fp = foreign.getsockname()[1]
try:
    gui.serve(fp, "monitor")
    raise AssertionError("expected SystemExit")
except SystemExit as e:
    assert "in use by something else" in str(e), e
foreign.close()
assert not gui._is_blade_gui(free_port())

try:
    gui.serve(free_port(), "nope")
    raise AssertionError("expected ValueError")
except ValueError:
    pass

# the launcher script: valid bash, and `twin` / `--port` reach `blade gui` (checked end to end with a fake browser via $BROWSER)
script = ROOT / "blade-gui"
assert os.access(script, os.X_OK)
assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
log = Path(tempfile.mkdtemp()) / "browser.log"
fake = Path(tempfile.mkdtemp()) / "fakebrowser.sh"
fake.write_text(f'#!/bin/sh\necho "$1" >> {log}\n'); fake.chmod(0o755)
p2 = free_port()
env = {**os.environ, "BROWSER": f"{fake} %s", "BLADE_PYTHON": sys.executable}
proc = subprocess.Popen([str(script), "twin", "--port", str(p2)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(80):
        if log.exists() and log.read_text().strip():
            break
        time.sleep(0.1)
    assert log.read_text().strip() == f"http://localhost:{p2}/twin", log.read_text()
    assert gui._is_blade_gui(p2)
finally:
    proc.terminate(); proc.wait(timeout=5)
print("GUI launch OK")

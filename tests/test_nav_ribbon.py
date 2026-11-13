"""Navigation ribbon test (no hardware, stdlib only): every GUI page is served with the left ribbon, the right tab is marked current, and the pages no longer carry their own
links to each other. Run: python -I tests/test_nav_ribbon.py"""
import os, re, sys, tempfile, threading, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade import nav
from blade.gui import H, _Server

srv = _Server(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
get = lambda path: urllib.request.urlopen(base + path).read().decode()


def ok(msg):
    print("PASS", msg)


# the tabs: the four the user asked for, in that order (the beamline twin follows so its viewer stays reachable)
labels = [t[2] for t in nav.TABS]
assert labels[:4] == ["Virtual Beamline", "Physics", "Knowledge Base", "Alignment Monitor"], labels
paths = {t[0]: t[1] for t in nav.TABS}
assert paths == {"vbl": "/vbl", "physics": "/physics", "kb": "/kb", "monitor": "/", "twin": "/twin"}, paths
ok("tabs: " + ", ".join(labels))

# every page: exactly one ribbon with all tabs, the right one current, theme variables used, body offset present
for tab, path in paths.items():
    html = get(path)
    assert html.count('id="bnav"') == 1 and html.count('id="blade-nav-css"') == 1, path
    for t, p in paths.items():
        assert f'<a href="{p}"' in html.split('id="bnav"', 1)[1].split("</nav>", 1)[0], (path, p)
    cur = re.findall(r'<a href="([^"]*)"[^>]*aria-current="page"', html)
    assert cur == [path], (path, cur)
    assert "var(--panel" in html and f"padding-left:{nav.WIDTH}px" in html
    assert html.split("<body>", 1)[1].startswith('<nav id="bnav"'), path      # the ribbon is the first thing in the body
ok("every page is served with one ribbon, the right tab current, theme variables, body offset")

# the page files themselves carry no links to the other pages any more (the ribbon is the main navigation)
for f in ("gui.html", "twin.html", "kb.html", "vbl.html", "physics.html"):
    src = (ROOT / "blade" / f).read_text()
    bad = re.findall(r'<a href="/(?:twin|kb|vbl|physics)?"', src)
    assert not bad, (f, bad)
    assert "alignment monitor</a>" not in src and "knowledge base →" not in src and "virtual beamline →" not in src, f
ok("no per-page navigation shortcuts left in the five pages")

# injecting twice does not duplicate; a page without <head>/<body> is refused rather than silently left without navigation
once = nav.inject("<html><head></head><body><p>x</p></body></html>", "kb")
assert nav.inject(once, "kb") == once
try:
    nav.inject("<p>fragment</p>", "kb"); raise SystemExit("FAIL: fragment accepted")
except AssertionError:
    pass
ok("injection is idempotent and refuses pages it cannot navigate")
print("nav ribbon OK")

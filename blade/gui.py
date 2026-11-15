"""Local web GUI (stdlib + numpy): the virtual beamline (/ and /vbl), the read-only sync & loop (/loop), the beamline twin of any profile (/twin), the physics catalogue (/physics) and the local
knowledge base (/kb: procedures, log images, log text; read-only).
Everything here is read-only for real hardware - it never commands anything; /vbl only changes the SIMULATED session (runs/vbl/).
Run:  python -I gui.py [--port 8765]   then open http://localhost:8765  (virtual beamline: /vbl, twin viewer: /twin, physics: /physics, knowledge base: /kb)"""
import json
import mimetypes
import sys
import threading
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .paths import RUNS_DIR
from . import config as cfg
from . import twin_api, edit_api, kb_curate
from . import vbl_api, loop_api
from . import kb_api, nav
from .vbl import physics_doc



class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        page = {"/": ("vbl.html", "vbl"), "/vbl": ("vbl.html", "vbl"), "/twin": ("twin.html", "twin"), "/kb": ("kb.html", "kb"), "/physics": ("physics.html", "physics"), "/loop": ("loop.html", "loop")}.get(u.path)
        if page:                                       # every page gets the left navigation ribbon (blade/nav.py); pages carry no links to each other
            return self._send(nav.inject((Path(__file__).parent / page[0]).read_text(), page[1]), "text/html; charset=utf-8")
        if u.path == "/api/vbl/physics":
            return self._send(physics_doc.payload())
        if u.path == "/api/vbl/physics/curve":         # curve computed by calling the real simulator functions on an 'aligned' world
            try:
                return self._send(physics_doc.curve(q.get("name", "")))
            except ValueError as e:
                return self._send({"error": str(e)}, code=404)
        if u.path == "/kb-image":                      # /kb-image?sha=<id>&w=<px>: found through the KB's images table only (never a client path)
            try:
                data, mime = kb_api.image_bytes(q.get("sha", ""), int(q.get("w", 0) or 0))
                return self._send(data, mime)
            except FileNotFoundError as e:
                return self._send({"error": str(e), "available": False}, code=404)
            except Exception as e:
                return self._send({"error": str(e)}, code=400)
        if u.path.startswith("/api/kb/"):
            return self._kb(u.path[len("/api/kb/"):], q)
        if u.path == "/api/loop/state":
            return self._send(loop_api.state(q.get("twin")))
        if u.path == "/api/vbl/state":
            return self._send(vbl_api.state_payload(reveal=q.get("reveal") == "1"))
        if u.path == "/api/vbl/frame":
            try:
                png = vbl_api.frame_png(q.get("camera", "gh1"), int(q.get("bin", 2)), float(q["exposure"]) if q.get("exposure") else None, q.get("auto", "1") == "1")
                return self._send(png, "image/png")
            except Exception as e:
                return self._send({"error": str(e)}, code=400)
        if u.path == "/api/profiles":
            return self._send(twin_api.profile_list())
        if u.path == "/api/twin":                      # pure read of profile + twin files; does not change the globally loaded profile
            try:
                return self._send(twin_api.twin_payload(q.get("profile") or cfg.PROFILE))
            except ValueError as e:
                return self._send({"error": str(e)}, code=404)
        if u.path.startswith("/twin-photo/"):          # /twin-photo/<twin>/<photo id or file>: only photos indexed in the twin's photos.json
            parts = u.path.split("/")[2:]
            f = twin_api.photo_file(parts[0], parts[1]) if len(parts) == 2 else None
            if f:
                return self._send(f.read_bytes(), mimetypes.guess_type(str(f))[0] or "image/jpeg")
            return self._send({"error": "photo not found"}, code=404)
        self._send({"error": "not found"}, code=404)


    def _kb(self, name, q):
        """Read-only knowledge-base queries (see blade/kb_api.py); errors come back as {"error": ...} with a 4xx code."""
        try:
            if name == "status":
                return self._send(kb_api.status())
            a = lambda k, d="": q.get(k, d)
            routes = {
                "facets": lambda: kb_api.facets(),
                "procs": lambda: kb_api.proc_list(),
                "proc": lambda: kb_api.proc_get(a("id")),
                "procsearch": lambda: kb_api.proc_search(a("q")),
                "numbers": lambda: kb_api.numbers(a("q")),
                "images": lambda: kb_api.image_search(a("q"), a("cls"), a("subject"), a("camera"), a("hutch"), a("source"), a("device"), int(a("offset", 0)), int(a("limit", 60))),
                "imginfo": lambda: kb_api.image_info(a("sha")),
                "text": lambda: kb_api.text_search(a("q"), a("year"), a("kind"), int(a("offset", 0)), int(a("limit", 60))),
                "docs": lambda: kb_api.doc_list(a("q"), a("year"), a("kind")),
                "outline": lambda: kb_api.doc_outline(a("doc")),
                "cite": lambda: kb_api.cite_window(a("c"), int(a("ctx", 8))),
                "window": lambda: kb_api.doc_window(a("doc"), int(a("a", 1)), int(a("b", 1)), int(a("ctx", 0))),
                "labelkeys": lambda: {"keys": kb_curate.keys(kb_api.KB_DIR)},
                "labelvalues": lambda: {"key": a("key"), "values": kb_curate.values(kb_api.KB_DIR, a("key"))},
                "curation": lambda: kb_curate.history(kb_api.KB_DIR, int(a("limit", 50))),
            }
            if name not in routes:
                return self._send({"error": f"unknown knowledge-base query {name!r}"}, code=404)
            return self._send(routes[name]())
        except FileNotFoundError as e:
            return self._send({"error": str(e), "available": False}, code=404)
        except Exception as e:
            return self._send({"error": f"{type(e).__name__}: {e}"}, code=400)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/edit":                   # guarded device-info editor (blade/edit_api.py); local-only, needs the confirmed flag
                try:
                    edit_api.check_request(self.headers)
                    return self._send(edit_api.apply_edit(body))
                except edit_api.EditError as e:
                    return self._send({"error": str(e)}, code=400)
            if u.path == "/api/kb/curate":              # remove / change / add knowledge-base labels, logged so they persist (blade/kb_curate.py); same guard as /api/edit
                try:
                    kb_curate.check_request(self.headers)
                    return self._send(kb_curate.submit(kb_api.KB_DIR, body, confirmed=body.get("confirm") is True))
                except (kb_curate.CurateError, FileNotFoundError) as e:
                    return self._send({"error": str(e)}, code=400)
            if u.path == "/api/loop/dryrun":            # a stand-in SIMULATOR plays the real beamline; nothing real is touched
                return self._send(loop_api.dry_run(body))
            if u.path == "/api/vbl/set":
                return self._send(vbl_api.apply_set(body))
            if u.path == "/api/vbl/reset":
                return self._send(vbl_api.reset(body))
            if u.path == "/api/vbl/projections":
                return self._send(vbl_api.projections(body))
            if u.path == "/api/vbl/profile":
                return self._send(vbl_api.profile(body))
            if u.path == "/api/vbl/tool":
                return self._send(vbl_api.run_tool(body))
        except Exception as e:
            return self._send({"error": f"{type(e).__name__}: {e}"}, code=400)
        self._send({"error": "not found"}, code=404)


class _Server(ThreadingHTTPServer):
    request_queue_size = 64          # the default backlog (5) resets connections when a page fires several requests at once while a handler is busy


PAGES = {"vbl": "/vbl", "loop": "/loop", "twin": "/twin", "kb": "/kb", "physics": "/physics"}


def _is_blade_gui(port):
    """True if a BLADE GUI already answers on this port (so a second launch can just open it)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/profiles", timeout=1.5) as r:
            return "profiles" in json.loads(r.read())
    except Exception:
        return False


def serve(port=8765, open_page=None):
    """Serve the GUI. open_page = None | "vbl" | "loop" | "twin" | "kb" | "physics": also open it in the default browser. If a BLADE GUI is already running on the
    port, do not start a second one: just open it (or print its address) and return."""
    if open_page not in (None, *PAGES):
        raise ValueError(f"page must be one of {sorted(PAGES)}")
    url = f"http://localhost:{port}{PAGES.get(open_page, '/vbl')}"
    try:
        srv = _Server(("127.0.0.1", port), H)
    except OSError:
        if _is_blade_gui(port):
            print(f"BLADE GUI is already running: {url}", flush=True)
            if open_page:
                webbrowser.open(url)
            return
        raise SystemExit(f"port {port} is in use by something else; choose another with --port N")
    print(f"BLADE GUI on http://localhost:{port}  (virtual beamline: /vbl, sync & loop: /loop, twin viewer: /twin, physics: /physics, knowledge base: /kb; runs dir: {RUNS_DIR}); Ctrl+C to stop", flush=True)
    if open_page:                                   # the socket is already listening, so the browser's request just queues until serving starts
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBLADE GUI stopped", flush=True)


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
    serve(port, "vbl" if "--open" in sys.argv else None)

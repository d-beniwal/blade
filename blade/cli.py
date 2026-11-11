"""BLADE command line.   blade align <cmd> ...   alignment module (see playbooks/alignment.md; every command prints JSON)
                       blade gui [--port N]      live monitor of runs/*/events.jsonl (read-only)
                       blade mcp [--http]        MCP server exposing every BLADE capability to agents (stdio; --http = streamable-http)
                       blade profiles            list beamline profiles (profiles/<name>/default_config.json)"""
import sys
from . import __version__


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""
    if cmd == "align":
        from .alignment.cli import main as align_main
        return align_main(argv[1:])
    if cmd == "gui":
        from .gui import serve
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8765
        return serve(port)
    if cmd == "mcp":
        from .mcp_server import serve
        return serve("streamable-http" if "--http" in argv else "stdio")
    if cmd == "profiles":
        import json
        from . import config as cfg
        out = {}
        for n in cfg.profiles():
            p = json.loads((cfg.profile_dir(n) / "default_config.json").read_text())
            out[n] = {"beamline": p.get("beamline"), "backends": p.get("backends"), "cameras": sorted(p.get("cameras", {})),
                    "stations": sorted(p.get("stations", {})), "default_station": p.get("default_station"), "twin": p.get("twin")}
        print(json.dumps({"default": cfg.PROFILE, "profiles": out}, indent=2))
        return
    if cmd in ("-V", "--version", "version"):
        print(f"blade {__version__}")
        return
    print(__doc__)
    raise SystemExit(0 if cmd in ("", "-h", "--help") else 2)


if __name__ == "__main__":
    main()

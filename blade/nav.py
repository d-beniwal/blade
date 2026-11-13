"""The GUI's main navigation: a vertical ribbon on the left edge of every page (served by blade/gui.py, which injects it into each page).

One source of truth: add a page by adding one entry to TABS (and a route in gui.py). Pages no longer carry their own links to the other pages. The ribbon uses the
theme variables every page defines (--panel, --line, --ink, --mute, --acc, --accbg), so it follows the chosen theme. Nothing here talks to hardware."""
import html

# (id, path, label, icon paths: stroke-only 24x24 SVG)
TABS = [
    ("vbl", "/vbl", "Virtual Beamline", '<path d="M2 12h6M8 6v12M12 6v4M12 14v4M12 12h5"/><rect x="17" y="8" width="5" height="8" rx="1"/>'),
    ("physics", "/physics", "Physics", '<path d="M2 12c3-8 5-8 8 0s5 8 8 0c1-2 2-3 4-3"/><path d="M2 20h20" opacity=".5"/>'),
    ("kb", "/kb", "Knowledge Base", '<path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3z"/><path d="M5 17a3 3 0 013-3h11"/>'),
    ("monitor", "/", "Alignment Monitor", '<path d="M2 12h4l3-8 4 16 3-8h6"/>'),
    ("twin", "/twin", "Beamline Twin", '<rect x="3" y="4" width="7" height="5" rx="1"/><rect x="14" y="15" width="7" height="5" rx="1"/><path d="M6.5 9v3h11v3"/>'),
]
WIDTH = 74

CSS = f"""<style id="blade-nav-css">
body{{padding-left:{WIDTH}px!important}}
#bnav{{position:fixed;left:0;top:0;bottom:0;width:{WIDTH}px;z-index:40;background:var(--panel,#fff);border-right:1px solid var(--line,#dde2ea);display:flex;flex-direction:column;align-items:stretch;padding:8px 0;gap:2px;overflow-y:auto;font:11px/1.15 system-ui,sans-serif}}
#bnav .mark{{text-align:center;font:700 11px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.14em;color:var(--mute,#677386);padding:4px 0 10px}}
#bnav a{{display:flex;flex-direction:column;align-items:center;gap:3px;padding:8px 2px 7px;text-align:center;text-decoration:none;color:var(--mute,#677386);border-left:3px solid transparent}}
#bnav a svg{{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}}
#bnav a span{{font-size:10px;font-weight:600}}
#bnav a:hover{{background:var(--accbg,#e6eefb);color:var(--ink,#1b2330)}}
#bnav a[aria-current=page]{{background:var(--accbg,#e6eefb);color:var(--acc,#2160c4);border-left-color:var(--acc,#2160c4)}}
#bnav a:focus-visible{{outline:2px solid var(--acc,#2160c4);outline-offset:-2px}}
@media(max-width:640px){{body{{padding-left:46px!important}}#bnav{{width:46px}}#bnav a span{{display:none}}#bnav .mark{{display:none}}}}
</style>"""


def ribbon(active):
    """The ribbon HTML with `active` (a TABS id) marked as the current page."""
    items = []
    for tid, path, label, icon in TABS:
        cur = ' aria-current="page"' if tid == active else ""
        items.append(f'<a href="{path}" title="{html.escape(label)}"{cur}><svg viewBox="0 0 24 24" aria-hidden="true">{icon}</svg><span>{html.escape(label)}</span></a>')
    return f'<nav id="bnav" aria-label="BLADE pages"><div class="mark">BLADE</div>{"".join(items)}</nav>'


def inject(page, active):
    """Put the ribbon (and its CSS) into a page's HTML: CSS before </head>, the nav right after <body>."""
    if 'id="bnav"' in page:
        return page
    assert "</head>" in page and "<body>" in page, "page has no <head>/<body> to inject the navigation into"
    return page.replace("</head>", CSS + "</head>", 1).replace("<body>", "<body>" + ribbon(active), 1)

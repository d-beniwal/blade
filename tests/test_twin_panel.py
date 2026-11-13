"""The element info panel is ONE uniform structure for every twin element (blade/twin_panel.py): long name, channel groups in a fixed order,
open items; names are only taken from reliable sources and doubtful ones are never assigned.
Usage: python -I tests/test_twin_panel.py"""
import os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BLADE_RUNS"] = tempfile.mkdtemp()
from blade import twin_api, twin_panel, edit_api

t = twin_api.twin_payload("s1id")["twin"]
els = {e["id"]: e for e in t["elements"]}
# every element: a long name (longer than / different from the short one) and the panel record
for i, e in els.items():
    assert e.get("long_name") and e["long_name"] != e["name"], i
    p = e["panel_info"]
    assert set(p) == {"channels", "open", "templates", "src_txt"}, i
    groups = [g["group"] for g in p["channels"]]
    assert groups == [g for g in twin_panel.GROUPS if g in groups], (i, groups)      # fixed order, no unknown group
    for g in p["channels"]:
        for r in g["rows"]:
            assert r["pv"] and r["src"] and all(s in twin_panel.SRC_TXT for s in r["src"]), (i, r)
    assert p["channels"] or any(o["kind"] == "gap" for o in p["open"]), i              # nothing silently empty
    for o in p["open"]:
        assert o["kind"] in ("verify", "conflict", "ambiguous", "gap"), (i, o)
# resolved names (sources: display / log panels / slit bindings / code)
def row(eid, pv):
    return next(r for g in els[eid]["panel_info"]["channels"] for r in g["rows"] if r["pv"].split(" ")[0] == pv)
assert row("lens1C", "1idc:m99")["label"] == "X" and "log: lens1_x" in row("lens1C", "1idc:m99")["also"]
assert row("alCRL", "1idb:m20")["label"] == "B20 L4B X"                         # named from the log-panel window title (tier A)
assert row("wbSlits", "1ida:m5")["label"].startswith("X+ blade")                  # from the top-panel slit binding
assert row("tomoB", "1idb:m52")["label"] == "x"                                   # from the twin's own controls
assert row("saxs", "1ide1:m52")["label"] == "SAX DetX"
assert row("stopC", "1idcAMCI:m9")["label"] == ""                                 # unnamed everywhere: stays open
# never guessed: PVs that several log windows claim stay unnamed and are listed as ambiguous
a = row("saxs", "1ide1:m51")
assert a["label"] == "pin_x"                                                      # code role only (twin controls), not a log window name
amb = [o["text"] for o in els["d2E"]["panel_info"]["open"] if o["kind"] == "ambiguous"]
assert any("1ide:m6" in x for x in amb), amb
# to-verify items show up on their element; verified ones do not
assert any(o["kind"] == "verify" for o in els["lens1C"]["panel_info"]["open"])
assert any(o["kind"] == "verify" for o in els["lens5C"]["panel_info"]["open"])
assert row("lens5C", "1idc:m99")["shared_with"] == ["lens1C"] or "lens1C" in row("lens5C", "1idc:m99")["shared_with"]
# long_name is editable through the guarded editor
assert "long_name" in edit_api.ELEMENT_FIELDS
n_open = sum(len(e["panel_info"]["open"]) for e in els.values())
print("twin panel ok:", len(els), "elements,", n_open, "open items")

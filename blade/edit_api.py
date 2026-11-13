"""Guarded editing of device information from the GUI (Beamline Twin page): twin elements, profile cameras/motors, and the to-verify list.

Safety, on purpose strict: only allow-listed fields; the request must carry `confirm: true` (the GUI sets it only after the user accepted the
confirmation dialog) AND the value the user saw (`old`) - if the file changed in the meantime the edit is refused; the request must come from the
local machine (Host header) with the custom header X-Blade-Edit (a cross-site page cannot send it without a CORS preflight, which is not answered);
a twin edit that makes `twin.py check` report errors is rolled back; every applied edit is appended to the audit log (knowledge tree, `edits`).
Edits go to the tracked files (`beamline_twins/<id>/hutches/*.json`, `profiles/<p>/default_config.json`, `beamline_twins/<id>/verify.json`), so git shows each change.
Never connects to anything."""
import json
import re
import time

from . import config as cfg
from . import paths
from . import twin_api

CONF = ("confirmed", "seen", "code", "inferred", "unseen")
VSTATUS = ("unverified", "verified", "wrong")
# element field -> kind of value
ELEMENT_FIELDS = {"name": "str", "long_name": "str", "dev": "str", "pv": "str", "conf": CONF, "z_m": "num?", "z_conf": "str", "z_src": "str", "notes": "str", "controls": "json", "state": "json"}
VERIFY_FIELDS = {"status": VSTATUS, "note": "str"}
PROFILE_PATHS = [(re.compile(r"^cameras\.[\w-]+\.(pv_prefix|note|hutch)$"), "str"), (re.compile(r"^cameras\.[\w-]+\.pixel_um$"), "num"),
                 (re.compile(r"^stations\.[\w-]+\.motors\.[\w-]+\.(pv|name|role)$"), "str")]


class EditError(ValueError):
    pass


def check_request(headers):
    """Local-only + custom header (see module doc). Raises EditError."""
    host = (headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise EditError("edits are only accepted from the local machine (Host header)")
    if headers.get("X-Blade-Edit") != "1":
        raise EditError("missing X-Blade-Edit header")


def _parse(kind, text):
    """Typed value from the text the user entered."""
    if kind == "str":
        return text
    if isinstance(kind, tuple):
        if text not in kind:
            raise EditError(f"must be one of {', '.join(kind)}")
        return text
    if kind in ("num", "num?"):
        if kind == "num?" and text.strip() in ("", "null"):
            return None
        try:
            return float(text) if re.search(r"[.eE]", text) else int(text)
        except ValueError:
            raise EditError("must be a number" + (" (or empty / null)" if kind == "num?" else ""))
    if kind == "json":
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError as e:
            raise EditError(f"not valid JSON: {e}")
    raise EditError("unsupported field type")


def _atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def dump_hutch(d, tail="\n"):
    """Hutch JSON in the repo's hand-formatted style: one line per top-level key, `elements` one element per line (so git diffs stay small)."""
    out = ["{"]
    items = list(d.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if k == "elements" and isinstance(v, list):
            body = ",\n".join("    " + json.dumps(x, ensure_ascii=False) for x in v)
            out.append(f'  {json.dumps(k)}: [\n{body}\n  ]{comma}')
        else:
            out.append(f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}{comma}')
    out.append("}")
    return "\n".join(out) + tail


def _tail(s):
    return s[len(s.rstrip()):] or "\n"


def _find_element(tdir, eid):
    for f in sorted((tdir / "hutches").glob("*.json")):
        d = json.loads(f.read_text())
        for e in d.get("elements", []):
            if e.get("id") == eid:
                return f, d, e
    raise EditError(f"element '{eid}' not found")


def _audit(rec):
    d = paths.knowledge_dir("edits")
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "edits.jsonl", "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _twin_check(tid):
    tm = twin_api._twin_module()
    return tm.check(tm.load(tid, paths.TWINS_DIR))[0]


def apply_edit(body):
    """body: {target: element|profile|verify, twin|profile, id, field|path, old, new, confirm}. Returns {ok, old, new, file}."""
    if body.get("confirm") is not True:
        raise EditError("not confirmed (the confirmation dialog must be accepted)")
    target = body.get("target")
    new_text = body.get("new")
    if not isinstance(new_text, str):
        raise EditError("'new' must be the text entered by the user")
    tid = body.get("twin") or "1-ID"
    tdir = paths.TWINS_DIR / tid
    if not (tdir / "beamline.json").is_file():
        raise EditError(f"unknown twin '{tid}'")
    if target == "element":
        field = body.get("field")
        if field not in ELEMENT_FIELDS:
            raise EditError(f"field '{field}' is not editable (allowed: {', '.join(ELEMENT_FIELDS)})")
        f, d, e = _find_element(tdir, body.get("id"))
        old = e.get(field)
        if not _same(old, body.get("old")):
            raise EditError("the value changed since you opened it - reload and try again")
        new = _parse(ELEMENT_FIELDS[field], new_text)
        if _same(old, new):
            raise EditError("no change")
        if field == "name" and not (new or "").strip():
            raise EditError("the name cannot be empty")
        orig = f.read_text()
        if new is None:
            e.pop(field, None)
        else:
            e[field] = new
        _atomic(f, dump_hutch(d, _tail(orig)))
        errs = _twin_check(tid)
        if errs:
            _atomic(f, orig)
            raise EditError("rejected, the twin check fails with this value: " + "; ".join(errs[:3]))
        where = f"{f.name}:{e['id']}.{field}"
    elif target == "profile":
        path = body.get("path") or ""
        kind = next((k for rx, k in PROFILE_PATHS if rx.match(path)), None)
        if kind is None:
            raise EditError(f"'{path}' is not an editable profile field")
        pname = body.get("profile") or "s1id"
        f = cfg.profile_dir(pname) / "default_config.json"
        orig = f.read_text()
        d = json.loads(orig)
        node = d
        keys = path.split(".")
        for k in keys[:-1]:
            if not isinstance(node, dict) or k not in node:
                raise EditError(f"profile has no '{path}'")
            node = node[k]
        old = node.get(keys[-1])
        if not _same(old, body.get("old")):
            raise EditError("the value changed since you opened it - reload and try again")
        new = _parse(kind, new_text)
        if _same(old, new):
            raise EditError("no change")
        node[keys[-1]] = new
        _atomic(f, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        where = f"{pname}:{path}"
    elif target == "verify":
        field = body.get("field")
        if field not in VERIFY_FIELDS:
            raise EditError("only 'status' and 'note' of a to-verify item are editable")
        f = tdir / "verify.json"
        orig = f.read_text()
        d = json.loads(orig)
        it = next((x for x in d["items"] if x["id"] == body.get("id")), None)
        if it is None:
            raise EditError(f"no to-verify item '{body.get('id')}'")
        old = it.get(field, "" if field == "note" else None)
        if not _same(old, body.get("old")):
            raise EditError("the value changed since you opened it - reload and try again")
        new = _parse(VERIFY_FIELDS[field], new_text)
        if _same(old, new):
            raise EditError("no change")
        if field == "status" and new == "verified" and not (it.get("note") or "").strip():
            raise EditError("add the evidence to 'note' first: an item is only 'verified' with evidence written down")
        it[field] = new
        if field == "status":
            it["status_changed"] = time.strftime("%Y-%m-%d")
        _atomic(f, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        where = f"verify.json:{it['id']}.{field}"
    else:
        raise EditError(f"unknown target '{target}'")
    _audit({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "where": where, "old": old, "new": new, "twin": tid})
    return {"ok": True, "where": where, "old": old, "new": new}


def verify_items(tid):
    f = paths.TWINS_DIR / tid / "verify.json"
    return json.loads(f.read_text())["items"] if f.is_file() else []

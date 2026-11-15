"""Curation of the knowledge-base labels: remove, change and add labels, with the changes made PERMANENT.

The curation log `<kb>/curation.jsonl` (knowledge tree, outside the repo; one JSON object per line, append-only) is the source of truth for every
human correction. Each operation is applied to `kb.sqlite` immediately, and `replay()` re-applies the whole log (idempotent) after anything that can
bring the old labels back - an ingest, a vision labelling pass - so a correction made once is never lost. Used by the GUI (`/kb`, POST
/api/kb/curate), by `knowledge_base/kb.py curate ...` and by tests. Never touches hardware.

Operations (`op`), all on the `labels` table (key = class | subject | camera | hutch | device | feature | any new key):
  rename        {key, old, new}   every label `key=old` (any image, any source) becomes `key=new`           (e.g. subject pin -> tomopin)
  delete_value  {key, value}      remove every label `key=value`
  set           {sha, key, value} this image: replace ALL its labels of that key by one human label (confidence 1)
  add           {sha, key, value} this image: add a human label (it outranks rule/vision labels of the key in `label_best`)
  remove        {sha, key[, value]} this image: delete its labels of that key (only those with that value when given)
The GUI path needs `confirm: true`, a local Host header and the X-Blade-Edit header (same guard as blade/edit_api.py); a copy of the database is
made once per day before the first change (`kb.sqlite.bak-curate-<date>`)."""
import json
import re
import sqlite3
import time
from pathlib import Path

LOG = "curation.jsonl"
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
OPS = ("rename", "delete_value", "set", "add", "remove")


class CurateError(ValueError):
    pass


def check_request(headers):
    """Local-only + custom header, like blade/edit_api.py (a cross-site page cannot send X-Blade-Edit without a CORS preflight, which is not answered)."""
    host = (headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise CurateError("label edits are only accepted from the local machine (Host header)")
    if headers.get("X-Blade-Edit") != "1":
        raise CurateError("missing X-Blade-Edit header")


def _db(kb_dir):
    return Path(kb_dir) / "kb.sqlite"


def _con(kb_dir):
    db = _db(kb_dir)
    if not db.is_file():
        raise CurateError(f"knowledge base not found at {db}")
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _text(v, what, maxlen=300):
    if not isinstance(v, str) or not v.strip():
        raise CurateError(f"{what} must be non-empty text")
    v = v.strip()
    if len(v) > maxlen or re.search(r"[\x00-\x1f]", v):
        raise CurateError(f"{what} is too long or has control characters")
    return v


def _key(v):
    if not isinstance(v, str) or not KEY_RE.match(v.strip()):
        raise CurateError("key must be letters/digits/underscore, starting with a letter (e.g. subject)")
    return v.strip()


def _sha(con, v):
    if not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{6,64}", v):
        raise CurateError("bad image id")
    rows = con.execute("SELECT sha256 FROM images WHERE sha256 LIKE ?", (v + "%",)).fetchall()
    if len(rows) != 1:
        raise CurateError(f"image {v!r} matches {len(rows)} images")
    return rows[0][0]


def normalize(con, body):
    """Validated, canonical operation dict (full sha) from a request / CLI body. Raises CurateError."""
    op = body.get("op")
    if op not in OPS:
        raise CurateError(f"op must be one of {', '.join(OPS)}")
    out = {"op": op, "key": _key(body.get("key"))}
    if op == "rename":
        out["old"], out["new"] = _text(body.get("old"), "old value"), _text(body.get("new"), "new value")
        if out["old"] == out["new"]:
            raise CurateError("old and new value are the same")
    elif op == "delete_value":
        out["value"] = _text(body.get("value"), "value")
    else:
        out["sha"] = _sha(con, body.get("sha"))
        if op in ("set", "add"):
            out["value"] = _text(body.get("value"), "value")
        elif body.get("value") not in (None, ""):
            out["value"] = _text(body.get("value"), "value")
    return out


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def apply_op(con, o, now=None):
    """Apply one canonical operation; returns the number of label rows changed (0 when already in the wanted state)."""
    now = now or _now()
    op, key = o["op"], o["key"]
    if op == "rename":
        return con.execute("UPDATE labels SET value=? WHERE key=? AND value=?", (o["new"], key, o["old"])).rowcount
    if op == "delete_value":
        return con.execute("DELETE FROM labels WHERE key=? AND value=?", (key, o["value"])).rowcount
    if not con.execute("SELECT 1 FROM images WHERE sha256=?", (o["sha"],)).fetchone():
        return 0                                                    # image no longer in this knowledge base: nothing to do
    if op == "remove":
        if o.get("value"):
            return con.execute("DELETE FROM labels WHERE sha256=? AND key=? AND value=?", (o["sha"], key, o["value"])).rowcount
        return con.execute("DELETE FROM labels WHERE sha256=? AND key=?", (o["sha"], key)).rowcount
    n = 0
    if op == "set":
        n = con.execute("DELETE FROM labels WHERE sha256=? AND key=? AND NOT (source='human' AND value=?)", (o["sha"], key, o["value"])).rowcount
    if con.execute("SELECT 1 FROM labels WHERE sha256=? AND key=? AND value=? AND source='human'", (o["sha"], key, o["value"])).fetchone():
        return n
    con.execute("INSERT INTO labels VALUES(?,?,?,?,?,?,?)", (o["sha"], key, o["value"], "human", 1.0, now, "curated"))
    return n + 1


def _would_change(con, o):
    """Rows the operation would touch (for the confirmation dialog and the log)."""
    op, key = o["op"], o["key"]
    q = {"rename": ("SELECT COUNT(*) FROM labels WHERE key=? AND value=?", (key, o.get("old"))),
         "delete_value": ("SELECT COUNT(*) FROM labels WHERE key=? AND value=?", (key, o.get("value")))}
    if op in q:
        sql, a = q[op]
        return con.execute(sql, a).fetchone()[0]
    return con.execute("SELECT COUNT(*) FROM labels WHERE sha256=? AND key=?", (o["sha"], key)).fetchone()[0]


def read_log(kb_dir):
    f = Path(kb_dir) / LOG
    out = []
    if f.is_file():
        for i, ln in enumerate(f.read_text().splitlines(), 1):
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    raise CurateError(f"{f}:{i}: not valid JSON (fix or delete that line)")
    return out


def _backup(kb_dir, con):
    dst = Path(kb_dir) / f"kb.sqlite.bak-curate-{time.strftime('%Y-%m-%d')}"
    if not dst.exists():
        b = sqlite3.connect(dst)
        con.backup(b)
        b.close()


def submit(kb_dir, body, confirmed=False):
    """Validate, log and apply one operation. Returns {"ok", "op", "changed", "was"}; `confirmed` must be true (the GUI sets it after its dialog)."""
    if not confirmed:
        raise CurateError("not confirmed")
    con = _con(kb_dir)
    try:
        o = normalize(con, body)
        was = _would_change(con, o)
        if was == 0 and o["op"] in ("rename", "delete_value", "remove"):
            raise CurateError("nothing matches: no such label")
        _backup(kb_dir, con)
        rec = dict(o, t=_now(), was=was)
        if body.get("note"):
            rec["note"] = _text(body["note"], "note")
        with open(Path(kb_dir) / LOG, "a") as f:             # log FIRST: if applying fails midway, replay() completes it
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        n = apply_op(con, o, rec["t"])
        con.commit()
        return {"ok": True, "op": o, "changed": n, "was": was}
    finally:
        con.close()


def replay(kb_dir, quiet=False):
    """Re-apply the whole curation log in order (idempotent). Call after ingest / labelling. Returns {"ops", "changed"}."""
    log = read_log(kb_dir)
    if not log or not _db(kb_dir).is_file():
        return {"ops": len(log), "changed": 0}
    con = _con(kb_dir)
    try:
        changed = 0
        for rec in log:
            changed += apply_op(con, {k: v for k, v in rec.items() if k not in ("t", "was", "note")}, rec.get("t"))
        con.commit()
    finally:
        con.close()
    if not quiet:
        print(f"curation: {len(log)} logged operation(s) re-applied, {changed} label row(s) changed")
    return {"ops": len(log), "changed": changed}


def values(kb_dir, key):
    """[(value, n_images)] of the BEST label per image for `key`, for the label manager."""
    con = _con(kb_dir)
    try:
        return [[r[0], r[1]] for r in con.execute("SELECT value, COUNT(*) n FROM label_best WHERE key=? GROUP BY value ORDER BY n DESC", (key,))]
    finally:
        con.close()


def keys(kb_dir):
    con = _con(kb_dir)
    try:
        return [[r[0], r[1]] for r in con.execute("SELECT key, COUNT(DISTINCT sha256) n FROM labels GROUP BY key ORDER BY n DESC")]
    finally:
        con.close()


def history(kb_dir, limit=50):
    return {"log": read_log(kb_dir)[-int(limit):][::-1]}

"""One uniform 'what can I address on this element' record for the twin viewer's info panel (`/twin`).

Every element, whatever its kind, gets the SAME structure so the eye finds things in the same place:
  channels = [{group, rows: [{label, pv, detail, src, flags, shared_with, candidates}]}]   groups in the fixed order GROUPS
  open     = [{kind: verify|gap|ambiguous|shared, text}]                                       what is still unresolved (never guessed)
The sources are merged per PV: CS-Studio display (pv_map.json: labels, slit axes, IC read-outs, camera IOCs), log-panel labels/limits/steps
(panel_registry, tier A only, already folded into pv_map by tools/pvmap.py) and the twin element's own `dev` / `pv` / `controls` (mpe_bluesky code,
user statements). Pure function, reads nothing, connects to nothing."""
import re

GROUPS = ("Device & prefix", "Motors & axes", "Slit axes", "Read-outs", "Signals & switches")
MOTOR_RX = re.compile(r"(?::|\b)m\d+(?:\.\w+)?$")          # 1ide1:m20, 1mini2:hxp:c0:m3
GENERIC_ROLE = re.compile(r"^(motors?|motors_display|hexapod_axes|table_motors|circle_motors|other)(\[\d+\]|_m\d+)?$|^motor_m\d+$")   # structure words, not axis names
PV_RX = re.compile(r"^[\w\-]+(?::[\w\-\.\$\(\)]+)+")      # contains a colon-separated EPICS-looking name
SRC_ORDER = ("display", "log", "code", "user")
SRC_TXT = {"display": "CS-Studio display", "log": "log panels (tier A)", "code": "mpe_bluesky / twin", "user": "user statement"}


def _pvkey(s):
    """'1id:userTran3 (field .a)' -> '1id:userTran3'; '.VAL'/'.RBV' suffix dropped so a record and its field merge."""
    s = str(s).split(" ")[0]
    return re.sub(r"\.(VAL|RBV|C)$", "", s)


def _flatten(ctl):
    """Twin `controls` (heterogeneous: role -> pv | {pv, access, units, ...} | [pv, ...] | nested | names/conflicts) -> (rows, extra_text)."""
    rows, extra = [], []
    names = {}

    def put(role, pv, meta=None):
        rows.append({"role": role, "pv": pv, "meta": meta or {}})

    def walk(prefix, v):
        for k, x in v.items():
            role = f"{prefix}{k}"
            if k == "names" and isinstance(x, dict):
                names.update({p: n for p, n in x.items()})
            elif k == "conflicts" and isinstance(x, dict):
                extra.extend(("conflict", f"{a}: {b}") for a, b in x.items())
            elif k in ("conflicts", "note", "notes") or (isinstance(x, str) and not PV_RX.match(x) and " " in x):
                extra.append(("gap", f"{role}: {x}"))
            elif isinstance(x, str):
                put(role, x)
            elif isinstance(x, list) and x and all(isinstance(i, str) for i in x):
                for i, p in enumerate(x):
                    put(f"{role}[{i + 1}]", p)
            elif isinstance(x, dict) and "pv" in x:
                put(role, x["pv"], {a: b for a, b in x.items() if a != "pv"})
            elif isinstance(x, dict):
                walk(role + ".", x)
    walk("", ctl or {})
    for r in rows:
        n = names.get(_pvkey(r["pv"])) or names.get(r["pv"])
        if n:
            r["meta"]["name"] = n
    return rows, extra


def _detail(m):
    bits = []
    if m.get("units"):
        bits.append(f"units {m['units']}")
    if m.get("step") is not None:
        bits.append(f"tweak {m['step']:g}")
    lim = m.get("limits")
    if lim and lim.get("lo") is not None and lim.get("hi") is not None:
        bits.append(f"limits {lim['lo']:g} … {lim['hi']:g} ({lim['frame']})")
    return " · ".join(bits)


def build(e, pvmap, verify_items=()):
    """e = twin element dict (with controls/dev/pv), pvmap = pv_map.json element or None, verify_items = this element's unresolved to-verify items."""
    ch = {g: {} for g in GROUPS}         # group -> {pvkey: row}
    order = {g: [] for g in GROUPS}
    opn = []

    def row(group, key, label, pv, src, detail="", **kw):
        d = ch[group]
        if key in d:
            r = d[key]
            if label and not r["label"]:
                r["label"] = label
            elif label and label != r["label"] and label not in r["also"]:
                r["also"].append(label)
            r["src"] += [x for x in ([src] if isinstance(src, str) else src) if x not in r["src"]]
            if detail and not r["detail"]:
                r["detail"] = detail
            for a, b in kw.items():
                if b and not r.get(a):
                    r[a] = b
            return r
        r = {"label": label or "", "also": [], "pv": pv, "detail": detail, "src": [src] if isinstance(src, str) else list(src), **{a: b for a, b in kw.items() if b}}
        d[key] = r
        order[group].append(key)
        return r

    # --- device & prefix (from the twin element itself) ---
    if e.get("dev"):
        row("Device & prefix", "dev", "device name", e["dev"], "code", mono=True)
    if e.get("pv"):
        row("Device & prefix", "pv:" + e["pv"], "PV / prefix", e["pv"], "code")

    # --- from the CS-Studio displays ---
    n_ic_no_readout = e.get("kind") == "ic"
    for g in (pvmap or {}).get("groups", []):
        t = g["type"]
        if t == "motors":
            for m in g["motors"]:
                nm, lg = m.get("name") or "", m.get("log_label") or ""
                src = ["display"] + (["log"] if lg else [])      # the row exists on the display; "log" = the log panels also name / limit it
                r = row("Motors & axes", _pvkey(m["pv"]), nm or lg, m["pv"], src, _detail(m),
                        shared_with=m.get("shared_with"), candidates=m.get("candidates"), slit_role=m.get("role"), tpl="motor")
                if nm and lg and re.sub(r"\W", "", nm.lower()) != re.sub(r"\W", "", lg.lower()) and f"log: {lg}" not in r["also"]:
                    r["also"].append(f"log: {lg}")
        elif t == "slit":
            for axis, x in g["axes"].items():
                row("Slit axes", x["record"], axis, x["record"], "display", "software axis: size and centre records", tpl="slit_axis")
            for k, pv in (g.get("blade_motors") or {}).items():
                pass   # blade motors appear in the motor group below (role label added by pvmap)
        elif t == "ic_readout":
            n_ic_no_readout = False
            row("Read-outs", _pvkey(g["readback"]["pv"]), "counts (scaler channel %d)" % g["scaler"]["channel"], g["readback"]["pv"], "display", "read")
            row("Read-outs", g["scaler"]["record"], "scaler record (shared counter)", g["scaler"]["record"], "display", tpl="scaler")
            row("Read-outs", g["preamp"]["record"], "SR570 preamp", g["preamp"]["record"], "display", "sensitivity, filters, offsets", tpl="preamp")
        elif t == "camera":
            ttl = re.search(r"\((.*)\)$", g.get("title") or "")
            row("Device & prefix", g["prefix"], f"{ttl.group(1) if ttl else 'detector'} - {g['driver']} IOC" + (f" ({g['model']})" if g.get("model") else ""), g["prefix"], "display")
        elif t == "panel" and g.get("P"):
            row("Device & prefix", "panel:" + g["P"], "panel prefix", g["P"], "display")

    # --- from the twin element's own controls (code / user statements) ---
    rows, extra = _flatten(e.get("controls"))
    for r in rows:
        pv, role, meta = r["pv"], r["role"], r["meta"]
        key = _pvkey(pv)
        is_motor = bool(MOTOR_RX.search(key))
        group = "Motors & axes" if is_motor else "Signals & switches"
        if group == "Signals & switches" and re.match(r"^(hsize|vsize)$", role):
            group = "Slit axes"
        label = meta.get("name") or ("" if GENERIC_ROLE.match(role) else role)
        bits = []
        if GENERIC_ROLE.match(role) and not meta.get("name"):
            bits.append(re.sub(r"\[\d+\]|_m\d+$", "", role).replace("_", " "))      # keep 'table motors' / 'circle motors' as a hint
        if " - " in label:                                    # 'NF TiltY (In E) - by motor number, ...' -> caveat goes to the detail line
            label, cav = label.split(" - ", 1)
            bits.append(cav)
        bits += [f"{k} {v}" for k, v in meta.items() if k in ("access", "units")]
        if meta.get("limits"):
            bits.append(f"limits {meta['limits'][0]:g} … {meta['limits'][1]:g}")
        if meta.get("readback") is not None:
            bits.append(f"readback {meta['readback']:g} (photo)")
        if meta.get("log_panel_desc"):
            bits.append(f"log panel: {meta['log_panel_desc']}")
        if meta.get("display_label"):
            bits.append(f"display: {meta['display_label']}")
        have = ch[group].get(key)
        r_ = row(group, key, "" if (have and have["label"]) else label, pv, "code", " · ".join(bits), tpl="motor" if is_motor else None)
        if have and have["label"] and label and label != have["label"] and f"code: {label}" not in have["also"]:
            have["also"].append(f"code: {label}")

    # --- open items ---
    for v in verify_items:
        opn.append({"kind": "verify", "text": f"{v['subject']} - {v['value']}", "why": v.get("why", "")})
    miss = [ch["Motors & axes"][k] for k in order["Motors & axes"] if not (ch["Motors & axes"][k]["label"] or ch["Motors & axes"][k].get("slit_role"))]
    amb = [r for r in miss if r.get("candidates")]
    plain = [r for r in miss if not r.get("candidates")]
    if plain:
        opn.append({"kind": "gap", "text": "Motor%s with no name on the display, the log panels or in code: %s" % ("s" if len(plain) > 1 else "", ", ".join(r["pv"] for r in plain))})
    for r in amb:
        opn.append({"kind": "ambiguous", "text": f"{r['pv']} appears on the log windows {'; '.join(r['candidates'])} but not clearly enough to name it - not assigned"})
    if e.get("kind") == "ic" and n_ic_no_readout:
        opn.append({"kind": "gap", "text": "No read-out channel for this ion chamber on the operator display (scaler / preamp PV not found)"})
    for kind, x in extra:
        if kind == "conflict" and verify_items:           # the element's to-verify items already carry these conflicts (with the why / how)
            continue
        opn.append({"kind": kind, "text": x})
    if not any(order[g] for g in GROUPS):
        opn.append({"kind": "gap", "text": "No PV recorded: the element is not a button on the CS-Studio layout and no code device / user statement gives one"})

    out = []
    for g in GROUPS:
        rs = []
        for k in order[g]:
            r = ch[g][k]
            r["src"] = sorted(set(r["src"]), key=SRC_ORDER.index)
            if not r.get("label") and r.get("slit_role"):
                r["label"] = r["slit_role"]
            elif r.get("slit_role") and r["slit_role"] not in r["also"] and r["slit_role"] != r["label"]:
                r["also"].append(r["slit_role"])
            r.pop("slit_role", None)
            rs.append(r)
        if rs:
            out.append({"group": g, "rows": rs})
    tpls = sorted({r["tpl"] for g in out for r in g["rows"] if r.get("tpl")}, key=("motor", "slit_axis", "scaler", "preamp").index)
    return {"channels": out, "open": opn, "templates": tpls, "src_txt": SRC_TXT}

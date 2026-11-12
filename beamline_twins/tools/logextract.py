"""Plain-text extraction of experiment-log documents (stdlib only): .docx, .xlsx, .ods -> list of (style, text) lines.

Never executes anything from the documents; only reads XML out of the zip container. Large embedded images are NOT loaded (only their names
are recorded, as '[IMG name]' marker lines, so a figure can be extracted later on demand with `image_bytes`).
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _rels(z, part):
    """relationship id -> target, for a part such as word/document.xml."""
    p = f"word/_rels/{Path(part).name}.rels"
    if p not in z.namelist():
        return {}
    return {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(p)).iter(f"{REL}Relationship")}


def _para(p, rels, extra):
    """Text of one w:p. Text boxes are pulled out into `extra` (so they are not duplicated); drawings become [IMG name] markers."""
    out = []

    def walk(el):
        for ch in el:
            t = ch.tag
            if t == f"{W}t":
                out.append(ch.text or "")
            elif t == f"{W}tab":
                out.append("\t")
            elif t in (f"{W}br", f"{W}cr"):
                out.append("\n")
            elif t == f"{W}txbxContent":
                extra.append(" / ".join(x for x in (_para(q, rels, extra)[0] for q in ch.iter(f"{W}p")) if x))
            elif t == f"{W}drawing" or t == f"{W}pict":
                for blip in ch.iter(f"{A}blip"):
                    tgt = rels.get(blip.get(f"{R}embed"), "?")
                    out.append(f" [IMG {Path(tgt).name}] ")
                for c in ch.iter(f"{WP}docPr"):
                    d = (c.get("descr") or "").strip()
                    if d:
                        out.append(f" [ALT {d[:200]}] ")
            elif t in (f"{W}instrText", f"{W}delText"):
                continue
            else:
                walk(ch)

    walk(p)
    style = ""
    ppr = p.find(f"{W}pPr")
    if ppr is not None:
        ps = ppr.find(f"{W}pStyle")
        if ps is not None:
            style = ps.get(f"{W}val") or ""
        if ppr.find(f"{W}numPr") is not None:
            style = (style + " list").strip()
    return "".join(out).replace("\xa0", " "), style


def docx_lines(path):
    """[(style, text)] in document order; tables become '| a | b | c' rows (style 'table')."""
    with zipfile.ZipFile(path) as z:
        rels = _rels(z, "word/document.xml")
        root = ET.fromstring(z.read("word/document.xml"))
        body = root.find(f"{W}body")
        lines, extra = [], []

        def block(el):
            for ch in el:
                if ch.tag == f"{W}p":
                    txt, st = _para(ch, rels, extra)
                    for part in txt.split("\n"):
                        lines.append((st, part.rstrip()))
                    while extra:
                        lines.append(("textbox", "[TEXTBOX] " + extra.pop(0)))
                elif ch.tag == f"{W}tbl":
                    for tr in ch.iter(f"{W}tr"):
                        cells = []
                        for tc in tr.findall(f"{W}tc"):
                            ex2 = []
                            cells.append(" / ".join(x for x in (_para(q, rels, ex2)[0].strip() for q in tc.iter(f"{W}p")) if x))
                        lines.append(("table", "| " + " | ".join(cells)))
                elif ch.tag in (f"{W}sdt", f"{W}sdtContent"):
                    block(ch)

        block(body)
        for part in z.namelist():                      # headers/footers/footnotes can carry settings too
            if re.match(r"word/(header|footer|footnotes|comments)\d*\.xml$", part):
                try:
                    for p in ET.fromstring(z.read(part)).iter(f"{W}p"):
                        txt = _para(p, {}, [])[0].strip()
                        if txt:
                            lines.append((part.split("/")[1].split(".")[0].rstrip("0123456789"), "[" + part.split("/")[1][:-4] + "] " + txt))
                except ET.ParseError:
                    pass
    return lines


def _col(ref):
    n = 0
    for c in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(c) - 64
    return n


def xlsx_lines(path):
    """[(style, text)]: one line per non-empty row, 'Sheet!row | cell | cell ...'; style 'sheet:<name>'."""
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as z:
        sst = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{NS}si"):
                sst.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{REL}Relationship")}
        lines = []
        for sh in wb.iter(f"{NS}sheet"):
            name, rid = sh.get("name"), sh.get(f"{R}id")
            tgt = rels.get(rid, "")
            part = tgt if tgt.startswith("xl/") else "xl/" + tgt.lstrip("/")
            if part not in z.namelist():
                continue
            lines.append((f"sheet:{name}", f"[SHEET {name}]"))
            for row in ET.fromstring(z.read(part)).iter(f"{NS}row"):
                cells = {}
                for c in row.findall(f"{NS}c"):
                    v = c.find(f"{NS}v")
                    t = c.get("t")
                    if t == "s" and v is not None:
                        val = sst[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{NS}t"))
                    else:
                        val = v.text if v is not None else ""
                    if val not in ("", None):
                        cells[_col(c.get("r"))] = val.strip().replace("\n", " ")
                if cells:
                    mx = max(cells)
                    lines.append((f"sheet:{name}", f"{name}!{row.get('r')} | " + " | ".join(cells.get(i, "") for i in range(1, mx + 1))))
    return lines


def ods_lines(path):
    T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
    X = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    lines = []
    for tb in root.iter(f"{T}table"):
        name = tb.get(f"{T}name")
        lines.append((f"sheet:{name}", f"[SHEET {name}]"))
        for n, row in enumerate(tb.iter(f"{T}table-row"), 1):
            cells = []
            for c in row.findall(f"{T}table-cell"):
                txt = " ".join("".join(p.itertext()) for p in c.findall(f"{X}p")).strip()
                rep = min(int(c.get(f"{T}number-columns-repeated", "1")), 8)
                cells += [txt] * rep
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                lines.append((f"sheet:{name}", f"{name}!{n} | " + " | ".join(cells)))
    return lines


def extract(path):
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        return docx_lines(path)
    if ext == ".xlsx":
        return xlsx_lines(path)
    if ext == ".ods":
        return ods_lines(path)
    raise ValueError(f"unsupported file type {ext}")


def image_bytes(path, name):
    """Bytes of one embedded image (by file name from an [IMG name] marker), for on-demand viewing."""
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith("/" + name) and "/media/" in n:
                return z.read(n)
    raise KeyError(name)

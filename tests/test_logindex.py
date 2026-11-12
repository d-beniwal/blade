"""Log extractor/index test with SYNTHETIC documents (no private logs needed, stdlib only).
Run: python -I tests/test_logindex.py"""
import io, json, os, subprocess, sys, tempfile, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "beamline_twins" / "tools"
sys.path.insert(0, str(TOOLS))
tmp = Path(tempfile.mkdtemp())
os.environ["BLADE_LOGINDEX_DIR"] = str(tmp / "index")
import logextract, logindex

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' \
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
p = lambda t, st=None: f'<w:p>{f"<w:pPr><w:pStyle w:val=\"{st}\"/></w:pPr>" if st else ""}<w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
IMG = '<w:p><w:r><w:drawing><wp:docPr id="1" name="x" descr="operator screen"/><a:graphic><a:graphicData><a:blip r:embed="rId5"/></a:graphicData></a:graphic></w:drawing></w:r></w:p>'
body = "".join([
    p("Experiment log for startup_jan25", "Title"), p("X-ray energy: 71.676 keV"), p("Monday (2025-01-27)", "Heading1"), p("Startup", "Heading2"),
    p("Calibrated energy at Au edge"), p("E_hem = 80.725 , Au K edge"), p("Gap = 8.995 mm , n=9"), p("WB = 0.3 x 0.3 @ [-0.02, -0.08]"),
    p("IC_B1 = 178.5 kHz , 50 nA/V @ 200 mA"), IMG, p("Th1 offset = 0.4873 deg"),
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Xb</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2.749887</w:t></w:r></w:p></w:tc></w:tr></w:tbl>',
    p("Tuesday (2025-01-28)", "Heading1"), p("Slit alignment", "Heading2"), p("Kohzu slit aligned with ion chamber; closed blade at 0.1 x 0.1 mm"),
])
docx = tmp / "src" / "2025_Explogs" / "startup_jan25_explog.docx"
docx.parent.mkdir(parents=True)
with zipfile.ZipFile(docx, "w") as z:
    z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>')
    z.writestr("word/_rels/document.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId5" Target="media/image7.png" Type="image"/></Relationships>')
    z.writestr("word/media/image7.png", b"\x89PNG-fake")
# a spreadsheet and a plain user log
xlsx = tmp / "src" / "2025_Explogs" / "smith_feb25_exptables.xlsx"
with zipfile.ZipFile(xlsx, "w") as z:
    z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>sample</t></si><si><t>gap</t></si></sst>')
    z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
               '<row r="2"><c r="A2"><v>1</v></c><c r="B2"><v>8.995</v></c></row></sheetData></worksheet>')
user = tmp / "src" / "2025_Explogs" / "smith_feb25_explog.docx"
with zipfile.ZipFile(user, "w") as z:
    z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{p("Experiment log", "Title")}{p("X-ray energy: 71.676 keV (Re edge)")}'
               f'{p("Sunday (2025-02-09)", "Heading1")}{p("Hydra at 2200 mm distance, 1 s exposure")}</w:body></w:document>')

# ---- extraction
lines = logextract.extract(docx)
txt = [t for _, t in lines]
assert "E_hem = 80.725 , Au K edge" in txt and any(t.startswith("| Xb | 2.749887") for t in txt) and any("[IMG image7.png]" in t for t in txt) and any("[ALT operator screen]" in t for t in txt)
assert logextract.image_bytes(docx, "image7.png") == b"\x89PNG-fake"
assert any("S1!2 | 1 | 8.995" in t for _, t in logextract.extract(xlsx)), logextract.extract(xlsx)

# ---- build + queries
meta = logindex.build(tmp / "src", "1-ID")
assert meta["n_docs"] == 3 and not meta["bad"], meta
T = lambda *a: subprocess.run([sys.executable, str(TOOLS / "logindex.py"), *a], capture_output=True, text=True, env=os.environ).stdout
assert "2025-startup_jan25_explog:L" in T("search", "Au edge", "--kind", "startup")                        # full-text hit with citation
assert "-- 0 hits" in T("search", "Au edge", "--kind", "user")                                              # the kind filter excludes startup docs
out = T("outline", "startup_jan25")
assert "Monday (2025-01-27)" in out and "Slit alignment" in out and "2025-01-28" in out                    # headings and parsed dates
assert "Gap = 8.995 mm" in T("show", "startup_jan25", "--section", "Startup")
pr = T("params", "E_hem_keV"); assert "80.725" in pr
pr = T("params", "gap_mm"); assert "8.995" in pr
pr = T("params", "slit_h_mm"); assert "0.3" in pr and "WB" in pr
assert "th1_offset_deg" in T("params", "mu_t") and "0.4873" in T("params", "th1_offset_deg")
assert "slit" in T("topic", "slit") and "2025-startup_jan25_explog" in T("topic", "slit")
assert "image7.png" in T("images", "startup_jan25") and "1 images" in T("images", "startup_jan25")
T("images", "startup_jan25", "--extract", "--out", str(tmp / "img")); assert (tmp / "img" / "image7.png").read_bytes() == b"\x89PNG-fake"
cat = (tmp / "index" / "catalog.md").read_text()
assert "| startup |" in cat and "| user |" in cat and "| tables |" in cat                                 # classification
con = logindex.connect("1-ID")
assert con.execute("select count(*) from docs where kind='startup' and year=2025").fetchone()[0] == 1
# stats script runs on the synthetic index and contains no document ids of user logs
sys.path.insert(0, str(TOOLS)); import logstats
md = logstats.build(con)
assert "Re" in md and "smith" not in md and "Corpus" in md
print("logindex OK")

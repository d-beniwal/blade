-- BLADE knowledge base (1-ID) - SQLite schema. Data lives OUTSIDE the repo (default ../kb_1ID); only code + this schema are committed.
-- Principles: (1) content-addressed images (sha256) so duplicates collapse and ids never change; (2) every claim about an image/fact is a
-- row in an APPEND-ONLY labels/facts table with source + confidence + timestamp, so labels can be upgraded (rule -> vision -> human)
-- without losing history; (3) every record keeps provenance back to doc_id + line so it can be cited and re-read.

CREATE TABLE IF NOT EXISTS docs(          -- copied from logindex (logs.sqlite): one row per experiment-log document
  doc_id TEXT PRIMARY KEY, relpath TEXT, year INT, ext TEXT, kind TEXT, title TEXT, header TEXT, exp_time TEXT,
  date_first TEXT, date_last TEXT, size_mb REAL, n_lines INT, n_tables INT, n_images INT, n_headings INT);
CREATE TABLE IF NOT EXISTS lines(doc_id TEXT, ln INT, h1 TEXT, h2 TEXT, h3 TEXT, date TEXT, style TEXT, text TEXT, PRIMARY KEY(doc_id, ln));
CREATE TABLE IF NOT EXISTS tags(doc_id TEXT, ln INT, tag TEXT);                       -- regex topic tags per line
CREATE TABLE IF NOT EXISTS params(doc_id TEXT, ln INT, name TEXT, value REAL, aux TEXT, raw TEXT);   -- numbers pulled from text (energy, slits ...)

CREATE TABLE IF NOT EXISTS images(        -- one row per UNIQUE image (by content)
  sha256 TEXT PRIMARY KEY, ext TEXT, bytes INT, width INT, height INT, mode TEXT,
  n_colors INT,       -- distinct colours on a 192px thumbnail (screenshots: few, photos: many)
  sat REAL,           -- mean |R-G|+|G-B| (0 = pure grayscale)
  mean REAL, std REAL, p1 REAL, p99 REAL, entropy REAL,   -- on the grayscale thumbnail
  dhash TEXT,         -- 64-bit difference hash (hex) for near-duplicate search
  path TEXT);         -- relative to the KB root

CREATE TABLE IF NOT EXISTS image_refs(    -- every place an image appears in a log (same image may be cited many times)
  doc_id TEXT, name TEXT, sha256 TEXT, ln INT, ord INT,          -- ord = running image index within the doc
  h1 TEXT, h2 TEXT, h3 TEXT, date TEXT, in_table INT,
  same_line TEXT,     -- text on the same line as the image marker (without markers)
  before TEXT, after TEXT,   -- nearest non-empty text lines before / after (captions, "With pg5 at position:", "Hotspot = ...")
  PRIMARY KEY(doc_id, name, ln));

CREATE TABLE IF NOT EXISTS labels(        -- append-only; many labels per image, one per (key, source, time)
  sha256 TEXT, key TEXT,      -- key: class | subject | camera | hutch | energy_keV | sample | note ...
  value TEXT, source TEXT,    -- source: rule | vision | human
  confidence REAL, created TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS labels_sha ON labels(sha256, key);
CREATE INDEX IF NOT EXISTS refs_sha ON image_refs(sha256);
CREATE INDEX IF NOT EXISTS refs_doc ON image_refs(doc_id);
CREATE INDEX IF NOT EXISTS images_dhash ON images(dhash);

-- The label to trust per (image, key): human > vision > rule, then newest.
CREATE VIEW IF NOT EXISTS label_best AS
  SELECT sha256, key, value, source, confidence, created, note FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY sha256, key ORDER BY
      CASE source WHEN 'human' THEN 3 WHEN 'vision' THEN 2 ELSE 1 END DESC, created DESC) AS rn FROM labels) WHERE rn = 1;

-- Flat, search-friendly view: one row per image with its trusted class/subject/camera/hutch and first citation.
CREATE VIEW IF NOT EXISTS image_index AS
  SELECT i.sha256, i.path, i.width, i.height,
    (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='class')   AS class,
    (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='subject') AS subject,
    (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='camera')  AS camera,
    (SELECT value FROM label_best b WHERE b.sha256=i.sha256 AND b.key='hutch')   AS hutch,
    (SELECT source FROM label_best b WHERE b.sha256=i.sha256 AND b.key='class')  AS class_source,
    (SELECT COUNT(*) FROM image_refs r WHERE r.sha256=i.sha256)                 AS n_refs
  FROM images i;

CREATE VIRTUAL TABLE IF NOT EXISTS ref_fts USING fts5(doc_id UNINDEXED, name UNINDEXED, sha256 UNINDEXED, text,
  tokenize="unicode61 remove_diacritics 2 tokenchars '_'");     -- searchable text around each image (headings + captions)

-- ---------------------------------------------------------------------------------------------------- procedures (how things are done)
-- Written from log "source packs" by extraction agents (procpack.py), validated (every citation must resolve to a real doc:line) and loaded by
-- procload.py. Source of truth = <KB_ROOT>/procedures/<id>.json; these tables are the searchable projection.
CREATE TABLE IF NOT EXISTS procedures(id TEXT PRIMARY KEY, name TEXT, goal TEXT, when_performed TEXT, scope TEXT, n_steps INT, n_cites INT, loaded TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS procedure_steps(proc_id TEXT, n INT, action TEXT, loc TEXT, tool TEXT, signal TEXT, done_when TEXT, evidence TEXT, cites TEXT, PRIMARY KEY(proc_id, n));
CREATE TABLE IF NOT EXISTS procedure_numbers(proc_id TEXT, step_n INT, quantity TEXT, value TEXT, unit TEXT, context TEXT, era TEXT, cites TEXT);
CREATE TABLE IF NOT EXISTS procedure_notes(proc_id TEXT, kind TEXT, text TEXT, cites TEXT);   -- kind: prereq|tool|variant|pitfall|success|image|open|vbl|related
CREATE TABLE IF NOT EXISTS procedure_cites(proc_id TEXT, doc_id TEXT, ln INT);               -- normalised citations (join to lines / image_refs)
CREATE INDEX IF NOT EXISTS pnum_q ON procedure_numbers(quantity);
CREATE INDEX IF NOT EXISTS pcite_doc ON procedure_cites(doc_id, ln);
CREATE VIRTUAL TABLE IF NOT EXISTS proc_fts USING fts5(proc_id UNINDEXED, kind UNINDEXED, text, tokenize="unicode61 remove_diacritics 2 tokenchars '_'");

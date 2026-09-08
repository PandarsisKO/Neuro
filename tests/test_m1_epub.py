"""G6P1 — EPUB Core (0.34.0): the P1 gate, offline ($0). (Sorts after test_l2.)

A valid EPUB (1) uploads through the ordinary source lifecycle, (2) extracts in SPINE order (never the ZIP's order),
(3) is searchable, (4) yields findings, (5) answers questions, (6) cites deterministic structural locators, (7) survives
retry/restart (same source, same locators), (8) uses the normal provenance/jobs/cost/revision infrastructure — plus
EPUB 2 and 3, nested and missing TOCs, non-English text, malformed-but-recoverable packages, and protected books refused."""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_epub_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, epub, fake_ai, findings, ingest, jobs, qa, search, works  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir(); (data / "files").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


# ---------------------------------------------------------------- a small book, built the way real packages are

INTRO = "This book explains why great companies fail when the technology changes under them. " * 3
CH1 = ("Established firms listen to their best customers and invest where the margins are. That discipline is exactly what leaves them exposed "
       "to a disruptive technology that starts as a worse, cheaper product serving a market nobody wanted. " * 2)
CH1_S2 = "The disk-drive industry shows the pattern in miniature: each new form factor was pioneered by entrants, not incumbents. " * 2
CH2 = "Managers cannot escape the problem by working harder; the resource-allocation process itself is the problem. " * 3
CH3 = "Un mercado emergente parece demasiado pequeño para una empresa grande — así empieza la disrupción. Résumé en français: la valeur naît ailleurs. " * 2
APPX = "Appendix data tables follow. " * 4


NAV_ITEM = '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
NCX_ITEM = '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
SPINE_TOC = ' toc="ncx"'


def _xhtml(title, body, lang="en"):
    return f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}"><head><title>{title}</title></head><body>{body}</body></html>'


def build_epub(path: Path, *, version=3, toc=True, isbn="9780875845852", protected=False, broken=False, spine_scramble=True):
    """Chapters are stored under ZIP names that sort in the WRONG order (z_, y_, …) so alphabetical reading would be visibly wrong."""
    docs = {
        "z_intro.xhtml": _xhtml("Introduction", f'<section epub:type="introduction"><h1 id="intro">Introduction</h1><p>{INTRO}</p></section>'),
        "y_ch1.xhtml": _xhtml("Chapter 1", f'<h1 id="c1">How Can Great Firms Fail?</h1><p>{CH1}</p><h2 id="c1s2">The Disk-Drive Pattern</h2><p>{CH1_S2}</p>'),
        "x_ch2.xhtml": _xhtml("Chapter 2", f'<h1 id="c2">Value Networks</h1><p>{CH2}</p>'),
        "w_ch3.xhtml": _xhtml("Chapter 3", f'<h1 id="c3">Mercados emergentes</h1><p>{CH3}</p>' + ("<p>unclosed <b>bold" if broken else ""), lang="es"),
        "a_appendix.xhtml": _xhtml("Appendix", f'<h1 id="appx">Appendix A</h1><p>{APPX}</p>'),
    }
    order = ["z_intro.xhtml", "y_ch1.xhtml", "x_ch2.xhtml", "w_ch3.xhtml", "a_appendix.xhtml"]
    manifest = "".join(f'<item id="d{i}" href="{h}" media-type="application/xhtml+xml"/>' for i, h in enumerate(order))
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(len(order)))
    ident = f'<dc:identifier id="pub-id" opf:scheme="ISBN">urn:isbn:{isbn}</dc:identifier>' if isbn else '<dc:identifier id="pub-id">urn:uuid:1234</dc:identifier>'
    files = {}
    if version == 3:
        nav = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><h1>Contents</h1><ol>'
               '<li><a href="z_intro.xhtml">Introduction</a></li>'
               '<li><a href="y_ch1.xhtml">How Can Great Firms Fail?</a><ol><li><a href="y_ch1.xhtml#c1s2">The Disk-Drive Pattern</a></li></ol></li>'
               '<li><a href="x_ch2.xhtml">Value Networks</a></li><li><a href="w_ch3.xhtml">Mercados emergentes</a></li><li><a href="a_appendix.xhtml">Appendix A</a></li></ol></nav></body></html>')
        opf = (f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" xmlns:opf="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">'
               f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title id="t1">The Innovator\'s Dilemma</dc:title><meta refines="#t1" property="title-type">main</meta>'
               f'<dc:title id="t2">When New Technologies Cause Great Firms to Fail</dc:title><meta refines="#t2" property="title-type">subtitle</meta>'
               f'<dc:creator>Clayton M. Christensen</dc:creator><dc:publisher>Harvard Business School Press</dc:publisher><dc:language>en</dc:language><dc:date>1997-05-01</dc:date>'
               f'<meta property="dcterms:modified">2020-01-02T00:00:00Z</meta>{ident}<dc:subject>Business</dc:subject><dc:description>Revised edition with a new preface.</dc:description><dc:rights>© 1997</dc:rights></metadata>'
               f'<manifest>{manifest}{NAV_ITEM if toc else ""}</manifest><spine>{spine}</spine></package>')
        if toc:
            files["OEBPS/nav.xhtml"] = nav
    else:
        ncx = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>'
               '<navPoint id="n1"><navLabel><text>Introduction</text></navLabel><content src="z_intro.xhtml"/></navPoint>'
               '<navPoint id="n2"><navLabel><text>How Can Great Firms Fail?</text></navLabel><content src="y_ch1.xhtml"/><navPoint id="n2a"><navLabel><text>The Disk-Drive Pattern</text></navLabel><content src="y_ch1.xhtml#c1s2"/></navPoint></navPoint>'
               '<navPoint id="n3"><navLabel><text>Value Networks</text></navLabel><content src="x_ch2.xhtml"/></navPoint><navPoint id="n4"><navLabel><text>Mercados emergentes</text></navLabel><content src="w_ch3.xhtml"/></navPoint>'
               '<navPoint id="n5"><navLabel><text>Appendix A</text></navLabel><content src="a_appendix.xhtml"/></navPoint></navMap></ncx>')
        opf = (f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" xmlns:opf="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="pub-id">'
               f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf"><dc:title>The Innovator\'s Dilemma</dc:title><dc:creator>Clayton M. Christensen</dc:creator>'
               f'<dc:publisher>Harvard Business School Press</dc:publisher><dc:language>en</dc:language><dc:date>1997</dc:date>{ident}</metadata>'
               f'<manifest>{manifest}{NCX_ITEM if toc else ""}</manifest><spine{SPINE_TOC if toc else ""}>{spine}</spine></package>')
        if toc:
            files["OEBPS/toc.ncx"] = ncx
    files["OEBPS/content.opf"] = opf
    for h, x in docs.items():
        files["OEBPS/" + h] = x
    files["META-INF/container.xml"] = '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    if protected:
        files["META-INF/encryption.xml"] = ('<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
                                            '<enc:EncryptedData><enc:CipherData><enc:CipherReference URI="OEBPS/y_ch1.xhtml"/></enc:CipherData></enc:EncryptedData></encryption>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name in (sorted(files) if spine_scramble else files):          # ZIP order ≠ reading order
            z.writestr(name, files[name])
    return path


# ---------------------------------------------------------------- the reader

def test_reader_follows_the_spine_and_recovers_structure(tmp_path):
    book = epub.read_epub(build_epub(tmp_path / "dilemma.epub"))
    md = book["metadata"]
    assert md["title"] == "The Innovator's Dilemma" and md["subtitle"].startswith("When New") and md["creators"] == ["Clayton M. Christensen"]
    assert md["publisher"] == "Harvard Business School Press" and md["language"] == "en" and md["date"] == "1997-05-01" and md["modified"].startswith("2020")
    assert md["isbn"] == "9780875845852" and md["package_id"] == "9780875845852" and md["subjects"] == ["Business"] and md["rights"] == "© 1997" and md["edition"] == "Revised edition"
    hrefs = [d["href"] for d in book["documents"]]
    assert hrefs == ["OEBPS/z_intro.xhtml", "OEBPS/y_ch1.xhtml", "OEBPS/x_ch2.xhtml", "OEBPS/w_ch3.xhtml", "OEBPS/a_appendix.xhtml"], "spine order, not ZIP order"
    titles = [d["title"] for d in book["documents"]]
    assert titles == ["Introduction", "How Can Great Firms Fail?", "Value Networks", "Mercados emergentes", "Appendix A"]
    assert [d["role"] for d in book["documents"]] == ["introduction", None, None, None, "appendix"]
    assert book["toc_depth"] == 2 and book["chapters"] == 5 and not book["warnings"]
    ch1 = book["documents"][1]["sections"]
    assert [s["heading"] for s in ch1] == ["How Can Great Firms Fail?", "The Disk-Drive Pattern"] and ch1[1]["fragment"] == "c1s2" and "entrants" in ch1[1]["text"]
    assert "pequeño" in book["documents"][3]["sections"][0]["text"], "non-English text intact"
    locs = epub.locators(book)
    assert locs[0]["label"] == "Ch. 1 → Introduction" and locs[2]["label"] == "Ch. 2 → How Can Great Firms Fail? · The Disk-Drive Pattern" and locs[2]["fragment"] == "c1s2"
    assert [lo["ordinal"] for lo in locs] == list(range(1, len(locs) + 1))


def test_epub2_ncx_missing_toc_and_broken_markup_still_read(tmp_path):
    b2 = epub.read_epub(build_epub(tmp_path / "v2.epub", version=2))
    assert b2["metadata"]["version"] == "2.0" and [d["title"] for d in b2["documents"]][1] == "How Can Great Firms Fail?" and b2["toc_depth"] == 2
    notoc = epub.read_epub(build_epub(tmp_path / "notoc.epub", toc=False, broken=True))
    assert any("no table of contents" in w for w in notoc["warnings"])
    assert [d["title"] for d in notoc["documents"]] == ["Introduction", "How Can Great Firms Fail?", "Value Networks", "Mercados emergentes", "Appendix A"], "chapters named from their headings"
    assert "unclosed bold" in notoc["documents"][3]["sections"][-1]["text"]
    assert epub.locators(notoc)[1]["label"] == "How Can Great Firms Fail?", "no TOC → no chapter numbers, the heading alone"


def test_protected_epub_is_detected_and_refused_without_circumvention(tmp_path):
    with pytest.raises(epub.EpubProtected, match="protected"):
        epub.read_epub(build_epub(tmp_path / "drm.epub", protected=True))
    with pytest.raises(epub.EpubError, match="not an EPUB"):
        epub.read_epub(Path(__file__))
    assert epub.is_epub(build_epub(tmp_path / "ok.epub")) and not epub.is_epub(Path(__file__))


# ---------------------------------------------------------------- the P1 gate through the ordinary source lifecycle

def test_p1_gate_upload_search_findings_answer_citations_retry(tmp_path, monkeypatch):
    pid = db.create_project("Books", "why incumbents lose to disruptive technology")["id"]
    f = build_epub(tmp_path / "dilemma.epub")
    # (1) ordinary lifecycle, (8) normal infrastructure: the upload job kind everything else uses
    r = ingest.ingest_local_file(f, project_id=pid, original_name="dilemma.epub")
    sid = r["source_id"]
    src = db.get_source(sid)
    assert src["platform"] == "book" and src["status"] == "ready" and src["transcript_kind"] == "epub" and src["title"].startswith("The Innovator's Dilemma: When New")
    assert src["channel"] == "Clayton M. Christensen" and src["published_at"] == "1997-05-01" and src["language"] == "en" and "ISBN 9780875845852" in src["description"]
    assert r["chapters"] == 5 and r["sections"] == 6 and r["metadata"]["isbn"] == "9780875845852" and r["work"]["by"] == "isbn"
    # (2) reading order
    segs = db.get_segments(sid)
    assert "great companies fail" in segs[0]["text"] and "Established firms" in segs[1]["text"] and "Appendix data" in segs[-1]["text"]
    labels = [row["label"] for row in db.connect().execute("SELECT label FROM book_sections WHERE source_id=? ORDER BY ordinal", (sid,)).fetchall()]
    assert labels[:3] == ["Ch. 1 → Introduction", "Ch. 2 → How Can Great Firms Fail?", "Ch. 2 → How Can Great Firms Fail? · The Disk-Drive Pattern"]
    # (3) searchable + (6) deterministic structural citations
    hits = search.search("disk-drive form factor entrants", source_ids=[sid], limit=5)
    assert hits and hits[0]["source_id"] == sid and hits[0]["timestamp"] == "Ch. 2 → How Can Great Firms Fail? · The Disk-Drive Pattern" and hits[0]["link"].endswith("#OEBPS/y_ch1.xhtml#c1s2")
    hits_es = search.search("mercado emergente disrupción", source_ids=[sid], limit=5)
    assert hits_es and hits_es[0]["timestamp"] == "Ch. 4 → Mercados emergentes"
    # (4) findings through the normal (fake) extraction
    fr = findings.suggest_for_source(pid, sid)
    notes = db.list_project_notes(pid, status="suggested")
    assert fr.get("suggested", 0) >= 1 and len(notes) >= 1 and all(str(c.get("timestamp", "")).startswith("Ch. ") for n in notes for c in (n.get("citations") or []) if c.get("source_id") == sid)
    # (5) answers with the same locators
    ans = qa.ask("Why do great firms fail according to the book?", project_id=pid, conversation_id="epub-1")
    assert ans["answer"] and any(c.get("source_id") == sid and str(c.get("timestamp", "")).startswith("Ch. ") for c in ans.get("citations", []))
    # (7) retry / restart: the same bytes are the same source; locators and Work link unchanged
    r2 = ingest.ingest_local_file(f, project_id=pid, original_name="dilemma-copy.epub")
    assert r2["source_id"] == sid and r2.get("already_ingested")
    db._local.conn = None
    assert [row["label"] for row in db.connect().execute("SELECT label FROM book_sections WHERE source_id=? ORDER BY ordinal", (sid,)).fetchall()] == labels
    from neurosearch import api
    view = api.api_source(sid)
    assert len(view["sections"]) == 6 and view["sections"][2]["fragment"] == "c1s2"
    assert "[Ch. 2 → How Can Great Firms Fail?]" in search.source_transcript(sid)


def test_work_integration_matches_the_existing_work_and_never_duplicates(tmp_path):
    """G6: the EPUB's ISBN resolves the Work G6 already knows; a second EPUB of the same ISBN is one Work, one owned copy per source."""
    pid = db.create_project("Books", "x")["id"]
    w0, created = works.ensure_work("book", "The Innovator's Dilemma", identifiers=[{"scheme": "isbn", "value": "9780875845852"}], creators=["Clayton M. Christensen"])
    assert created
    r = ingest.ingest_local_file(build_epub(tmp_path / "a.epub"), project_id=pid, original_name="a.epub")
    assert r["work"]["id"] == w0["id"] and r["work"]["version"] == "Revised edition"
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM works WHERE kind='book'").fetchone()[0] == 1
    m = conn.execute("SELECT relation, form, access FROM work_manifestations WHERE work_id=? AND source_id=?", (w0["id"], r["source_id"])).fetchone()
    assert m["relation"] == "manifestation_of" and m["form"] == "epub" and m["access"] == "owned"
    # without an ISBN: title + creator still resolve the same Work (non-regulatory kinds merge on exact title+creator)
    r2 = ingest.ingest_local_file(build_epub(tmp_path / "b.epub", isbn=None, version=2), project_id=pid, original_name="b.epub")
    assert r2["work"]["id"] == w0["id"] and r2["work"]["by"] == "title+creator" and r2["source_id"] != r["source_id"]
    assert conn.execute("SELECT COUNT(*) FROM works WHERE kind='book'").fetchone()[0] == 1


def test_upload_endpoint_immediate_and_job_paths(tmp_path, client):
    """The chat's attach button (immediate) and the background job both take an .epub."""
    H = {"Authorization": "Bearer t0k"}
    p = client.post("/api/projects", headers=H, json={"name": "Books", "brief": "disruption"}).json()
    data = build_epub(tmp_path / "up.epub").read_bytes()
    r = client.post("/api/ingest/file", headers=H, data={"project_id": p["id"], "immediate": "true"}, files={"file": ("up.epub", data, "application/epub+zip")}).json()
    assert r.get("immediate") and r.get("source_id")
    s = client.get(f"/api/sources/{r['source_id']}", headers=H).json()
    assert s["platform"] == "book" and s["status"] == "ready" and len(s["sections"]) == 6

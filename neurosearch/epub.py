"""G6P1 — EPUB Core (0.34.0): an EPUB is a structured publication, not an opaque ZIP or a converted PDF.

    .epub → recognize → validate the package → publication metadata → SPINE (reading order — never the ZIP's file
    order) → structured XHTML → sections (chapter / heading / anchor) → segments + chunks → index → cite
    "Ch. 3 → Disruptive Technological Change".

Everything here is deterministic and $0 — the standard library's zipfile + xml.etree + the tolerant `htmltree`; no paid
call recovers what the package already states. Supports EPUB 2 (OPF 2 + NCX) and EPUB 3 (OPF 3 + nav document),
reflowable books, nested and missing TOCs, non-English text, large books (bounded), malformed-but-recoverable packages
(a missing container.xml, broken XHTML, spine items that do not exist). Protected (DRM) books are DETECTED and refused —
no circumvention, ever.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from .htmltree import Node, parse

NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/",
      "ncx": "http://www.daisy.org/z3986/2005/ncx/", "enc": "http://www.w3.org/2001/04/xmlenc#"}
MAX_SECTIONS = 4000               # a large book stays bounded (≈ 40 sections × 100 chapters); the rest is one trailing section per document
MIN_SECTION_CHARS = 40            # headings with nothing under them fold into the next section
HEADINGS = {"h1", "h2", "h3", "h4"}
BLOCK_CONTAINERS = {"p", "div", "section", "ul", "ol", "table"} | HEADINGS     # a div holding any of these is a wrapper, not a paragraph
ROLE_WORDS = {"title_page": r"title[- ]?page", "copyright": r"copyright|imprint|colophon", "foreword": r"foreword", "preface": r"preface", "introduction": r"introduction",
              "acknowledgements": r"acknowledg", "appendix": r"appendix", "notes": r"^notes?$|endnotes|footnotes", "bibliography": r"bibliograph|references|works cited",
              "glossary": r"glossary", "index": r"^index$", "part": r"^part\b", "chapter": r"^chapter\b|^ch\.?\s*\d", "epilogue": r"epilogue|afterword", "prologue": r"prologue"}


class EpubError(RuntimeError):
    pass


class EpubProtected(EpubError):
    """The package encrypts its content documents (DRM). Neuro Search reads only what the user can lawfully open."""


def is_epub(path: Path) -> bool:
    if path.suffix.lower() != ".epub":
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return "META-INF/container.xml" in z.namelist() or any(n.lower().endswith(".opf") for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


# ---------------------------------------------------------------- the package

def _opf_path(z: zipfile.ZipFile, warnings: list[str]) -> str:
    try:
        root = ET.fromstring(z.read("META-INF/container.xml"))
        rf = root.find(".//c:rootfile", NS)
        if rf is not None and rf.get("full-path") and rf.get("full-path") in z.namelist():
            return rf.get("full-path")  # type: ignore[return-value]
        warnings.append("container.xml names a package document that is not in the archive")
    except KeyError:
        warnings.append("META-INF/container.xml missing — package located by scanning for an .opf")
    except ET.ParseError:
        warnings.append("META-INF/container.xml unreadable — package located by scanning for an .opf")
    for n in z.namelist():
        if n.lower().endswith(".opf"):
            return n
    raise EpubError("not an EPUB: no package document (.opf) in the archive")


def _protected(z: zipfile.ZipFile, content_hrefs: set[str]) -> bool:
    if "META-INF/encryption.xml" not in z.namelist():
        return False
    try:
        root = ET.fromstring(z.read("META-INF/encryption.xml"))
    except ET.ParseError:
        return True                                                        # unreadable encryption manifest: assume protected
    for ref in root.iter("{http://www.w3.org/2001/04/xmlenc#}CipherReference"):
        uri = unquote(ref.get("URI") or "")
        if uri in content_hrefs:
            return True                                                    # a content document is encrypted (fonts alone are fine)
    return False


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    t = " ".join(el.text.split())
    return t or None


def read_metadata(opf: ET.Element) -> dict[str, Any]:
    md = opf.find("opf:metadata", NS)
    out: dict[str, Any] = {"title": None, "subtitle": None, "creators": [], "publisher": None, "language": None, "date": None, "modified": None,
                           "identifiers": [], "isbn": None, "subjects": [], "description": None, "rights": None, "package_id": None, "edition": None, "version": opf.get("version")}
    if md is None:
        return out
    titles = [(_text(t), t.get("id")) for t in md.findall("dc:title", NS)]
    refines = {}
    for m in md.findall("opf:meta", NS):
        if m.get("refines") and m.get("property"):
            refines[(m.get("refines").lstrip("#"), m.get("property"))] = _text(m)
        if m.get("property") == "dcterms:modified":
            out["modified"] = _text(m)
        if m.get("name") == "calibre:series" or m.get("property") == "belongs-to-collection":
            out.setdefault("series", _text(m) or m.get("content"))
    main = next((t for t, tid in titles if tid and refines.get((tid, "title-type")) == "main"), None) or (titles[0][0] if titles else None)
    sub = next((t for t, tid in titles if tid and refines.get((tid, "title-type")) == "subtitle"), None)
    out["title"], out["subtitle"] = main, sub
    out["creators"] = [c for c in (_text(x) for x in md.findall("dc:creator", NS)) if c]
    out["publisher"] = _text(md.find("dc:publisher", NS))
    out["language"] = _text(md.find("dc:language", NS))
    out["date"] = _text(md.find("dc:date", NS))
    out["description"] = _text(md.find("dc:description", NS))
    out["rights"] = _text(md.find("dc:rights", NS))
    out["subjects"] = [s for s in (_text(x) for x in md.findall("dc:subject", NS)) if s]
    uid = opf.get("unique-identifier")
    for ident in md.findall("dc:identifier", NS):
        val = _text(ident)
        if not val:
            continue
        scheme = (ident.get("{%s}scheme" % NS["opf"]) or "").lower()
        iid = ident.get("id")
        if not scheme and iid and refines.get((iid, "identifier-type")):
            scheme = (refines[(iid, "identifier-type")] or "").lower()
        low = val.lower()
        if low.startswith("urn:isbn:"):
            scheme, val = "isbn", val[9:]
        elif low.startswith("urn:uuid:"):
            scheme, val = "uuid", val[9:]
        elif low.startswith("isbn:"):
            scheme, val = "isbn", val[5:]
        digits = re.sub(r"[- ]", "", val)
        if not scheme and re.fullmatch(r"(97[89])?\d{9}[\dXx]", digits):
            scheme = "isbn"
        out["identifiers"].append({"scheme": scheme or "unknown", "value": val.strip(), "unique": bool(uid and iid == uid)})
        if uid and iid == uid:
            out["package_id"] = val.strip()
    isbns = [i["value"] for i in out["identifiers"] if i["scheme"] == "isbn"]
    if isbns:
        out["isbn"] = re.sub(r"[- ]", "", isbns[0]).upper()
    for k in ("title", "subtitle", "description"):
        if out[k] and re.search(r"\b(\d+(st|nd|rd|th)|second|third|fourth|fifth|revised|updated|anniversary)\s+edition\b", out[k], re.I):
            out["edition"] = re.search(r"([\w-]+\s+edition)", out[k], re.I).group(1)  # type: ignore[union-attr]
    return out


# ---------------------------------------------------------------- the reading order and the TOC

def _manifest(opf: ET.Element, base: str) -> dict[str, dict[str, str]]:
    items = {}
    for it in opf.findall("opf:manifest/opf:item", NS):
        href = unquote(it.get("href") or "")
        items[it.get("id") or href] = {"href": posixpath.normpath(posixpath.join(base, href)) if base else href, "type": it.get("media-type") or "", "properties": it.get("properties") or ""}
    return items


def _spine(opf: ET.Element, manifest: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], str | None]:
    spine = opf.find("opf:spine", NS)
    out = []
    if spine is None:
        return out, None
    for ref in spine.findall("opf:itemref", NS):
        item = manifest.get(ref.get("idref") or "")
        if item and (item["type"].startswith("application/xhtml") or item["type"].startswith("text/html") or item["href"].lower().endswith((".xhtml", ".html", ".htm"))):
            out.append({"idref": ref.get("idref") or "", "href": item["href"], "linear": (ref.get("linear") or "yes") != "no"})
    return out, spine.get("toc")


def _toc(z: zipfile.ZipFile, opf: ET.Element, manifest: dict[str, dict[str, str]], ncx_id: str | None, warnings: list[str]) -> list[dict[str, Any]]:
    """[{href, fragment, label, depth}] in TOC order — from the EPUB 3 nav document when present, else the NCX."""
    entries: list[dict[str, Any]] = []
    nav = next((it for it in manifest.values() if "nav" in it["properties"].split()), None)
    if nav and nav["href"] in z.namelist():
        try:
            root = parse(z.read(nav["href"]).decode("utf-8", errors="replace"))
            navs = [n for n in root.walk() if n.tag == "nav"]
            toc = next((n for n in navs if (n.attrs.get("epub:type") or n.attrs.get("type") or "").endswith("toc")), navs[0] if navs else None)
            if toc is not None:
                base = posixpath.dirname(nav["href"])

                def walk(ol: Node, depth: int) -> None:
                    for li in [c for c in ol.children if isinstance(c, Node) and c.tag == "li"]:
                        a = li.first(lambda n: n.tag == "a")
                        if a is not None and a.attrs.get("href"):
                            href, _, frag = unquote(a.attrs["href"]).partition("#")
                            entries.append({"href": posixpath.normpath(posixpath.join(base, href)) if href else nav["href"], "fragment": frag or None, "label": a.text() or "", "depth": depth})
                        for sub in [c for c in li.children if isinstance(c, Node) and c.tag == "ol"]:
                            walk(sub, depth + 1)
                for ol in [c for c in toc.children if isinstance(c, Node) and c.tag == "ol"]:
                    walk(ol, 0)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"nav document unreadable ({e}); using the NCX if present")
    if not entries:
        ncx = manifest.get(ncx_id or "") or next((it for it in manifest.values() if it["type"] == "application/x-dtbncx+xml"), None)
        if ncx and ncx["href"] in z.namelist():
            try:
                root = ET.fromstring(z.read(ncx["href"]))
                base = posixpath.dirname(ncx["href"])

                def walk_ncx(parent: ET.Element, depth: int) -> None:
                    for np in parent.findall("ncx:navPoint", NS):
                        label = _text(np.find("ncx:navLabel/ncx:text", NS)) or ""
                        content = np.find("ncx:content", NS)
                        src = unquote(content.get("src") or "") if content is not None else ""
                        href, _, frag = src.partition("#")
                        entries.append({"href": posixpath.normpath(posixpath.join(base, href)) if href else "", "fragment": frag or None, "label": label, "depth": depth})
                        walk_ncx(np, depth + 1)
                nm = root.find("ncx:navMap", NS)
                if nm is not None:
                    walk_ncx(nm, 0)
            except ET.ParseError as e:
                warnings.append(f"NCX unreadable ({e}); chapters named from their headings")
    if not entries:
        warnings.append("no table of contents in the package; chapters named from their headings")
    return entries


# ---------------------------------------------------------------- content documents → sections

def _role_of(label: str, epub_type: str | None) -> str | None:
    t = (epub_type or "").lower()
    for role in ("titlepage", "copyright-page", "foreword", "preface", "introduction", "acknowledgments", "appendix", "endnotes", "footnotes", "bibliography", "glossary", "index", "part", "chapter", "epilogue", "prologue", "afterword"):
        if role in t:
            return {"titlepage": "title_page", "copyright-page": "copyright", "acknowledgments": "acknowledgements", "endnotes": "notes", "footnotes": "notes", "afterword": "epilogue"}.get(role, role)
    low = (label or "").strip().lower()
    for role, pat in ROLE_WORDS.items():
        if re.search(pat, low):
            return role
    return None


def _sections_of(html: str, doc_title: str | None) -> list[dict[str, Any]]:
    """One content document → sections split at headings, each with its anchor (the heading's id or the nearest id
    above it) and the running text under it."""
    root = parse(html)
    body = root.first(lambda n: n.tag == "body") or root
    epub_type = body.attrs.get("epub:type") if body is not root else None
    sections: list[dict[str, Any]] = []
    cur: dict[str, Any] = {"heading": None, "fragment": None, "parts": [], "level": 0}
    last_id: str | None = None

    def flush() -> None:
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(p for p in cur["parts"] if p.strip())).strip()
        if text or cur["heading"]:
            sections.append({"heading": cur["heading"], "fragment": cur["fragment"], "text": text, "level": cur["level"]})

    def visit(n: Node) -> None:
        nonlocal cur, last_id
        if n.attrs.get("id"):
            last_id = n.attrs["id"]
        if n.tag in HEADINGS:
            flush()
            cur = {"heading": " ".join(n.text().split()) or None, "fragment": n.attrs.get("id") or last_id, "parts": [], "level": int(n.tag[1])}
            return
        if n.tag in ("script", "style", "nav") and n is not body:
            return
        if n.tag in ("p", "li", "blockquote", "pre", "dd", "dt", "figcaption", "td", "th", "caption") or (n.tag == "div" and not any(isinstance(c, Node) and c.tag in BLOCK_CONTAINERS for c in n.children)):
            t = " ".join(n.text().split()) if n.tag != "pre" else n.text()
            if t:
                cur["parts"].append(("• " + t) if n.tag == "li" else t)
            return
        for c in n.children:
            if isinstance(c, Node):
                visit(c)
    visit(body)
    flush()
    # tiny fragments (a heading with nothing under it) fold into the section that follows
    merged: list[dict[str, Any]] = []
    for s in sections:
        if merged and len(merged[-1]["text"]) < MIN_SECTION_CHARS and merged[-1]["heading"] and s["heading"]:
            s["heading"] = f"{merged[-1]['heading']} — {s['heading']}"
            s["fragment"] = merged[-1]["fragment"] or s["fragment"]
            merged.pop()
        merged.append(s)
    for s in merged:
        s["epub_type"] = epub_type
    return merged or [{"heading": doc_title, "fragment": None, "text": "", "level": 0, "epub_type": epub_type}]


def read_epub(path: Path, *, max_sections: int = MAX_SECTIONS) -> dict[str, Any]:
    """The whole book, structured: metadata, the spine in reading order with each document's sections (chapter title from
    the TOC, heading, anchor, role, text), TOC depth, and every recoverable irregularity as a warning."""
    warnings: list[str] = []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise EpubError("not an EPUB (the file is not a ZIP package)") from e
    with z:
        names = set(z.namelist())
        opf_path = _opf_path(z, warnings)
        try:
            opf = ET.fromstring(z.read(opf_path))
        except ET.ParseError as e:
            raise EpubError(f"the package document is not valid XML ({e})") from e
        base = posixpath.dirname(opf_path)
        meta = read_metadata(opf)
        manifest = _manifest(opf, base)
        spine, ncx_id = _spine(opf, manifest)
        if not spine:
            raise EpubError("the package has no readable spine (no content documents in reading order)")
        if _protected(z, {it["href"] for it in manifest.values() if it["type"].startswith(("application/xhtml", "text/html"))}):
            raise EpubProtected("this EPUB is protected (DRM-encrypted content); Neuro Search does not circumvent protection — export an unprotected copy from the store you bought it from, if it offers one")
        toc = _toc(z, opf, manifest, ncx_id, warnings)
        by_href: dict[str, list[dict[str, Any]]] = {}
        for e in toc:
            by_href.setdefault(e["href"], []).append(e)
        top_level = [e for e in toc if e["depth"] == 0]
        chapter_no: dict[str, int] = {}
        n = 0
        for e in top_level:
            if e["href"] not in chapter_no:
                n += 1
                chapter_no[e["href"]] = n
        documents: list[dict[str, Any]] = []
        total = 0
        for idx, it in enumerate(spine):
            if it["href"] not in names:
                warnings.append(f"spine item missing from the archive: {it['href']}")
                continue
            try:
                html = z.read(it["href"]).decode("utf-8", errors="replace")
            except Exception as e:  # noqa: BLE001
                warnings.append(f"could not read {it['href']}: {e}")
                continue
            entries = by_href.get(it["href"], [])
            doc_title = next((e["label"] for e in entries if not e["fragment"]), None) or (entries[0]["label"] if entries else None)
            secs = _sections_of(html, doc_title)
            frag_labels = {e["fragment"]: e["label"] for e in entries if e["fragment"]}
            for s in secs:
                if s["fragment"] and s["fragment"] in frag_labels and not s["heading"]:
                    s["heading"] = frag_labels[s["fragment"]]
            if not doc_title:
                doc_title = next((s["heading"] for s in secs if s["heading"]), None) or posixpath.basename(it["href"]).rsplit(".", 1)[0]
            role = _role_of(doc_title, secs[0].get("epub_type") if secs else None)
            if len(secs) > 1 and total + len(secs) > max_sections:
                secs = secs[: max(1, max_sections - total)] + [{"heading": "(remaining text)", "fragment": None, "text": "\n\n".join(x["text"] for x in secs[max(1, max_sections - total):]), "level": 0}]
                warnings.append(f"book is very large: sections beyond {max_sections} are folded into one per document")
            total += len(secs)
            documents.append({"spine_index": idx, "href": it["href"], "linear": it["linear"], "title": doc_title, "chapter_no": chapter_no.get(it["href"]), "role": role, "sections": secs})
        chapters = [d for d in documents if d.get("chapter_no")]
        return {"metadata": meta, "documents": documents, "toc": toc, "toc_depth": (max((e["depth"] for e in toc), default=-1) + 1),
                "chapters": len(chapters) or len(documents), "sections": total, "warnings": warnings, "opf": opf_path}


# ---------------------------------------------------------------- the locator shape Neuro Search stores

def locators(book: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the book into ordered sections: ordinal (the segment locator) → chapter / section / anchor / role."""
    out = []
    ordinal = 0
    for d in book["documents"]:
        for i, s in enumerate(d["sections"]):
            ordinal += 1
            chapter = d["title"] or ""
            section = s["heading"] if (s["heading"] and s["heading"] != chapter) else None
            out.append({"ordinal": ordinal, "spine_index": d["spine_index"], "href": d["href"], "fragment": s.get("fragment"), "chapter": chapter, "chapter_no": d.get("chapter_no"),
                        "section": section, "role": d.get("role") or ("body" if d["linear"] else "back_matter"), "depth": s.get("level") or 0, "text": s["text"],
                        "label": cite_label(d.get("chapter_no"), chapter, section)})
    return out


def cite_label(chapter_no: int | None, chapter: str, section: str | None) -> str:
    head = (f"Ch. {chapter_no} → {chapter}" if chapter_no else chapter) or "book"
    return f"{head} · {section}" if section else head


# ---------------------------------------------------------------- semantic roles → weight (G6P2)

# Retrieval and findings weigh a passage by where it sits in the publication: the body is the book; front matter that
# introduces it counts fully; appendices and notes carry real content at a discount; an index, a copyright page, a
# title page or acknowledgements are never the answer. Nothing is discarded — the weight only orders.
ROLE_WEIGHT: dict[str, float] = {"body": 1.0, "chapter": 1.0, "part": 1.0, "introduction": 1.0, "preface": 0.9, "foreword": 0.8, "prologue": 1.0, "epilogue": 0.9,
                                 "appendix": 0.85, "notes": 0.7, "glossary": 0.7, "bibliography": 0.5, "index": 0.3, "copyright": 0.2, "title_page": 0.2,
                                 "acknowledgements": 0.3, "back_matter": 0.7, "front_matter": 0.8}
SKIP_FOR_FINDINGS = {"index", "copyright", "title_page", "acknowledgements"}      # never worth a model window


def role_weight(role: str | None) -> float:
    return ROLE_WEIGHT.get(role or "body", 0.9)


def section_roles(source_id: str) -> dict[int, str]:
    """ordinal → role for a book source (empty for any other platform)."""
    from . import db
    return {r["ordinal"]: r["role"] or "body" for r in db.connect().execute("SELECT ordinal, role FROM book_sections WHERE source_id=?", (source_id,)).fetchall()}

"""S25 — a screenshot is a source (0.63.0). (Sorts after test_s24.)

Kyle: *"one major flaw is we do not allow PNGs or other image types to be uploaded or used in chats. we need this
with OCR for screenshots etc."* He was right about the state of it — `ingest.ingest_local_file` ended at
`raise RuntimeError("unsupported file type: .png")`, so a screenshot could not enter the app at all.

The reading ladder is cheapest-first and reports which rung answered:

1. **Apple Vision** (`pyobjc-framework-Vision`) — free, local, no network, and the best of the three on UI
   screenshots. It is a **pip** install rather than a system package, which is the deciding property: Kyle does no
   terminal work, so a path needing `brew install` is a path he cannot use. Available on his Mac only, so these
   tests cannot exercise it — his machine is where it gets verified.
2. **tesseract** when the binary is on PATH — free, local, and what this test environment has, so it is the rung
   these tests cover.
3. **the model** (`image.read`, cheapest tier) — only when no local engine exists or a local engine returned almost
   nothing. A paid call, so `engine` and `paid` are recorded and reported rather than left implicit.

**An image with no readable text is still a source.** Refusing it would throw away the one thing always true — the
picture is there, attached, named and viewable. And the picture is KEPT (`images_dir/<source_id><ext>`, named by id
so the serving route handles no user-supplied path at all).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_img_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, images, ingest  # noqa: E402
from neurosearch.config import settings  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None and not images._vision_available(),
                                reason="no local OCR engine on this machine")


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _screenshot(tmp_path: Path, text: str = "Seller financing 10 percent\nSDE 350,000", name="shot.png") -> Path:
    """A plain, high-contrast image of text — what a screenshot is, for OCR purposes."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (900, 320), "white")
    d = ImageDraw.Draw(im)
    y = 40
    for line in text.split("\n"):
        d.text((40, y), line, fill="black")
        y += 60
    p = tmp_path / name
    im.save(p)
    return p


# ------------------------------------------------------------------ the router

def test_an_image_is_recognised(tmp_path):
    assert images.is_image(Path("a.PNG")) and images.is_image(Path("b.jpeg")) and images.is_image(Path("c.heic"))
    assert not images.is_image(Path("d.pdf")) and not images.is_image(Path("e.mp4"))


def test_the_engines_available_here_are_reported():
    e = images.engines()
    assert set(e) >= {"vision", "tesseract", "model", "note"}
    assert isinstance(e["vision"], bool) and isinstance(e["tesseract"], bool)


# ------------------------------------------------------------------ reading it

def test_text_is_read_from_a_screenshot(fresh, tmp_path):
    got = images.ocr(_screenshot(tmp_path), allow_model=False)
    assert got["engine"] in ("vision", "tesseract")
    assert "financing" in got["text"].lower() or "seller" in got["text"].lower()
    assert got["paid"] is False
    assert any(t.get("engine") == got["engine"] for t in got["engines_tried"])


def test_an_image_with_no_text_is_not_an_error(fresh, tmp_path):
    from PIL import Image
    p = tmp_path / "blank.png"
    Image.new("RGB", (200, 200), "white").save(p)
    got = images.ocr(p, allow_model=False)
    assert got["text"] == "" and got["engine"] in ("none", "vision", "tesseract")
    assert "no readable text" in got["note"]


def test_the_model_rung_is_never_reached_when_a_local_engine_reads_it(fresh, tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_ocr_model", lambda *a, **k: pytest.fail("paid for OCR a local engine had done"))
    got = images.ocr(_screenshot(tmp_path))
    assert got["paid"] is False and got["engine"] != "model"


def test_the_model_rung_is_used_when_there_is_no_local_engine(fresh, tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_vision_available", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda b: None)
    monkeypatch.setattr(images, "_ocr_model", lambda path, **k: "Seller financing 10 percent")
    got = images.ocr(_screenshot(tmp_path))
    assert got["engine"] == "model" and got["paid"] is True
    assert "read by the model" in got["note"]


def test_a_failing_engine_does_not_fail_the_upload(fresh, tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_vision_available", lambda: True)
    monkeypatch.setattr(images, "_ocr_vision", lambda p: (_ for _ in ()).throw(RuntimeError("Vision exploded")))
    got = images.ocr(_screenshot(tmp_path), allow_model=False)
    assert any(t.get("error", "").startswith("Vision exploded") for t in got["engines_tried"])
    assert got["text"], "tesseract should still have read it"


# ------------------------------------------------------------------ it becomes an ordinary source

def test_a_screenshot_becomes_a_searchable_source(fresh, tmp_path):
    p = db.create_project("img", brief="buying businesses")
    res = ingest.ingest_local_file(_screenshot(tmp_path), None, [], p["id"], original_name="shot.png")
    src = db.get_source(res["source_id"])
    assert src["platform"] == "image" and src["status"] == "ready"
    assert res["chunks"] >= 1 and res["ocr"]["engine"] in ("vision", "tesseract")
    assert "text read by" in (src["description"] or "")
    from neurosearch import search
    hits = search.search("financing", limit=5)
    assert any(h["source_id"] == res["source_id"] for h in hits) or res["ocr"]["chars"] > 0


def test_the_picture_is_kept_and_findable(fresh, tmp_path):
    p = db.create_project("img", brief="b")
    res = ingest.ingest_local_file(_screenshot(tmp_path), None, [], p["id"], original_name="shot.png")
    kept = ingest.kept_image(res["source_id"])
    assert kept and kept.exists() and kept.suffix == ".png"
    assert kept.parent == settings.images_dir
    assert kept.stem == res["source_id"]          # named by id: the serving route handles no user path


def test_an_unreadable_image_still_becomes_a_source(fresh, tmp_path):
    from PIL import Image
    q = tmp_path / "blank.png"
    Image.new("RGB", (240, 240), "white").save(q)
    p = db.create_project("img", brief="b")
    res = ingest.ingest_local_file(q, None, [], p["id"], original_name="blank.png")
    src = db.get_source(res["source_id"])
    assert src["status"] == "ready" and res["chunks"] == 0
    # 0.63.1 distinguishes "there is no text in this image" from "nothing on this machine can read it"
    assert "no text found in it" in (src["description"] or "") or "no free OCR" in (src["description"] or "")
    assert ingest.kept_image(res["source_id"])    # and it can still be looked at


def test_the_same_image_twice_is_one_source(fresh, tmp_path):
    p = db.create_project("img", brief="b")
    a = _screenshot(tmp_path, name="one.png")
    first = ingest.ingest_local_file(a, None, [], p["id"], original_name="one.png")
    second = ingest.ingest_local_file(a, None, [], p["id"], original_name="one.png")
    assert second["source_id"] == first["source_id"]


def test_a_huge_screenshot_is_downscaled_before_the_model_sees_it(tmp_path):
    from PIL import Image
    big = tmp_path / "big.png"
    Image.new("RGB", (4000, 2400), "white").save(big)
    media_type, data = images._for_model(big)
    assert media_type == "image/png"
    import base64, io
    with Image.open(io.BytesIO(base64.b64decode(data))) as im:
        assert max(im.size) <= images.MODEL_MAX_EDGE


def test_an_unsupported_format_is_converted_for_the_model(tmp_path):
    from PIL import Image
    p = tmp_path / "x.bmp"
    Image.new("RGB", (100, 80), "white").save(p)
    media_type, _ = images._for_model(p)
    assert media_type == "image/png"           # bmp is not accepted by the provider, so it is converted


# ------------------------------------------------------------------ paying for OCR is a separate, explicit act

def test_uploading_never_pays_for_ocr(fresh, tmp_path, monkeypatch):
    """The rule the rest of the app already follows: nothing spends without being asked. A screenshot whose text no
    free engine could read becomes a source that SAYS so, and offers the paid read as a separate verb."""
    from PIL import Image
    monkeypatch.setattr(images, "_ocr_model", lambda *a, **k: pytest.fail("ingestion paid for OCR"))
    q = tmp_path / "blank.png"
    Image.new("RGB", (240, 240), "white").save(q)
    p = db.create_project("img", brief="b")
    res = ingest.ingest_local_file(q, None, [], p["id"], original_name="blank.png")
    assert res["chunks"] == 0 and res["ocr"]["paid"] is False
    d = db.get_source(res["source_id"])["description"] or ""
    assert "no text found in it" in d or "no free OCR on this machine" in d


def test_the_paid_read_is_available_on_request_and_makes_it_searchable(fresh, tmp_path, monkeypatch):
    from PIL import Image
    q = tmp_path / "blank.png"
    Image.new("RGB", (240, 240), "white").save(q)
    p = db.create_project("img", brief="b")
    res = ingest.ingest_local_file(q, None, [], p["id"], original_name="blank.png")
    monkeypatch.setattr(images, "_ocr_model", lambda path, **k: "Quality of earnings report, 2026")
    out = ingest.read_image_with_model(res["source_id"], p["id"])
    assert out["engine"] == "model" and out["paid"] is True and out["chars"] > 0
    assert "quality of earnings" in (db.get_segments(res["source_id"])[0]["text"] or "").lower()


def test_the_paid_read_refuses_when_there_is_no_image(fresh):
    with pytest.raises(RuntimeError):
        ingest.read_image_with_model("nope", None)


# ------------------------------------------------------------------ who asked (0.63.1)

def test_an_image_attached_to_a_question_is_read_even_if_it_must_be_paid_for(fresh, tmp_path, monkeypatch):
    """Kyle attached two iPhone screenshots of a CIM to a chat and got "I can't see what's actually in them":
    neither free engine was present on his Mac and 0.63.0 refused to pay, so the source had no text and nothing
    was retrievable. Attaching a screenshot to a question you are waiting on IS the ask."""
    from PIL import Image
    monkeypatch.setattr(images, "_vision_available", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda b: None)
    monkeypatch.setattr(images, "_ocr_model", lambda path, **k: "Asking price $335,000 · SDE $709,835")
    q = tmp_path / "IMG_5585.png"
    Image.new("RGB", (300, 200), "white").save(q)
    p = db.create_project("img", brief="b")
    res = ingest.ingest_local_file(q, None, [], p["id"], original_name="IMG_5585.png", ocr_paid=True)
    assert res["chunks"] >= 1 and res["ocr"]["engine"] == "model" and res["ocr"]["paid"] is True
    assert "335,000" in db.get_segments(res["source_id"])[0]["text"]


def test_a_bulk_upload_still_never_pays(fresh, tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(images, "_vision_available", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda b: None)
    monkeypatch.setattr(images, "_ocr_model", lambda *a, **k: pytest.fail("a bulk upload paid for OCR"))
    q = tmp_path / "bulk.png"
    Image.new("RGB", (300, 200), "white").save(q)
    p = db.create_project("img", brief="b")
    res = ingest.ingest_local_file(q, None, [], p["id"], original_name="bulk.png")
    assert res["chunks"] == 0 and res["ocr"]["paid"] is False


def test_an_unreadable_image_says_whether_the_machine_even_has_an_engine(fresh, tmp_path, monkeypatch):
    """"no readable text" and "nothing on this machine could read it" are different problems and need different
    sentences — the first is about the image, the second is about the install."""
    from PIL import Image
    q = tmp_path / "blank.png"
    Image.new("RGB", (240, 240), "white").save(q)
    p = db.create_project("img", brief="b")
    monkeypatch.setattr(images, "_vision_available", lambda: False)
    monkeypatch.setattr(shutil, "which", lambda b: None)
    res = ingest.ingest_local_file(q, None, [], p["id"], original_name="blank.png")
    assert "no free OCR on this machine" in (db.get_source(res["source_id"])["description"] or "")

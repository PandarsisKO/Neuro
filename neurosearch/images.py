"""Images as sources: a screenshot becomes searchable text, and stays viewable ($0 wherever possible).

Kyle: *"one major flaw is we do not allow PNGs or other image types to be uploaded or used in chats. we need this
with OCR for screenshots etc."* He was exactly right about the state of it — `ingest.ingest_local_file` ended in
`raise RuntimeError("unsupported file type: .png")`, so a screenshot could not enter the app at all.

**The reading ladder, cheapest first, and it reports which rung answered.** The app's rule is the cheapest tier that
can do the job, and for OCR that ordering is unusually clear-cut:

1. **`vision` — Apple's Vision framework** via `pyobjc-framework-Vision`. Free, local, no network, and excellent on
   exactly the material Kyle has: UI screenshots, PDFs-as-pictures, dashboards. It is a **pip** install rather than
   a system package, which matters more than it sounds: Kyle does no terminal work, so a path that needs
   `brew install` is a path he cannot use. Available on his Mac and nowhere else.
2. **`tesseract`** when the binary is on PATH. Free, local, and what the Linux test environment has — so this is the
   rung the automated tests exercise.
3. **`model`** — the `image.read` contract, on the cheapest vision-capable tier. Used ONLY when no local engine is
   available or when a local engine returned almost nothing from an image that plainly contains text. It is a paid
   call, so it is never silent: the engine is recorded on the source and reported to the caller.

**An image with no readable text is still a source.** A photo of a whiteboard that OCR cannot read, or a chart with
no labels, is ingested with whatever text was found (often none) and says so. Refusing it would lose the one thing
the app can always offer — that the image is *there*, attached to the project, viewable, with its filename and the
context it arrived in.

Nothing here changes an existing path: `is_image` extends the same `ingest_local_file` router that `is_document`
and `is_media` already feed, and the result is an ordinary source with ordinary chunks, so search, findings, Claims
and citations work on a screenshot exactly as they do on a transcript.
"""
from __future__ import annotations

import base64
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif"}

# What the model path may be handed. Anthropic accepts png/jpeg/gif/webp; anything else is converted first, and a
# very large screenshot is downscaled because tokens scale with pixels and a 5K screenshot is mostly empty space.
MODEL_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".webp": "image/webp"}
MODEL_MAX_EDGE = 1568          # Anthropic's own guidance: a longer edge buys tokens, not accuracy
MODEL_MAX_BYTES = 4_500_000

# Below this, a local engine is treated as having failed to read an image rather than having read an empty one, so
# the model rung is allowed to try. Deliberately small: a screenshot of a menu bar legitimately has few characters.
THIN_TEXT_CHARS = 24

OCR_PROMPT = ("Transcribe every piece of text visible in this image, in reading order. Include labels, buttons, "
              "table cells, numbers, axis labels and captions. Do not describe the image, do not summarise, do not "
              "add commentary, and do not guess at text that is cut off or illegible — transcribe only what is "
              "actually legible. If the image contains no text at all, reply with exactly: NO TEXT")


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def engines() -> dict[str, Any]:
    """Which rungs are actually available here, so the app can say so rather than discovering it mid-upload."""
    return {"vision": _vision_available(), "tesseract": bool(shutil.which("tesseract")),
            "model": True,  # the contract always exists; whether it is allowed to run is the caller's decision
            "note": "Apple Vision and tesseract are free and local; the model rung is a paid call and is only used "
                    "when neither is available or a local engine read almost nothing"}


def _vision_available() -> bool:
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
    except Exception:  # noqa: BLE001 — absent on every non-mac, which is not an error
        return False
    return True


def _ocr_vision(path: Path) -> str:
    """Apple's Vision framework, in-process, no network, no subprocess.

    `VNRecognizeTextRequest` with `accurate` recognition is what macOS itself uses for Live Text, and on UI
    screenshots it is better than tesseract at small anti-aliased type — which is most of what a screenshot is."""
    import Quartz
    import Vision
    url = Quartz.CFURLCreateWithFileSystemPath(None, str(path), Quartz.kCFURLPOSIXPathStyle, False)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if not src:
        raise RuntimeError("Vision could not open the image")
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if not cg:
        raise RuntimeError("Vision could not decode the image")
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1)                       # 1 = accurate (0 = fast)
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision failed: {err}")
    lines = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if cand and len(cand):
            lines.append(str(cand[0].string()))
    return "\n".join(lines).strip()


def _ocr_tesseract(path: Path) -> str:
    out = subprocess.run(["tesseract", str(path), "stdout"], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "tesseract failed").strip()[:200])
    return (out.stdout or "").strip()


def _for_model(path: Path) -> tuple[str, str]:
    """(media_type, base64) — converted and downscaled as needed. Tokens scale with pixels, so a 5120-wide
    screenshot is resized rather than sent whole; the text stays legible well below Anthropic's own 1568 guidance.

    Pillow is how the resizing and converting is done, but it is **not** allowed to be the reason the rung fails.
    Kyle's two CIM screenshots came back "no readable text found" on a machine where nothing could read them: no
    Vision, no tesseract, and the model rung raised `ImportError` inside this function because the app had not been
    relaunched since Pillow was added. Anthropic accepts png/jpeg/gif/webp and downscales oversized images itself, so
    without Pillow an already-acceptable file is sent as it is — more tokens than necessary, and the right answer."""
    ext = path.suffix.lower()
    try:
        from PIL import Image
    except ImportError:
        if ext in MODEL_MEDIA_TYPES and path.stat().st_size <= MODEL_MAX_BYTES:
            return MODEL_MEDIA_TYPES[ext], base64.b64encode(path.read_bytes()).decode()
        raise RuntimeError(
            f"{ext} images need Pillow to be converted before the model can read them, and it is not installed here"
        ) from None
    with Image.open(path) as im:
        im.load()
        w, h = im.size
        needs_convert = ext not in MODEL_MEDIA_TYPES
        needs_resize = max(w, h) > MODEL_MAX_EDGE or path.stat().st_size > MODEL_MAX_BYTES
        if not needs_convert and not needs_resize:
            return MODEL_MEDIA_TYPES[ext], base64.b64encode(path.read_bytes()).decode()
        if max(w, h) > MODEL_MAX_EDGE:
            scale = MODEL_MAX_EDGE / float(max(w, h))
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        import io
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return "image/png", base64.b64encode(buf.getvalue()).decode()


def _ocr_model(path: Path, *, project_id: str | None, source_id: str | None) -> str:
    from . import providers, usage
    media_type, data = _for_model(path)
    resp = providers.invoke(
        "image.read",
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
            {"type": "text", "text": OCR_PROMPT}]}])
    usage.record_anthropic(resp, "image", project_id=project_id, source_id=source_id)
    text = providers.text_of(resp).strip()
    return "" if text.upper().startswith("NO TEXT") else text


def ocr(path: Path, *, allow_model: bool = True, project_id: str | None = None,
        source_id: str | None = None) -> dict[str, Any]:
    """Read the text in one image. Returns `{text, engine, engines_tried, chars, paid, note}`.

    Never raises for an unreadable image: an image with no text is a legitimate source, and the caller decides what
    to do with an empty string. What it must never do is pretend — `engine` names the rung that produced the text,
    and `paid` says whether that cost anything."""
    tried: list[dict[str, Any]] = []
    text, engine = "", "none"
    for name, fn in (("vision", _ocr_vision), ("tesseract", _ocr_tesseract)):
        if name == "vision" and not _vision_available():
            tried.append({"engine": name, "skipped": "not installed (macOS only)"})
            continue
        if name == "tesseract" and not shutil.which("tesseract"):
            tried.append({"engine": name, "skipped": "binary not on PATH"})
            continue
        try:
            got = (fn(path) or "").strip()
            tried.append({"engine": name, "chars": len(got)})
            if len(got) >= THIN_TEXT_CHARS:
                text, engine = got, name
                break
            if got and not text:
                text, engine = got, name          # keep the thin read; the model rung may still improve on it
        except Exception as e:  # noqa: BLE001 — a failed engine is a fact about this machine, not a failed upload
            tried.append({"engine": name, "error": str(e)[:160]})
            log.warning("%s OCR failed on %s: %s", name, path.name, e)
    paid = False
    if allow_model and len(text) < THIN_TEXT_CHARS:
        try:
            got = _ocr_model(path, project_id=project_id, source_id=source_id).strip()
            tried.append({"engine": "model", "chars": len(got)})
            if len(got) > len(text):
                text, engine, paid = got, "model", True
            else:
                paid = True                        # it ran and was charged even if it added nothing
        except Exception as e:  # noqa: BLE001
            tried.append({"engine": "model", "error": str(e)[:160]})
            log.warning("model OCR failed on %s: %s", path.name, e)
    note = ""
    ran = [t for t in tried if "chars" in t]
    if not text and not ran:
        # Nothing could read it, which is a fact about this machine and not about the image. Saying "no text found"
        # here is the mistake that stranded Kyle's two CIM screenshots: both were dense with text.
        why = "; ".join(f"{t['engine']}: {t.get('skipped') or t.get('error')}" for t in tried) or "no engine ran"
        note = ("nothing on this machine could read this image, so it has not been read yet — it is attached and "
                f"viewable. ({why})")
    elif not text:
        note = ("no readable text was found in this image — it is attached to the project and viewable, but there "
                "is nothing to search")
    elif engine == "model":
        note = "read by the model (no free local OCR was available on this machine, or it read almost nothing)"
    return {"text": text, "engine": engine, "engines_tried": tried, "chars": len(text), "paid": paid, "note": note}

"""Shared readers for the static frontend after its CSS/ES-module split."""
from pathlib import Path


def ui_source(web_dir: Path) -> str:
    """Return the shipped frontend text for static contract assertions.

    The HTML shell no longer contains JavaScript or CSS; tests that inspect a
    rendered/template contract should read the complete static asset set.
    """
    return "\n".join([
        (web_dir / "index.html").read_text(),
        (web_dir / "styles.css").read_text(),
        *[p.read_text() for p in sorted((web_dir / "js").glob("*.js"))],
    ])

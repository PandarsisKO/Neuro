"""Spreadsheets as sources AND as calculators.

A workbook is read twice: once as text (each sheet becomes a "page" of `label = value` lines so it is searchable
and citable like a document), and once as a live model (the `formulas` package evaluates the workbook's own
formulas, so the chat can change inputs and read the recomputed outputs — the user's spreadsheet is the
calculator, we never re-implement its maths).

Inputs = numeric constants that have a text label next to them; outputs = formula cells with a label.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

SHEET_EXT = (".xlsx", ".xlsm", ".xls", ".csv")
MAX_CELLS_TEXT = 4000        # per sheet, for the text rendering
MAX_LABELLED = 80            # inputs/outputs listed per workbook


def is_spreadsheet(path: Path) -> bool:
    return path.suffix.lower() in SHEET_EXT


def files_dir() -> Path:
    d = settings.data_dir / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_file(src: Path, source_id: str, suffix: str) -> Path:
    dest = files_dir() / f"{source_id}{suffix.lower()}"
    shutil.copyfile(src, dest)
    return dest


# ------------------------------------------------------------------ reading

def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.2f}".rstrip("0").rstrip(".")
        return f"{v:.6g}"
    return str(v).strip()


def _label_for(ws: Any, row: int, col: int, values: dict[tuple[int, int], Any]) -> str | None:
    """Nearest text cell to the left on the same row, else directly above in the column."""
    for c in range(col - 1, max(0, col - 4), -1):
        v = values.get((row, c))
        if isinstance(v, str) and v.strip() and not v.startswith("="):
            return v.strip()
    for r in range(row - 1, max(0, row - 3), -1):
        v = values.get((r, col))
        if isinstance(v, str) and v.strip() and not v.startswith("="):
            return v.strip()
    return None


def read_workbook(path: Path) -> dict[str, Any]:
    """Returns {"sheets": [{"name", "text"}], "inputs": [...], "outputs": [...]}.
    inputs/outputs: {"cell": "Sheet!B3", "label": str, "value": current cached value}."""
    if path.suffix.lower() == ".csv":
        import csv
        rows = list(csv.reader(path.open(newline="", encoding="utf-8", errors="replace")))
        text = "\n".join(" | ".join(c for c in r) for r in rows[:2000])
        return {"sheets": [{"name": path.stem, "text": text}], "inputs": [], "outputs": []}

    import openpyxl
    wb_f = openpyxl.load_workbook(path, data_only=False, read_only=True)     # formulas
    wb_v = openpyxl.load_workbook(path, data_only=True, read_only=True)      # cached values
    sheets, inputs, outputs = [], [], []
    for ws_f in wb_f.worksheets:
        ws_v = wb_v[ws_f.title]
        vals: dict[tuple[int, int], Any] = {}
        forms: dict[tuple[int, int], str] = {}
        n = 0
        for row in ws_f.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                n += 1
                if n > MAX_CELLS_TEXT:
                    break
                if isinstance(c.value, str) and c.value.startswith("="):
                    forms[(c.row, c.column)] = c.value
                else:
                    vals[(c.row, c.column)] = c.value
            if n > MAX_CELLS_TEXT:
                break
        cached: dict[tuple[int, int], Any] = {}
        for row in ws_v.iter_rows(max_row=min(ws_v.max_row or 1, 2000)):
            for c in row:
                if c.value is not None:
                    cached[(c.row, c.column)] = c.value
        # text rendering: one line per row, "label = value" pairs
        lines = [f"Sheet: {ws_f.title}"]
        by_row: dict[int, list[str]] = {}
        for (r, cidx), v in sorted({**vals, **{k: cached.get(k, f) for k, f in forms.items()}}.items()):
            from openpyxl.utils import get_column_letter
            s = _fmt(v)
            if s:
                by_row.setdefault(r, []).append(f"{get_column_letter(cidx)}{r}: {s}")
        for r in sorted(by_row):
            lines.append(" | ".join(by_row[r]))
        sheets.append({"name": ws_f.title, "text": "\n".join(lines)})
        # labelled inputs / outputs
        from openpyxl.utils import get_column_letter
        for (r, cidx), v in vals.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and len(inputs) < MAX_LABELLED:
                lab = _label_for(ws_f, r, cidx, vals)
                if lab:
                    inputs.append({"cell": f"{ws_f.title}!{get_column_letter(cidx)}{r}", "label": lab, "value": v})
        for (r, cidx), f in forms.items():
            if len(outputs) < MAX_LABELLED:
                lab = _label_for(ws_f, r, cidx, vals)
                if lab:
                    outputs.append({"cell": f"{ws_f.title}!{get_column_letter(cidx)}{r}", "label": lab, "value": cached.get((r, cidx)), "formula": f[:120]})
    return {"sheets": sheets, "inputs": inputs, "outputs": outputs}


# ------------------------------------------------------------------ calculating

_models: dict[str, Any] = {}
_lock = threading.Lock()


def _model(path: Path) -> Any:
    key = f"{path}:{path.stat().st_mtime}"
    with _lock:
        m = _models.get(key)
        if m is None:
            import formulas
            m = formulas.ExcelModel().loads(str(path)).finish()
            _models.clear()
            _models[key] = m
        return m


def _ref(path: Path, cell: str) -> str:
    sheet, addr = cell.split("!", 1) if "!" in cell else ("Sheet1", cell)
    return f"'[{path.name}]{sheet.strip(chr(39)).upper()}'!{addr.upper()}"


def resolve(name: str, model: dict[str, Any], which: str) -> str | None:
    """Turn a label ("purchase price") or an address ("Deal!B1") into a cell address."""
    if re.match(r"^[^!]+![A-Za-z]{1,3}\d+$", name) or re.match(r"^[A-Za-z]{1,3}\d+$", name):
        if "!" not in name and model.get("sheets"):
            return f"{model['sheets'][0]['name']}!{name}"
        return name
    key = name.strip().lower()
    cands = model.get(which) or []
    for c in cands:
        if c["label"].strip().lower() == key:
            return c["cell"]
    for c in cands:
        if key in c["label"].lower() or c["label"].lower() in key:
            return c["cell"]
    return None


def calculate(source_id: str, inputs: dict[str, Any], outputs: list[str] | None = None) -> dict[str, Any]:
    """Set inputs (by label or address), recompute, return the requested (or all labelled) outputs."""
    model = load_model(source_id)
    path = files_dir() / model["file"]
    if not path.exists():
        raise RuntimeError("the spreadsheet file is missing — upload it again")
    m = _model(path)
    set_in: dict[str, Any] = {}
    unknown: list[str] = []
    for k, v in (inputs or {}).items():
        cell = resolve(k, model, "inputs")
        if not cell:
            unknown.append(k)
            continue
        try:
            v = float(str(v).replace(",", "").replace("$", "").replace("%", "")) if not isinstance(v, (int, float)) else v
        except ValueError:
            pass
        set_in[_ref(path, cell)] = v
    want = outputs or [o["cell"] for o in model.get("outputs") or []]
    want_cells = [resolve(w, model, "outputs") or w for w in want]
    refs = [_ref(path, c) for c in want_cells]
    sol = m.calculate(inputs=set_in or None, outputs=refs) if set_in else m.calculate(outputs=refs)
    out: dict[str, Any] = {}
    labels = {o["cell"].upper(): o["label"] for o in model.get("outputs") or []}
    for c, r in zip(want_cells, refs):
        v = sol.get(r)
        val = getattr(v, "value", v)
        try:
            val = val[0][0]
        except (TypeError, IndexError, KeyError):
            pass
        if hasattr(val, "item"):
            val = val.item()
        out[labels.get(c.upper(), c)] = val
    return {"outputs": out, "inputs_applied": {k: v for k, v in (inputs or {}).items() if k not in unknown}, "unknown_inputs": unknown}


def save_model(source_id: str, filename: str, model: dict[str, Any]) -> None:
    db.kv_set(f"sheet:{source_id}", json.dumps({"file": filename, "sheets": [{"name": s["name"]} for s in model["sheets"]],
                                                 "inputs": model["inputs"], "outputs": model["outputs"]}, default=str))


def load_model(source_id: str) -> dict[str, Any]:
    raw = db.kv_get(f"sheet:{source_id}")
    if not raw:
        raise RuntimeError("not a spreadsheet source")
    return json.loads(raw)


def calculators_for_project(project_id: str) -> list[dict[str, Any]]:
    """Spreadsheet sources of a project with their labelled inputs/outputs (for the chat's tool description)."""
    out = []
    ids = set(db.project_source_ids(project_id))
    for s in db.list_sources(limit=100000):
        if s["id"] in ids and s["platform"] == "spreadsheet":
            try:
                m = load_model(s["id"])
            except RuntimeError:
                continue
            out.append({"source_id": s["id"], "title": s["title"], "inputs": m["inputs"][:40], "outputs": m["outputs"][:40]})
    return out

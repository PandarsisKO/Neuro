"""Deterministic, report-only repository health checks.

This module deliberately inspects source and documentation only.  It never imports
the application, opens a database, contacts a provider, or mutates the checkout.
"""
from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    file: str
    location: str
    rule: str
    severity: str
    why: str


ROOT_FILES = {
    ".env.example", ".gitignore", "AGENTS.md", "AUDIT.md", "CLAUDE.md", "DESIGN-MISSION.md",
    "DESIGN.md", "DEVELOPMENT-OPERATING-SYSTEM.md", "Dockerfile", "EXTERNAL-AI-ACCESS-MISSION.md",
    "FIELD-MAP-RUNG.md", "FOUNDATION-HANDOFF.md", "HANDOFF.md", "HARDENING.md", "PRODUCT-SCHEDULER.md",
    "QA-STABILIZATION-MISSION.md", "QA-STABILIZATION-PROMPT.md", "QUALITY-CONTRACT.md", "README.md",
    "SCHEDULER.md", "SOURCE-CAPABILITY-RUNG.md", "SPEED-MISSION.md", "TRANSCRIPT-INTELLIGENCE-MISSION.md",
    "VESTIGIAL-INVENTORY.md", "fly.toml", "pyproject.toml", "restart.command", "start", "start.command",
    "run-findings-haiku-test.command", "run-haiku-comparison.command", "RUN THIS - Audit Instance.command",
}
DOCUMENTED_EXPERIMENTAL = {"neurosearch/planner_v3.py"}


def _py_files(root: Path):
    yield from sorted((root / "neurosearch").rglob("*.py"))


def _duplicate_definitions(root: Path, out: list[Finding]) -> None:
    for path in _py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        names: dict[str, list[int]] = {}
        for node in tree.body:  # top-level only; nested class methods are intentional
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.setdefault(node.name, []).append(node.lineno)
        for name, lines in sorted(names.items()):
            if len(lines) > 1:
                out.append(Finding(str(path.relative_to(root)), ",".join(map(str, lines)),
                                   "duplicate-definition", "warning",
                                   f"top-level name {name!r} is defined {len(lines)} times in one module"))


def _duplicate_routes(root: Path, out: list[Finding]) -> None:
    routes: dict[tuple[str, str], list[tuple[Path, int]]] = {}
    for path in _py_files(root):
        try: tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError): continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in {"get", "post", "put", "delete", "patch", "api_route"}
                        and dec.args and isinstance(dec.args[0], ast.Constant)
                        and isinstance(dec.args[0].value, str)):
                    key = (dec.func.attr.upper(), dec.args[0].value)
                    routes.setdefault(key, []).append((path, node.lineno))
    for (method, route), locations in sorted(routes.items()):
        if len(locations) > 1:
            loc = ",".join(f"{p.relative_to(root)}:{line}" for p, line in locations)
            out.append(Finding(locations[0][0].relative_to(root).__str__(), loc,
                               "duplicate-route", "error", f"{method} {route} is registered more than once"))


def _root_hygiene(root: Path, out: list[Finding]) -> None:
    states = sorted(root.glob("STATE-OF-THE-APP-*.md"), key=lambda p: p.name)
    newest_state = states[-1].name if states else None
    for path in sorted(root.iterdir()):
        if path.name.startswith(".") or path.name in ROOT_FILES or path.name == newest_state or path.name in {"docs", "evals", "extension", "neurosearch", "tests", "data", "data_backup_2026-09-03", "VIDEOS", "_to_delete", "INSPIRATION", "Claude outputs", ".venv", ".worktrees", "neurosearch.egg-info"}:
            continue
        out.append(Finding(path.name, "1", "unexpected-root-entry", "warning",
                           "root-level entry is not in the documented repository allowlist"))


def _suspicious_names(root: Path, out: list[Finding]) -> None:
    pat = re.compile(r"(^|/)(?:new_|old_|backup_|copy_|.*_v\d+\.)")
    for base in (root / "neurosearch", root / "tests"):
        for path in sorted(base.rglob("*")):
            rel = path.relative_to(root)
            if "__pycache__" in rel.parts:
                continue
            if str(rel) in DOCUMENTED_EXPERIMENTAL:
                continue
            if path.is_file() and pat.search(str(rel)):
                out.append(Finding(str(path.relative_to(root)), "1", "suspicious-filename", "warning",
                                   "filename suggests an experimental or duplicate implementation"))


def _broken_markdown_links(root: Path, out: list[Finding]) -> None:
    link_re = re.compile(r"\[[^]]+\]\(([^)#]+)")
    for path in sorted(root.glob("*.md")):
        try: text = path.read_text(encoding="utf-8")
        except OSError: continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for target in link_re.findall(line):
                if ("://" in target or target.startswith("mailto:") or target.startswith("#")
                        or target in {"link", "URL", "path"}):
                    continue
                candidate = (path.parent / target).resolve()
                if not candidate.exists():
                    out.append(Finding(str(path.relative_to(root)), str(line_no), "broken-reference", "warning",
                                       f"local Markdown target does not exist: {target}"))


def _forbidden_boundaries(root: Path, out: list[Finding]) -> None:
    """Catch the one boundary that is unambiguous without architecture heuristics."""
    for path in _py_files(root):
        if path.name in {"db.py", "repo_check.py"}:
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "sqlite3.connect(" in line:
                out.append(Finding(str(path.relative_to(root)), str(line_no), "direct-db-connection", "error",
                                   "SQLite connections belong to neurosearch/db.py so lifecycle and isolation rules stay centralized"))


def check_repo(root: str | Path = ".") -> list[Finding]:
    """Return stable findings sorted by file, location, rule, and message."""
    base = Path(root).resolve()
    findings: list[Finding] = []
    _duplicate_definitions(base, findings)
    _duplicate_routes(base, findings)
    _root_hygiene(base, findings)
    _suspicious_names(base, findings)
    _broken_markdown_links(base, findings)
    _forbidden_boundaries(base, findings)
    return sorted(findings, key=lambda f: (f.file, f.location, f.rule, f.why))


def render(findings: list[Finding], *, as_json: bool = False) -> str:
    if as_json:
        import json
        return json.dumps([asdict(f) for f in findings], indent=2, sort_keys=True) + "\n"
    if not findings:
        return "repo-check: PASS (no findings)\n"
    lines = [f"repo-check: {len(findings)} finding(s)"]
    lines.extend(f"{f.severity.upper()} {f.rule} {f.file}:{f.location} — {f.why}" for f in findings)
    return "\n".join(lines) + "\n"

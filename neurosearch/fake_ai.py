"""Deterministic stand-ins for the Anthropic and OpenAI clients.

Used by the tests, by `NEUROSEARCH_FAKE_AI=1` (the whole app runs with no keys and no network) and by the Tier-1
evals. They are *content-aware* rather than canned: the findings fake picks real lines out of the transcript it
was given, the answer fake cites the excerpts it was given, the embedding fake is a hashed bag-of-words so lexical
similarity actually retrieves — which is what lets the evidence validators and retrieval metrics mean something
without spending a cent. Set NEUROSEARCH_FAKE_AI_BAD_QUOTES=1 to make the findings fake hallucinate quotes, which is
how the quote validator is proven to catch them.

Handlers are chosen by the `task` the caller declares in `extra_headers["x-neurosearch-task"]` (the router seam);
until every caller sets one, a phrase in the system prompt still works.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import pathlib
import re
from typing import Any

import numpy as np

_WORD = re.compile(r"[a-z0-9']+")
_LINE = re.compile(r"^\[([^\]]+)\]\s*(.+)$", re.M)
STOP = set("the a an and or of to in on for with that this is are was were be it as at by from you your we our they "
           "their he she his her i my me not no but if so do does did have has had will would can could should about "
           "what which who how when where than then there these those into out up down over just like also more most "
           "some any all one two very really get got going go make made".split())


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 2]


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ------------------------------------------------------------------ Anthropic

PLAN = {
    "goal": {"outcome": "Move the marketing site off Squarespace to a faster, cheaper host without breaking email.",
             "constraints": ["budget under $500", "live by end of October"], "success": ["site loads < 1s", "no email downtime"], "evidence": []},
    "approach": {"recommended": "Static export + Cloudflare Pages", "why": "Cheapest recurring cost and the sources agree it handles small sites well.",
                 "alternatives": [{"option": "Webflow", "why_not": "recurring cost exceeds the budget"}], "basis": "research", "confidence": "medium", "evidence": []},
    "first_steps": [{"action": "Export the existing Squarespace site", "detail": "Save a complete local backup before touching DNS.", "today": True, "evidence": []},
                    {"action": "Document current DNS records", "detail": "Screenshot every record, especially MX.", "today": True}],
    "phases": [{"name": "Preparation", "objective": "Backups and inventory", "tasks": [{"task": "Export site", "detail": ""}, {"task": "List all pages and redirects"}],
                "dependencies": ["Squarespace admin access"], "decisions": [], "outcome": "Nothing can be lost"}],
    "dependencies": [{"item": "Registrar login", "blocking": True, "note": "Needed before DNS changes"}, {"item": "Analytics choice", "blocking": False}],
    "decisions": [{"decision": "Which host", "options": ["Cloudflare Pages", "Netlify"], "recommended": "Cloudflare Pages", "why": "free tier suffices",
                   "when": "now", "by_phase": "Phase 2", "basis": "research", "evidence": []}],
    "tools": [{"need": "Hosting", "tool": "Cloudflare Pages", "free_option": "yes", "premium_option": "n/a", "cost": "$0", "why": "static hosting", "tier": "required", "basis": "research"}],
    "costs": {"upfront": [{"item": "Domain transfer", "amount": "$10-15"}], "recurring": [], "optional": [], "services": [], "contingency": "$50",
              "minimum": "$15", "recommended": "$65", "premium": "$300+", "note": "Estimates.", "evidence": []},
    "risks": [{"risk": "DNS change breaks email", "mitigation": "Do not touch MX records.", "priority": "high"}],
    "gotchas": [{"gotcha": "Domain may be registered with Squarespace itself", "avoid": "Check the registrar before Phase 3."}],
    "defer": [{"item": "Analytics platform", "until": "after launch"}],
    "open_questions": [{"question": "Where is the domain registered?", "category": "blocking", "why": "Changes the migration procedure",
                        "research_prompt": "Is our domain registered directly with Squarespace or a third-party registrar?"}],
    "confidence": [{"area": "Hosting choice", "level": "high", "note": "two sources agree"}, {"area": "Timeline", "level": "needs_research", "note": "depends on registrar"}],
    "ready": {"first_three": ["Export the site", "Document DNS", "Create Cloudflare account"], "initial_cost": "~$15", "need_before": ["Squarespace admin login"], "blockers": []},
    "this_week": [{"action": "Export the Squarespace site to a local folder", "why": "backup before anything", "time": "30 min"}],
    "refine_questions": [{"question": "Where is the domain registered?", "why": "changes the DNS procedure", "kind": "fact", "options": ["Squarespace", "GoDaddy", "Other"]},
                         {"question": "Do you need a contact form?", "why": "static hosts need a form service", "kind": "decision", "options": ["Yes", "No"]}],
}
UPDATES = {"updates": [{"section": "Recommended approach", "previous": "Static export + Cloudflare Pages", "proposed": "Static export + Netlify",
                        "reason": "New finding says Cloudflare form handling is limited."}]}
ANALYSIS = {"situation": "You have a small budget and a live site to move.", "swot": {
    "strengths": [{"point": "Existing content", "so_what": "Nothing to write, just move"}], "weaknesses": [{"point": "No DNS experience", "so_what": "Get help before touching records"}],
    "opportunities": [{"point": "Static hosting is free", "so_what": "Recurring cost can drop to zero", "evidence": []}], "threats": [{"point": "Email breaks on DNS change", "so_what": "Sequence carefully", "evidence": []}]},
    "readiness": [{"area": "money", "level": "ready", "note": "budget covers it"}, {"area": "skills", "level": "gap", "note": "DNS"}],
    "options": [{"path": "Static + Cloudflare", "summary": "export and host free", "cost": "$0-15", "time_to_result": "1 week", "risk": "low", "fit": 5, "why_fit": "cheapest, sources agree", "evidence": []},
                {"path": "Webflow", "summary": "rebuild", "cost": "$20/mo", "time_to_result": "3 weeks", "risk": "medium", "fit": 2, "why_fit": "over budget"}],
    "assumptions": [{"assumption": "Site is mostly static", "if_wrong": "need a CMS", "how_to_check": "list dynamic features"}],
    "failure_patterns": [{"pattern": "Changing MX with the A record", "seen_in": "two videos", "avoid": "leave MX alone", "evidence": []}],
    "verdict": "Proceed with the static export path."}


class _Blk:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


_cache_seen: set[str] = set()      # simulated prompt cache: prefixes we have "written"
CACHE_MIN_TOKENS = 1024             # the provider ignores breakpoints on shorter prefixes (Sonnet/Opus minimum)
CACHE_LOG: list[dict[str, Any]] = []   # evals hook: one entry per request {task, total, read, write, breakpoints}; cleared by the cache-layout eval


def _tool_tokens(tools: Any) -> int:
    """Tool definitions are billed by their size like any other prompt text (the provider serialises the schemas)."""
    return _tokens(json.dumps(tools, default=str)) if tools else 0


def _simulate_cache(tools: Any, system: Any, messages: list[dict[str, Any]]) -> tuple[int, int]:
    """Prompt-cache simulation with the provider's rules: the prefix is tools → system blocks → message blocks in
    order; a `cache_control` block ends a cacheable prefix; the longest previously written prefix that matches
    exactly is READ; everything from there to the last breakpoint is WRITTEN; prefixes under CACHE_MIN_TOKENS are
    ignored. Prefix positions are measured on the same flattened text the fake bills, so read+write+plain == total."""
    seed = json.dumps(tools, sort_keys=True, default=str) if tools else ""   # tools are part of the prefix identity…
    base = _tool_tokens(tools)                        # …and of its length (tool schemas are billed like text)
    acc = ""
    marks: list[tuple[str, int]] = []                 # (prefix hash, tokens up to and including the block)

    def mark() -> None:
        marks.append((hashlib.sha1((seed + "\x00" + acc).encode()).hexdigest(), base + _tokens(acc)))

    sys_blocks = system if isinstance(system, list) else ([{"type": "text", "text": system}] if system else [])
    for b in sys_blocks:
        if isinstance(b, dict):
            acc += b.get("text", "")
            if b.get("cache_control"):
                mark()
    for m in messages:
        c = m.get("content")
        blocks = [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])
        for b in blocks:
            if isinstance(b, dict):
                acc += json.dumps(b.get("content")) if b.get("type") == "tool_result" else (b.get("text") or "")
                if b.get("cache_control"):
                    mark()
            else:
                acc += getattr(b, "text", "") or ""
    marks = [(h, n) for h, n in marks if n >= CACHE_MIN_TOKENS]
    read = 0
    for h, n in reversed(marks):                      # longest cached prefix wins
        if h in _cache_seen:
            read = n
            break
    write = 0
    if marks:
        last_h, last_n = marks[-1]
        if last_n > read:
            write = last_n - read
        for h, n in marks:
            if n > read:
                _cache_seen.add(h)
    return read, write


def _flatten(system: Any) -> tuple[str, list[str]]:
    """(system text, cached prefix hashes) — the fake honours cache_control so cache metrics show up in evals."""
    if isinstance(system, str):
        return system, []
    texts, hashes, acc = [], [], ""
    for b in system or []:
        if isinstance(b, dict):
            texts.append(b.get("text", ""))
            acc += b.get("text", "")
            if b.get("cache_control"):
                hashes.append(hashlib.sha1(acc.encode()).hexdigest())
    return "\n".join(texts), hashes


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            out.append(json.dumps(b.get("content")) if b.get("type") == "tool_result" else (b.get("text") or ""))
        else:
            out.append(getattr(b, "text", "") or "")
    return "\n".join(out)


def _with_evidence(obj: Any, ids: list[str]) -> Any:
    """Fill every empty "evidence" list with real ids from the material, so plan-evidence validation is meaningful."""
    if isinstance(obj, dict):
        return {k: (ids[:2] if k == "evidence" and isinstance(v, list) and not v else _with_evidence(v, ids)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_with_evidence(x, ids) for x in obj]
    return obj


def _findings(system: str, user: str) -> str:
    bad = os.environ.get("NEUROSEARCH_FAKE_AI_BAD_QUOTES") == "1"
    m = re.search(r"BRIEF:\s*(.+)", system)
    brief_words = set(_words(m.group(1) if m else "") or _words(system)[:30])
    lines = _LINE.findall(user)
    scored = []
    for pos, (ts, text) in enumerate(lines):
        ws = _words(text)
        overlap = len(set(ws) & brief_words)
        scored.append((overlap, len(ws), -pos, ts, text))
    scored.sort(reverse=True)
    picks = [s for s in scored if s[1] >= 4][:5]
    findings = []
    for overlap, _n, negpos, ts, text in picks:
        words = text.split()
        quote = " ".join(words[:12]) if not bad else "this exact phrase appears nowhere in the transcript"
        findings.append({"title": " ".join(words[:6]).rstrip(",.;:"), "finding": "Detail: " + " ".join(words[12:40]),
                         "ts": ts, "quote": quote, "importance": min(5, 2 + overlap)})
    first = lines[0][1] if lines else ""
    substance = min(100, 20 + 15 * sum(1 for s in scored if s[0] > 0)) if lines else 0
    return json.dumps({"summary": "Covers " + " ".join(first.split()[:25]) + ".", "substance": substance, "findings": findings})


def _answer(system: str, messages: list[dict[str, Any]], task: str = "answer.chat") -> str:
    text = system + "\n" + "\n".join(_content_text(m.get("content")) for m in messages)
    bad = os.environ.get("NEUROSEARCH_FAKE_AI_BAD_CITATIONS")
    if bad and (task != "answer.repair" or bad == "stubborn"):
        return "SBA loans normally require ten percent down [17]."
    ex = re.search(r"<excerpts>(.*?)</excerpts>", text, re.S)
    nums = re.findall(r"^\[(\d+)\] ", ex.group(1), re.M) if ex else []
    q = re.findall(r"Question:\s*(.+)", text)
    question = q[-1].strip() if q else ""
    if not nums or "no relevant excerpts" in (ex.group(1) if ex else ""):
        return "The sources do not cover that. Gap: add a source that addresses " + (question or "this") + "."
    body = ex.group(1)
    first = re.search(r"^\[1\] .*?\n(.*?)(?=\n\[\d+\] |\Z)", body, re.S | re.M)
    snippet = " ".join((first.group(1) if first else "").split()[:18])
    cites = "[1]" + (" [2]" if len(nums) > 1 else "")
    return f"On \"{question}\": the sources say \"{snippet}\" {cites}." + (" A second excerpt adds detail [2]." if len(nums) > 1 else "")


_RANK_STOP = {"that", "this", "with", "from", "have", "what", "when", "will", "your", "about", "into", "they", "them", "than", "then",
              "there", "their", "which", "would", "could", "should", "these", "those", "only", "also", "more", "most", "some", "such",
              "need", "needs", "want", "best", "videos", "video", "project", "score", "scores", "relevance", "relevant"}


def _updates(user: str) -> str:
    """Content-aware plan updates: one proposed change per NEW FINDING / NEW USER FACT line in the material (so an eval
    can check the new evidence was addressed); the canned update when there is nothing new."""
    def block(name: str) -> list[str]:
        m = re.search(name + r":\n((?:- .*\n?)*)", user)
        return [ln[2:].strip() for ln in (m.group(1).splitlines() if m else []) if ln.startswith("- ")]
    ups = [{"section": "Financing" if re.search(r"inject|lender|loan|seller note|standby|down", f, re.I) else "Research", "previous": "as planned",
            "proposed": f[:300], "reason": "New finding: " + f[:200]} for f in block("NEW FINDINGS")]
    ups += [{"section": "Constraints", "previous": "as planned", "proposed": f[:300], "reason": "New user fact: " + f[:200]} for f in block("NEW USER FACTS")]
    return json.dumps({"updates": ups} if ups else UPDATES)


def _synthesis(user: str) -> str:
    """A masterplan with the required sections, quoting the findings it was given and preserving their citation
    links verbatim (never inventing one) — content-aware so the export eval can check grounding."""
    name = (re.search(r"Project name:\s*(.+)", user) or re.search(r"(.+)", user)).group(1).strip()
    brief = (re.search(r"<brief>\s*(.*?)\s*</brief>", user, re.S) or re.search(r"(.{0,200})", user)).group(1).strip()
    finds = re.findall(r"^- (.+?)\n\s+(\[[^\]]+\]\([^)]+\)(?:\s*\[[^\]]+\]\([^)]+\))*)", user, re.M)
    insights = "\n".join(f"- {f[:160]} {links}" for f, links in finds) or "- (no findings yet)"
    return (f"# {name} — Masterplan\n\n## Purpose\n{brief}\n\n## Executive summary\nThe research covers the brief above. "
            f"{len(finds)} findings were reviewed. The main themes are financing, valuation and diligence. Each insight below keeps its citation. "
            f"Nothing here goes beyond the material.\n\n## Key insights\n{insights}\n\n## Recommended actions / how to use these insights\n"
            f"Start with the financing rules, then valuation, then the diligence checklist.\n\n## Open questions and gaps\n"
            f"Anything the findings do not cover is still open.\n\n## How to continue\nAdd lender interviews and broker calls as sources.\n")


def _rank(user: str, system: str = "") -> str:
    """Lexical stand-in for the ranker: a candidate scores by how many content words of the project head (brief, goal,
    questions) appear in its title/description. Deterministic, content-aware, and blind to the fixture's answer key."""
    head = system[system.find("PROJECT:"):] if "PROJECT:" in system else ""
    words = lambda t: {w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", t.lower()) if w not in _RANK_STOP}  # noqa: E731
    vocab = words(head)
    out = []
    for m in re.finditer(r"^\[(\d+)\] (.*)$", user, flags=re.M):
        i, line = int(m.group(1)), m.group(2)
        hits = len(vocab & words(line))
        out.append({"i": i, "score": min(100, 10 + 20 * hits), "why": "on topic" if hits >= 2 else "filler"})
    return json.dumps({"scores": out})


_PREFILTER_STOP = set("first days goal water know next find using much like done down away life light exact fair cover bring decide whether must looks months "
                      "questions rules source starting brief what when where which while would could should about after before other things thing every "
                      "still really little great never always people something going".split())


def _prefilter(user: str, system: str = "") -> str:
    """Lexical stand-in for the H1 window pre-filter: how densely the window uses the project head's content words.
    Conservative like the real prompt: 'drop' only when the window barely touches the brief's vocabulary; a single
    passage that does (a buried nugget) makes it 'uncertain'. NEUROSEARCH_FAKE_PREFILTER=drop_all|bad_json|refuse|error
    exercise the anomaly signal and the fail-open paths."""
    mode = os.environ.get("NEUROSEARCH_FAKE_PREFILTER", "")
    if mode == "drop_all":
        return json.dumps({"decision": "drop", "reason": "simulated overconfident filter"})
    if mode == "bad_json":
        return "{not json"
    head = system[system.find("PROJECT:"):] if "PROJECT:" in system else ""
    head = head.split("\nSOURCE:", 1)[0]                                     # the brief's vocabulary, not the source's title
    words = lambda t: {w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", t.lower()) if w not in _RANK_STOP and w not in _PREFILTER_STOP}  # noqa: E731
    vocab = words(head)
    body = user.split("\n", 1)[1] if "\n" in user else user
    lines = [ln for ln in body.split("\n") if ln.strip()]
    hits_per_line = [len(vocab & words(ln)) for ln in lines]
    strong = sum(1 for h in hits_per_line if h >= 2)          # lines that clearly speak the brief's language
    weak = sum(1 for h in hits_per_line if h == 1)
    if strong == 0 and weak <= max(2, len(lines) // 40):
        return json.dumps({"decision": "drop", "reason": "different subject throughout; no passage touches the brief"})
    if strong >= max(3, len(lines) // 10):
        return json.dumps({"decision": "keep", "reason": "clearly addresses the brief's topics"})
    return json.dumps({"decision": "uncertain", "reason": "mostly unrelated but at least one passage may matter"})


DISCOVER_QUICK = {"sources": [
    {"name": "Dave Ramsey", "kind": "youtube_channel", "url": "https://www.youtube.com/@TheRamseyShow", "gist": "debt-free budgeting basics",
     "why": "The most-cited mainstream voice on getting out of debt.", "angle": "Anti-debt absolutist; dismisses credit strategies.",
     "start_with": [{"title": "The 7 Baby Steps", "url": "https://www.youtube.com/watch?v=abc123def45"}], "fit": 5, "depth": "beginner"},
    {"name": "The Money Guy Show", "kind": "youtube_channel", "url": "https://www.youtube.com/@MoneyGuyShow", "gist": "index-fund investing, CFP-led",
     "why": "More nuanced on investing than Ramsey.", "angle": "CFP-driven, pro-index-funds.", "start_with": [], "fit": 4, "depth": "intermediate"}],
    "note": "Start with the practitioner, then the contrarian."}
DISCOVER_VERIFY = {"fixes": [{"name": "Dave Ramsey", "url": "https://www.youtube.com/@TheRamseyShow", "start_with": [{"title": "Baby Steps", "url": "https://www.youtube.com/watch?v=zzz"}]}],
                   "added": [{"name": "BiggerPockets", "kind": "podcast", "url": "https://www.biggerpockets.com/podcasts", "gist": "real estate investing", "why": "The largest REI community podcast.", "angle": "pro-leverage", "fit": 4, "depth": "beginner"}],
                   "note": "verified"}


# ---- Planner V3 canned components (Mission F4). Ids are consistent across components; evidence lists are filled with
# real ids from the material by _with_evidence, like the V1 plan. Themed on the golden brief so assembly has real refs.
SITUATION_V3 = {
    "situation": "You want to buy a main-street business with an SBA 7(a) loan within a year and have researched financing, valuation and diligence.",
    "swot": {"strengths": [{"point": "Clear brief and a 12-month decision window", "so_what": "You can run a real search, not a hobby", "evidence": []}],
             "weaknesses": [{"point": "No deal experience yet", "so_what": "Lean on a lender and a QoE provider early", "evidence": []}],
             "opportunities": [{"point": "SBA 7(a) finances 90% with a seller note on standby", "so_what": "A $1M deal needs ~$50-100k of your cash", "evidence": []},
                               {"point": "Off-market owners near retirement", "so_what": "Outreach beats brokers for price", "evidence": []}],
             "threats": [{"point": "Customer concentration above 20% of revenue", "so_what": "Price it in or walk", "evidence": []},
                         {"point": "Inflated add-backs in the seller's numbers", "so_what": "A quality of earnings report is not optional", "evidence": []}]},
    "readiness": [{"area": "money", "level": "partly", "note": "cash for a 10% equity injection to confirm"}, {"area": "skills", "level": "partly", "note": "no operating experience"},
                  {"area": "network", "level": "gap", "note": "no lender or broker relationships yet"}],
    "options": [{"id": "option:sba-7a-acquisition", "path": "SBA 7(a) acquisition with a standby seller note", "summary": "10% equity injection, 10-year term, DSCR 1.25",
                 "cost": "$50-100k cash on a $1M deal", "time_to_result": "6-12 months", "risk": "medium", "fit": 5, "why_fit": "matches the brief and the sources", "evidence": []},
                {"id": "option:seller-financed-zero-down", "path": "Zero down with full seller financing", "summary": "the podcast's path", "cost": "$0 cash",
                 "time_to_result": "12+ months", "risk": "high", "fit": 2, "why_fit": "contradicts the 10% injection rule; rare in practice", "evidence": []}],
    "recommended_option": "option:sba-7a-acquisition",
    "assumptions": [{"id": "assumption:dscr-floor", "assumption": "Lenders want DSCR of at least 1.25", "if_wrong": "less debt, more cash", "how_to_check": "ask two SBA lenders for their DSCR floor"},
                    {"id": "assumption:sde-multiple-range", "assumption": "Small businesses trade at 2.0x-3.5x SDE", "if_wrong": "budget shifts", "how_to_check": "pull three comparable listings and check the multiple"}],
    "failure_patterns": [{"id": "failure:overpaying-on-addbacks", "pattern": "Paying a multiple on inflated add-backs", "seen_in": "yt02", "avoid": "quality of earnings before the LOI expires", "evidence": []},
                         {"id": "failure:customer-concentration", "pattern": "One customer over 20% of revenue walks after closing", "seen_in": "pod", "avoid": "price the risk in or walk", "evidence": []}],
    "verdict": "Proceed with the SBA path; the first 90 days of diligence decide everything."}
CORE_V3 = {
    "goal": {"outcome": "Buy a main-street business with an SBA 7(a) loan within 12 months", "constraints": ["10% equity injection", "DSCR at least 1.25"], "success": ["closed deal", "no surprises in the first 90 days"], "evidence": []},
    "approach": {"recommended": "SBA 7(a) acquisition with a seller note on full standby", "why": "The sources agree: 10% down, half of it can be a standby seller note, 10-year term.",
                 "option": "option:sba-7a-acquisition", "alternatives": [{"option": "Zero down with full seller financing", "why_not": "contradicts the 10% equity injection rule; rare"}],
                 "basis": "research", "confidence": "high", "evidence": []},
    "decisions": [{"id": "decision:target-industry", "decision": "HVAC, services or light manufacturing?", "options": ["HVAC", "services", "light manufacturing"], "recommended": "HVAC", "why": "most listings, recurring revenue", "when": "now", "basis": "planner", "evidence": []},
                  {"id": "decision:qoe-provider", "decision": "Which quality of earnings provider?", "options": ["boutique", "regional CPA"], "recommended": "boutique", "why": "$8-20k, faster", "when": "later", "basis": "research", "evidence": []}],
    "confidence": [{"area": "financing", "level": "high", "note": "rules are well documented"}, {"area": "valuation", "level": "medium", "note": "depends on the industry"}]}
EXECUTION_V3 = {
    "phases": [{"id": "phase:financing", "name": "Financing readiness", "objective": "Know exactly what you can borrow",
                "tasks": [{"id": "task:get-lender-prequalification", "task": "Get pre-qualified by two SBA lenders", "detail": "Ask for their DSCR floor and equity injection rules", "depends_on": [], "evidence": []},
                          {"id": "task:confirm-cash-for-injection", "task": "Confirm cash available for the 10% equity injection", "detail": "Half may be a standby seller note", "depends_on": [], "evidence": []}],
                "dependencies": ["personal financial statement"], "decisions": ["decision:target-industry"], "outcome": "a pre-qualification letter"},
               {"id": "phase:search", "name": "Search and LOI", "objective": "Find a business and lock exclusivity",
                "tasks": [{"id": "task:build-deal-flow", "task": "Build deal flow from brokers and off-market outreach", "detail": "", "depends_on": ["task:get-lender-prequalification"], "evidence": []},
                          {"id": "task:sign-loi-with-exclusivity", "task": "Sign an LOI with a sixty-day exclusivity period", "detail": "Working capital peg and seller transition in the LOI", "depends_on": ["task:build-deal-flow"], "evidence": []}],
                "dependencies": [], "decisions": [], "outcome": "a signed LOI"},
               {"id": "phase:diligence", "name": "Diligence and closing", "objective": "Verify the numbers and close",
                "tasks": [{"id": "task:order-quality-of-earnings", "task": "Order a quality of earnings report", "detail": "Check add-backs and customer concentration", "depends_on": ["task:sign-loi-with-exclusivity"], "evidence": []},
                          {"id": "task:closing-day-checklist", "task": "Run the closing day checklist", "detail": "Bank signers, payroll, merchant accounts, insurance; do not raise prices in the first 90 days", "depends_on": ["task:order-quality-of-earnings"], "evidence": []}],
                "dependencies": [], "decisions": ["decision:qoe-provider"], "outcome": "keys in hand"}],
    "dependencies": [{"id": "dependency:equity-injection", "item": "Cash for the 10% equity injection", "blocking": True, "note": "half may be a standby seller note", "phase": "phase:financing"},
                     {"id": "dependency:personal-guarantee", "item": "Every 20%+ owner signs a personal guarantee", "blocking": True, "note": "", "phase": "phase:diligence"}],
    "defer": [{"item": "Raising prices", "until": "after the first 90 days"}]}
ECONOMICS_V3 = {
    "costs": {"upfront": [{"item": "Equity injection", "amount": "$50-100k", "phase": "phase:financing"}, {"item": "SBA guarantee fee", "amount": "2-3.5% of the guaranteed portion", "phase": "phase:diligence"}],
              "recurring": [{"item": "Loan payment", "amount": "estimate", "phase": ""}], "optional": [], "services": [{"item": "Quality of earnings report", "amount": "$8-20k", "phase": "phase:diligence"}],
              "contingency": "10% of upfront", "minimum": "$60k", "recommended": "$100k", "premium": "$150k", "note": "ranges are estimates", "evidence": []},
    "tools": [{"id": "tool:deal-tracker", "need": "track listings", "tool": "spreadsheet", "free_option": "Google Sheets", "premium_option": "DealRoom", "cost": "$0", "why": "enough", "tier": "required", "basis": "planner", "evidence": [], "phase": "phase:search"}],
    "risks": [{"id": "risk:customer-concentration", "risk": "One customer over 20% of revenue", "mitigation": "Price it in or walk, checked in the QoE", "priority": "high", "related": ["task:order-quality-of-earnings"], "evidence": []},
              {"id": "risk:inflated-add-backs", "risk": "Add-backs that are not legitimate", "mitigation": "Quality of earnings before exclusivity ends", "priority": "high", "related": ["task:order-quality-of-earnings"], "evidence": []},
              {"id": "risk:seller-transition", "risk": "Seller leaves too early", "mitigation": "Transition period in the LOI", "priority": "medium", "related": ["task:sign-loi-with-exclusivity"], "evidence": []}],
    "gotchas": [{"id": "gotcha:lease-assignment", "gotcha": "The lease may not be assignable", "avoid": "Get landlord consent before closing"},
                {"id": "gotcha:personal-guarantee", "gotcha": "The personal guarantee covers the whole loan", "avoid": "Know it before you sign the LOI"}]}
ACTIONS_V3 = {
    "first_steps": [{"id": "step:call-lenders", "action": "Call two SBA lenders and ask for their DSCR floor", "detail": "", "today": True, "task": "task:get-lender-prequalification", "evidence": []},
                    {"id": "step:count-cash", "action": "Write down the cash you can bring", "detail": "savings, liquid assets, a possible standby seller note", "today": True, "task": "task:confirm-cash-for-injection", "evidence": []},
                    {"id": "step:list-brokers", "action": "List five brokers and ten off-market owners to contact", "detail": "", "today": False, "task": "task:build-deal-flow", "evidence": []}],
    "this_week": [{"id": "week:lenders", "action": "Call two SBA lenders", "why": "financing gates everything", "time": "1h", "task": "task:get-lender-prequalification"},
                  {"id": "week:cash", "action": "Total your available cash", "why": "sets the deal size", "time": "30 min", "task": "task:confirm-cash-for-injection"},
                  {"id": "week:brokers", "action": "Email five brokers", "why": "start deal flow", "time": "1h", "task": "task:build-deal-flow"}],
    "open_questions": [{"id": "question:working-capital-peg", "question": "How is the working capital peg set in this industry?", "category": "soon", "why": "it moves the price", "research_prompt": "How do buyers set a working capital peg for an HVAC acquisition?"},
                       {"id": "question:multiples-above-4x", "question": "Do home services really trade above 4x SDE?", "category": "soon", "why": "the podcast contradicts the article's 2.0-3.5x", "research_prompt": "What SDE multiples do HVAC businesses sell for?"}],
    "refine_questions": [{"id": "refine:cash", "question": "How much cash can you bring?", "why": "sets the deal size", "kind": "fact", "options": []},
                         {"id": "refine:industry", "question": "HVAC, services or light manufacturing?", "why": "changes the search", "kind": "decision", "options": ["HVAC", "services", "light manufacturing"]},
                         {"id": "refine:hours", "question": "Hours per week you can give the search?", "why": "sets the timeline", "kind": "fact", "options": []},
                         {"id": "refine:location", "question": "Which metro?", "why": "deal flow differs", "kind": "preference", "options": []}],
    "ready": {"first_three": ["task:get-lender-prequalification", "task:confirm-cash-for-injection", "task:build-deal-flow"], "initial_cost": "$0 this week", "need_before": ["pre-qualification letter"], "blockers": []}}
PLANNER_V3 = {"planner.situation": SITUATION_V3, "planner.core": CORE_V3, "planner.execution": EXECUTION_V3, "planner.economics": ECONOMICS_V3, "planner.actions": ACTIONS_V3}


def task_of(system: str, kw: dict[str, Any]) -> str:
    """The declared task, else a guess from the system prompt (legacy)."""
    declared = (kw.get("extra_headers") or {}).get("x-neurosearch-task")
    if declared:
        return declared
    s = system
    if "checking a shortlist" in s:
        return "discover.verify"
    if "research librarian" in s:
        return "discover.quick"
    if "research analyst reading a transcript" in s:
        return "findings.extract"
    if "research triage assistant" in s:
        return "rank.relevance"
    if "Master Planner's analyst" in s:
        return "planner.analysis"
    if "Master Planner reviewing" in s:
        return "planner.update"
    if "You are Master Planner" in s:
        return "planner.build"
    if "masterplan" in s.lower():
        return "export.synthesis"
    return "answer.chat"


class _Msgs:
    def create(self, **kw: Any) -> Any:
        system, cache_hashes = _flatten(kw.get("system", ""))
        messages = kw.get("messages") or []
        user = _content_text(messages[-1]["content"]) if messages else ""
        task = task_of(system, kw)
        if task == "discover.verify":
            text = json.dumps(DISCOVER_VERIFY)
        elif task == "discover.quick":
            text = json.dumps(DISCOVER_QUICK)
        elif task == "findings.extract":
            text = _findings(system, user)
        elif task == "rank.relevance":
            text = _rank(user, system)
        elif task in PLANNER_V3:
            ids = re.findall(r"^\[([USFC]\d+)\]", system + "\n" + user, re.M)
            text = json.dumps(_with_evidence(PLANNER_V3[task], ids))
        elif task == "planner.analysis":
            ids = re.findall(r"^\[([USFC]\d+)\]", system + "\n" + user, re.M)
            text = json.dumps(_with_evidence(ANALYSIS, ids))
        elif task == "findings.prefilter":
            mode = os.environ.get("NEUROSEARCH_FAKE_PREFILTER", "")
            if mode == "refuse":
                return _Blk(stop_reason="refusal", model="fake-haiku", content=[], usage=_Blk(input_tokens=10, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
            if mode == "error":
                raise RuntimeError("simulated provider outage")
            text = _prefilter(user, system)
        elif task == "planner.update":
            text = _updates(user)
        elif task == "planner.build":
            ids = re.findall(r"^\[([USFC]\d+)\]", system + "\n" + user, re.M)
            text = "```json\n" + json.dumps(_with_evidence(PLAN, ids)) + "\n```"
        elif task == "export.synthesis":
            text = _synthesis(user)
        else:
            text = _answer(system, messages, task)
        fmt = (kw.get("output_config") or {}).get("format")
        if fmt:
            # structured output requested: the fake must conform exactly like the provider would (Tier 1 proves it).
            # NEUROSEARCH_FAKE_AI_BAD_JSON=1 breaks the JSON on purpose to exercise the observable fallback path.
            if os.environ.get("NEUROSEARCH_FAKE_AI_BAD_JSON") == "1":
                text = "```json\n" + text + "\n```"          # fenced: not what a structured request returns; recoverable only via the compat hatch
            else:
                import jsonschema
                try:
                    jsonschema.Draft202012Validator(fmt["schema"]).validate(json.loads(text))
                except (ValueError, jsonschema.ValidationError) as e:
                    raise AssertionError(f"fake {task} output does not conform to the requested schema: {e}") from e
        # token accounting, including a simulated prompt cache with the provider's semantics (see _simulate_cache)
        all_in = system + "\n".join(_content_text(m.get("content")) for m in messages)
        total = _tokens(all_in) + _tool_tokens(kw.get("tools"))
        cache_read, cache_write = _simulate_cache(kw.get("tools"), kw.get("system", ""), messages)
        plain = max(0, total - cache_read - cache_write)
        CACHE_LOG.append({"task": task, "total": total, "read": cache_read, "write": cache_write, "plain": plain,
                          "system_blocks": [(_tokens(b.get("text", "")), bool(b.get("cache_control"))) for b in (kw.get("system") if isinstance(kw.get("system"), list) else []) if isinstance(b, dict)]})
        content = [_Blk(type="text", text=text, citations=None)]
        if os.environ.get("NEUROSEARCH_FAKE_AI_THINKING") == "1" or (kw.get("thinking") or {}).get("type") == "adaptive":
            content.insert(0, _Blk(type="thinking", thinking="(private reasoning) " + text[:40], signature="sig_" + hashlib.sha1(text.encode()).hexdigest()[:12]))
        return _Blk(stop_reason="end_turn", model="fake-claude", content=content,
                    usage=_Blk(input_tokens=plain, output_tokens=_tokens(text), cache_read_input_tokens=cache_read,
                               cache_creation_input_tokens=cache_write, server_tool_use=None))

    def stream(self, **kw: Any) -> "_Stream":
        return _Stream(self.create(**kw))

    def count_tokens(self, **kw: Any) -> Any:
        """Stand-in for the token-counting endpoint. Claude 5 family counts 30% more than Claude 4 so the eval's
        tokenizer-delta path is exercised under Tier 1; the real delta only ever comes from the live endpoint."""
        from .contracts import model_family
        system, _ = _flatten(kw.get("system", ""))
        n = _tokens(system + "\n".join(_content_text(m.get("content")) for m in (kw.get("messages") or [])))
        if model_family(str(kw.get("model") or "")) == "claude-5":
            n = int(n * 1.3)
        return _Blk(input_tokens=n)


class _Stream:
    def __init__(self, msg: Any) -> None:
        self._msg = msg
        self.text_stream = iter([b.text for b in msg.content if getattr(b, "type", "") == "text"])

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *a: Any) -> bool:
        return False

    def get_final_message(self) -> Any:
        return self._msg


class Anthropic:
    def __init__(self, **kw: Any) -> None:
        from .fake_batches import FakeBatches
        self.messages = _Msgs()
        self.messages.batches = FakeBatches(_Msgs())


# ------------------------------------------------------------------ OpenAI

DIM = 512


def fake_embedding(text: str) -> np.ndarray:
    """Hashed bag of words + bigrams. Deterministic, lexical, good enough for retrieval tests."""
    v = np.zeros(DIM, dtype=np.float32)
    ws = _words(text)
    for i, w in enumerate(ws):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
        if i + 1 < len(ws):
            h2 = int(hashlib.md5((w + " " + ws[i + 1]).encode()).hexdigest(), 16)
            v[h2 % DIM] += 0.5 if (h2 >> 9) & 1 else -0.5
    n = float(np.linalg.norm(v))
    return v / n if n else v


class _Embeddings:
    def create(self, model: str, input: list[str]) -> Any:  # noqa: A002
        data = [_Blk(index=i, embedding=fake_embedding(t).tolist()) for i, t in enumerate(input)]
        return _Blk(data=data, usage=_Blk(total_tokens=sum(_tokens(t) for t in input)))


class _Transcriptions:
    def create(self, **kw: Any) -> Any:
        """A sidecar `<file>.segments.json` next to the audio is used when present; otherwise a stub."""
        fh = kw.get("file")
        name = getattr(fh, "name", "")
        segs = []
        try:
            side = pathlib.Path(name).with_suffix(".segments.json")
            if side.exists():
                segs = json.loads(side.read_text())
        except Exception:  # noqa: BLE001
            segs = []
        if not segs:
            segs = [{"start": 0, "end": 5, "text": "fake transcript of " + (pathlib.Path(name).name if name else "audio")}]
        return _Blk(language="en", duration=float(segs[-1]["end"]), segments=[_Blk(**s) for s in segs])


class OpenAI:
    def __init__(self, **kw: Any) -> None:
        self.embeddings = _Embeddings()
        self.audio = _Blk(transcriptions=_Transcriptions())

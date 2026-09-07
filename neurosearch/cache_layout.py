"""Rung G (second portion) — prompt-cache layout measurement (`neurosearch eval --cache-layout`).

Runs the repeated Anthropic workloads the way the product actually repeats them — a multi-turn project chat in which
the project state changes mid-conversation (a finding pinned, a fact recorded), findings extraction over every golden
source, the two planner passes — under the fake with its provider-faithful cache simulation (`fake_ai._simulate_cache`:
tools → system blocks → message blocks; exact-prefix hits; ≥1024-token minimum; read + write + plain == total), and
reports per task and per request what was read from cache, written to cache, or sent plain, plus the block layout of
every chat request (stable vs volatile). Free, deterministic, changes nothing.

`request_content(task, system, messages)` is the deterministic content signature used by the equivalence gate: the
multiset of non-empty lines of everything the model sees (tools, system blocks, messages). Reordering blocks must keep
it identical — no information may appear or disappear.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from . import db

CHAT_TURNS = [
    "What is the minimum down payment?",
    "How are seller notes usually structured?",
    "What did the sources say about SBA loans?",
    "Which of these financing options carries the least personal risk?",
]
CHAT_TURNS_2 = [                    # a later conversation, different questions: only the stable project prefix can be reused
    "How long does due diligence usually take?",
    "What are the warning signs in the financial statements?",
    "Should I hire a broker or go direct?",
]


def request_content(tools: Any, system: Any, messages: list[dict[str, Any]]) -> Counter:
    """Multiset of non-empty lines across tools (as JSON), system blocks and message blocks — order-free, so a layout
    change that only moves blocks leaves it unchanged, while any dropped or altered line shows up."""
    lines: list[str] = []
    if tools:
        lines.append(json.dumps(tools, sort_keys=True, default=str))
    blocks = system if isinstance(system, list) else ([{"type": "text", "text": system}] if system else [])
    for b in blocks:
        if isinstance(b, dict):
            lines.extend(b.get("text", "").split("\n"))
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            lines.extend(c.split("\n"))
        else:
            for b in c or []:
                t = (json.dumps(b.get("content"), sort_keys=True, default=str) if b.get("type") == "tool_result" else b.get("text", "")) if isinstance(b, dict) else (getattr(b, "text", "") or "")
                lines.extend(str(t).split("\n"))
    return Counter(x.strip() for x in lines if x.strip())


def content_diff(a: Counter, b: Counter) -> dict[str, list[str]]:
    return {"missing": sorted((a - b).elements())[:20], "added": sorted((b - a).elements())[:20]}


def run(progress: Any = print) -> dict[str, Any]:
    """Measure the current layout under the fake cache simulation. Requires settings.fake_ai (free)."""
    from . import evals, fake_ai, findings, planner, qa, usage
    from .config import settings
    assert settings.fake_ai, "the cache-layout measurement runs under the fakes"
    fake_ai._cache_seen.clear()
    fake_ai.CACHE_LOG.clear()
    t0 = time.time()
    g = evals.load_golden()
    pid = g["project_id"]
    rep: dict[str, Any] = {"eval": "cache-layout", "tier": "fake", "scenarios": {}}

    def measure(label: str, fn: Any) -> dict[str, Any]:
        start = len(fake_ai.CACHE_LOG)
        fn()
        entries = fake_ai.CACHE_LOG[start:]
        total = sum(e["total"] for e in entries); read = sum(e["read"] for e in entries); write = sum(e["write"] for e in entries)
        out = {"requests": len(entries), "total_input_tokens": total, "cache_read": read, "cache_write": write, "plain": total - read - write,
               "cache_read_share": round(read / total, 4) if total else 0.0, "requests_detail": entries}
        rep["scenarios"][label] = out
        progress(f"  {label:40s} {len(entries):3d} requests   input {total:>8,}   read {read:>8,} ({out['cache_read_share']:.0%})   write {write:>8,}   plain {out['plain']:>8,}")
        return out

    # 1. findings over every source (single-window sources, one multi-window source) — the project head is shared
    measure("findings (9 sources / 10 windows)", lambda: [findings.suggest_for_source(pid, sid) for sid in g["sources"].values()])
    # 2. a project chat: four turns; after turn 2 a finding is pinned and a fact recorded (project state changes mid-chat)
    conv = "cache-layout-chat"
    def chat() -> None:
        for i, q in enumerate(CHAT_TURNS):
            qa.ask(q, project_id=pid, conversation_id=conv)
            if i == 1:
                db.add_project_note(pid, "Pinned: minimum down payment is typically ten percent for SBA-backed deals.", citations=[], status="approved")
                db.add_fact(pid, "constraint", "Budget for the purchase: under one million dollars.")
    chat_res = measure("project chat (4 turns, state changes)", chat)
    # 3. a NEW conversation with different questions (a later session the same day): only the stable prefix can be reused
    measure("project chat (new conversation, 3 turns)", lambda: [qa.ask(q, project_id=pid, conversation_id="cache-layout-chat-2") for q in CHAT_TURNS_2])
    # 3b. the same new-conversation turns with the conversation-tail breakpoint ON (the pre-0.20.0+g5 default, kept as an
    #     override for tool-heavy workloads): shows the write premium the default now avoids
    import os
    os.environ["NEUROSEARCH_CHAT_TAIL_BREAKPOINT"] = "1"
    try:
        measure("project chat (new conv, tail breakpoint ON)", lambda: [qa.ask(q, project_id=pid, conversation_id="cache-layout-chat-3") for q in CHAT_TURNS_2])
    finally:
        os.environ.pop("NEUROSEARCH_CHAT_TAIL_BREAKPOINT", None)
    # 4. planner: two passes over the shared research material
    measure("planner (analysis + build)", lambda: planner.build_plan(pid))
    core = {k: v for k, v in rep["scenarios"].items() if "tail breakpoint ON" not in k}   # totals = the production layout; the variant is reported beside it
    tot = {k: sum(s[k] for s in core.values()) for k in ("requests", "total_input_tokens", "cache_read", "cache_write", "plain")}
    tot["cache_read_share"] = round(tot["cache_read"] / max(1, tot["total_input_tokens"]), 4)
    rep["totals"] = tot
    # billed-token view: what the provider would charge (cache write 1.25×, cache read 0.1×) relative to sending it all plain
    billed = tot["plain"] + tot["cache_write"] * usage.CACHE_WRITE_MULT + tot["cache_read"] * usage.CACHE_READ_MULT
    rep["input_cost_index"] = round(billed / max(1, tot["total_input_tokens"]), 4)      # 1.0 = every token at full price
    for k, sc in rep["scenarios"].items():
        b = sc["plain"] + sc["cache_write"] * usage.CACHE_WRITE_MULT + sc["cache_read"] * usage.CACHE_READ_MULT
        sc["input_cost_index"] = round(b / max(1, sc["total_input_tokens"]), 4)
    rep["chat_layout"] = [{"turn": i + 1, "system_blocks": e["system_blocks"], "total": e["total"], "read": e["read"], "write": e["write"]}
                          for i, e in enumerate([x for x in chat_res["requests_detail"] if x["task"] == "answer.chat"])]
    rep["seconds"] = round(time.time() - t0, 1)
    rep["text"] = format_report(rep)
    return rep


def format_report(rep: dict[str, Any]) -> str:
    t = rep["totals"]
    lines = [f"Cache layout ({rep['tier']}) · {rep['seconds']}s",
             f"  {'scenario':40s} {'req':>4s}   {'input':>9s}   {'read':>9s}          {'write':>9s}   {'plain':>9s}"]
    for k, s in rep["scenarios"].items():
        lines.append(f"  {k:40s} {s['requests']:4d}   {s['total_input_tokens']:9,}   {s['cache_read']:9,} ({s['cache_read_share']:4.0%})   {s['cache_write']:9,}   {s['plain']:9,}   cost index {s['input_cost_index']:.3f}")
    lines.append(f"  {'TOTAL':40s} {t['requests']:4d}   {t['total_input_tokens']:9,}   {t['cache_read']:9,} ({t['cache_read_share']:4.0%})   {t['cache_write']:9,}   {t['plain']:9,}")
    lines.append(f"  input cost index {rep['input_cost_index']:.3f} (1.000 = every input token at full price; cache write 1.25×, cache read 0.1×)")
    lines.append("  chat request layout (system blocks as (tokens, breakpoint)):")
    for c in rep["chat_layout"]:
        lines.append(f"    turn {c['turn']}: {c['system_blocks']}  total {c['total']:,}  read {c['read']:,}  write {c['write']:,}")
    return "\n".join(lines)

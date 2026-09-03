"""A stand-in for anthropic.Anthropic used by tests and UI demos (no API calls)."""
import json

PLAN = {
    "goal": {"outcome": "Move the marketing site off Squarespace to a faster, cheaper host without breaking email.",
             "constraints": ["budget under $500", "live by end of October"], "success": ["site loads < 1s", "no email downtime"], "evidence": ["U1"]},
    "approach": {"recommended": "Static export + Cloudflare Pages", "why": "Cheapest recurring cost and the sources agree it handles small sites well.",
                 "alternatives": [{"option": "Webflow", "why_not": "recurring cost exceeds the budget"}], "basis": "research", "confidence": "medium", "evidence": ["S1", "F1"]},
    "first_steps": [{"action": "Export the existing Squarespace site", "detail": "Save a complete local backup before touching DNS.", "today": True, "evidence": ["C1"]},
                    {"action": "Document current DNS records", "detail": "Screenshot every record, especially MX.", "today": True}],
    "phases": [{"name": "Preparation", "objective": "Backups and inventory", "tasks": [{"task": "Export site", "detail": ""}, {"task": "List all pages and redirects"}],
                "dependencies": ["Squarespace admin access"], "decisions": [], "outcome": "Nothing can be lost"}],
    "dependencies": [{"item": "Registrar login", "blocking": True, "note": "Needed before DNS changes"}, {"item": "Analytics choice", "blocking": False}],
    "decisions": [{"decision": "Which host", "options": ["Cloudflare Pages", "Netlify"], "recommended": "Cloudflare Pages", "why": "free tier suffices",
                   "when": "now", "by_phase": "Phase 2", "basis": "research", "evidence": ["S1"]}],
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
}
UPDATES = [{"section": "Recommended approach", "previous": "Static export + Cloudflare Pages", "proposed": "Static export + Netlify",
            "reason": "New finding says Cloudflare form handling is limited."}]


class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Msgs:
    def create(self, **kw):
        system = kw.get("system", "")
        if "research librarian" in system:
            text = json.dumps({"note": "Start with the practitioner, then the contrarian.", "sources": [
                {"name": "Dave Ramsey", "kind": "youtube_channel", "url": "https://www.youtube.com/@TheRamseyShow", "gist": "debt-free budgeting basics",
                 "why": "The most-cited mainstream voice on getting out of debt.", "angle": "Anti-debt absolutist; dismisses credit strategies.",
                 "start_with": [{"title": "The 7 Baby Steps", "url": "https://www.youtube.com/watch?v=abc123def45"}], "fit": 5, "depth": "beginner"},
                {"name": "The Money Guy Show", "kind": "youtube_channel", "url": "https://www.youtube.com/@MoneyGuyShow", "gist": "index-fund investing, CFP-led",
                 "why": "More nuanced on investing than Ramsey.", "angle": "CFP-driven, pro-index-funds.", "start_with": [], "fit": 4, "depth": "intermediate"}]})
        elif "research analyst reading a transcript" in system:
            text = json.dumps({"summary": "Compares static hosts and warns about DNS.", "substance": 72, "findings": [
                {"title": "Cloudflare Pages: free static hosting", "finding": "Free tier covers a brochure site with no bandwidth bill.", "ts": "0:05", "quote": "cloudflare pages is free for static sites", "importance": 5},
                {"title": "Leave MX records alone", "finding": "Changing MX during a site move is how email breaks; only touch A/CNAME.", "ts": "3:40", "quote": "never touch MX records", "importance": 4}]})
        elif "research triage assistant" in system:
            import re as _re
            idx = [int(m) for m in _re.findall(r"^\[(\d+)\] ", kw["messages"][0]["content"], flags=_re.M)]
            text = json.dumps({"scores": [{"i": i, "score": (90 if i % 2 else 20), "why": "on topic" if i % 2 else "filler"} for i in idx]})
        elif "Master Planner reviewing" in system:
            text = json.dumps(UPDATES)
        elif "You are Master Planner" in system:
            text = "```json\n" + json.dumps(PLAN) + "\n```"
        elif "masterplan" in system.lower():
            text = "# Plan\n\nSynthesized."
        else:
            text = "Answer from the sources [1]."
        return _Blk(stop_reason="end_turn", model="claude-sonnet-4-6", usage=_Blk(input_tokens=12000, output_tokens=800, server_tool_use=None),
                    content=[_Blk(type="text", text=text, citations=None)])


class Anthropic:
    def __init__(self, **kw):
        self.messages = _Msgs()

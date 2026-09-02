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
        if "Master Planner reviewing" in system:
            text = json.dumps(UPDATES)
        elif "You are Master Planner" in system:
            text = "```json\n" + json.dumps(PLAN) + "\n```"
        elif "masterplan" in system.lower():
            text = "# Plan\n\nSynthesized."
        else:
            text = "Answer from the sources [1]."
        return _Blk(stop_reason="end_turn", content=[_Blk(type="text", text=text, citations=None)])


class Anthropic:
    def __init__(self, **kw):
        self.messages = _Msgs()

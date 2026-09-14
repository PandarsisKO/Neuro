"""Generates the frozen HARD retrieval fixture (Rung I1). Run once: `python tests/fixtures/golden/retrieval/build.py`.

The Golden Project's retrieval questions are graded per source and mostly have one obvious answer, which is why
Recall@10 sits at 100%: they hide ordering and localisation mistakes. This fixture adds distractor sources to the same
project and a query set graded per source AND per chunk locator, with hard negatives — sources that are semantically
close to the question but not responsive (or wrong). Categories:

  same_concept     several sources cover the concept; the graded primary must come first (yt01 + report + …)
  authority        the authoritative source vs a popular, weaker, partly wrong one (pop_weak)
  numeric          the exact number the question asks for, surrounded by similar numbers for other loan types (dscr_numbers)
  contradiction    sources that disagree (pod vs yt01/report; pod vs article)
  terminology      the same words in a different context (startup_wc: 'working capital' as runway; hvac_ops: 'standby' generators, 'note' as service notes)
  buried           evidence deep inside the 92-minute walkthrough (yt03), graded at the exact locator
  ordering         the right source is in the top 10 today but not first
  locator          exact chunk grading (±120 s for media, exact page for documents)

Deterministic, synthetic, no real people. Files are committed; re-run only to change the corpus (bump "version").
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20260908)


def segs(lines: list[str], start: float = 0.0) -> list[dict]:
    out, t = [], start
    for ln in lines:
        d = max(2.0, min(12.0, len(ln.split()) / 2.6))
        out.append({"start": round(t, 1), "end": round(t + d, 1), "text": ln})
        t += d
    return out


FILLER = [
    "Quick reminder to like the video if this is useful, it genuinely helps.",
    "Okay let me grab my notes, one second.",
    "I get asked this constantly so here's my take.",
    "Anyway, back to the point.",
    "Drop a comment if you want the deep dive on that.",
]


def with_filler(core: list[str], every: int = 3) -> list[str]:
    out = []
    for i, ln in enumerate(core):
        out.append(ln)
        if i % every == every - 1:
            out.append(rng.choice(FILLER))
    return out


# --- authority vs popular: a hype channel that is vague and partly wrong on the same questions as yt01/report
POP_WEAK = with_filler([
    "Guys, buying a business is the ultimate cheat code and today I'm giving you the no-fluff version.",
    "Down payment: honestly people overthink this, I've seen buyers get in with basically five percent down if they know the right lender, sometimes less.",
    "The bank wants some skin in the game but it's negotiable, everything is negotiable, that's the mindset.",
    "Seller notes are magic, get the seller to carry as much as possible and your down payment basically disappears.",
    "Standby, non standby, whatever, the lawyers sort that out, don't get stuck on the jargon.",
    "Personal guarantee? Sure, you sign some paperwork, but nobody ever actually comes after you, that's a myth.",
    "Loan terms are like ten years-ish, could be more, depends on the vibe with the lender.",
    "The guarantee fee is small, like a percent, don't even factor it in.",
    "Closing can be done in thirty days if you push, I've seen it happen.",
    "Multiples: anything under five x is a steal in this market, trust me, I talk to brokers every day.",
    "Due diligence is mostly a formality if the business has good reviews and the owner seems honest.",
    "Quality of earnings reports are for big deals, for small deals just look at the bank statements yourself.",
    "The first ninety days are about making your mark: rebrand, raise prices, show the staff who's boss.",
], every=3)

# --- numeric: the exact number the question wants, surrounded by similar numbers for other products
DSCR_NUMBERS = with_filler([
    "Today I want to go through every coverage ratio a lender will quote you, because they all sound the same and they are not.",
    "For a plain commercial real estate loan, most banks want a debt service coverage ratio of one point two zero.",
    "For an owner-occupied real estate deal on a 504 structure, you'll often see one point one five accepted.",
    "For a business acquisition on a 7a loan, the coverage ratio lenders want is one point two five, and some go to one point three.",
    "For a startup or a franchise with no history, expect them to underwrite to one point three five or higher.",
    "For equipment financing, coverage is usually one point one zero because the collateral is the equipment itself.",
    "So if someone quotes you one point five, ask which product they're talking about, because that's a different loan.",
    "The ratio is cash flow available for debt service divided by the annual loan payment, and lenders calculate cash flow their way, not yours.",
    "Loan-to-value on the real estate piece is typically eighty percent for owner-occupied and seventy percent for investment property.",
    "Global cash flow adds your personal income and debts to the business numbers, and it's where a lot of buyers fall short.",
    "The guarantee fee on the 7a piece is between two and three and three quarters percent depending on the loan size.",
    "Interest rates are prime plus a spread, and the spread on acquisition deals right now is two and a half to three.",
], every=3)

# --- terminology: 'working capital' as startup runway, 'burn', 'peg' never in the acquisition sense
STARTUP_WC = with_filler([
    "Let's talk working capital for a seed stage startup, which is a totally different animal from a small business loan.",
    "Working capital for us is runway: how many months of burn we have in the bank before we need to raise again.",
    "The rule of thumb is to raise eighteen to twenty four months of working capital so you're never fundraising from a position of weakness.",
    "Investors will peg your valuation to your growth rate, not to earnings, because there are no earnings.",
    "Accounts receivable barely exist for a SaaS startup; customers pay monthly by card, so the working capital cycle is short.",
    "Inventory is zero, payables are mostly cloud bills, and the whole balance sheet is cash and deferred revenue.",
    "A working capital line from a bank is basically impossible pre-revenue, so venture debt is the only debt on the table.",
    "Founders should negotiate the option pool before the price, because the pool comes out of your side of the cap table.",
    "Due diligence from a VC is about the team and the market, not about tax returns and bank statements.",
    "The transition after a raise is about hiring, not about a seller handing over keys.",
], every=3)

# --- terminology: 'standby' generators, 'notes' as service notes, 'seller' as parts seller — an HVAC operations video
HVAC_OPS = with_filler([
    "This one's for HVAC business owners: how we run service calls so techs stop leaving money on the table.",
    "Every truck carries a standby generator for storm season, and standby units are a huge upsell for customers with medical equipment.",
    "Our techs write service notes on every ticket: what they found, what they recommended, what the customer declined.",
    "The parts seller we use delivers twice a day, and the seller gives net thirty terms if you keep the account current.",
    "Maintenance agreements are the business: a customer on a plan is worth three times a one-off repair customer.",
    "Pricing is flat rate from the book, not time and materials, so the customer knows the price before the work starts.",
    "Dispatch by zone, not by first come first served, and your drive time drops by a third.",
    "In the first ninety days of a new hire, ride along with them every week and check their notes.",
    "The down payment on a new install is fifty percent at signing and the balance at startup, and startup means when the unit runs.",
    "Equity in the company goes to techs who stay five years, that's our retention plan.",
], every=3)


def build() -> None:
    files = {
        "pop_weak.json": POP_WEAK,
        "dscr_numbers.json": DSCR_NUMBERS,
        "startup_wc.json": STARTUP_WC,
        "hvac_ops.json": HVAC_OPS,
    }
    for name, lines in files.items():
        s = segs(lines)
        (HERE / name).write_text(json.dumps({"segments": s, "duration": s[-1]["end"]}, indent=1))
    sources = [
        {"id": "pop_weak", "file": "pop_weak.json", "platform": "youtube", "external_id": "retr000001", "url": "https://www.youtube.com/watch?v=retr000001",
         "title": "Buy a business with (almost) no money down — the cheat code", "channel": "Hustle Capital", "published_at": "2025-08-01"},
        {"id": "dscr_numbers", "file": "dscr_numbers.json", "platform": "youtube", "external_id": "retr000002", "url": "https://www.youtube.com/watch?v=retr000002",
         "title": "Every lender ratio explained: DSCR, LTV, global cash flow", "channel": "Bank Talk", "published_at": "2025-07-10"},
        {"id": "startup_wc", "file": "startup_wc.json", "platform": "youtube", "external_id": "retr000003", "url": "https://www.youtube.com/watch?v=retr000003",
         "title": "Working capital and runway for seed-stage startups", "channel": "Founder Office Hours", "published_at": "2025-06-15"},
        {"id": "hvac_ops", "file": "hvac_ops.json", "platform": "youtube", "external_id": "retr000004", "url": "https://www.youtube.com/watch?v=retr000004",
         "title": "Running an HVAC service business: dispatch, notes, standby units", "channel": "Trade Owner", "published_at": "2025-05-20"},
    ]
    # locators: seconds of the segment that answers, found by phrase at build time
    def at(name: str, phrase: str) -> float:
        for s in json.loads((HERE / name).read_text())["segments"]:
            if phrase.lower() in s["text"].lower():
                return s["start"]
        raise SystemExit(f"phrase not found in {name}: {phrase}")
    golden_at = {}
    for name, key in (("yt01_sba_basics.json", "yt01"), ("yt02_due_diligence.json", "yt02"), ("yt03_deal_walkthrough_long.json", "yt03"), ("podcast_contrarian.json", "pod")):
        golden_at[key] = json.loads((HERE.parent / name).read_text())["segments"]
    def gat(key: str, phrase: str) -> float:
        for s in golden_at[key]:
            if phrase.lower() in s["text"].lower():
                return s["start"]
        raise SystemExit(f"phrase not found in {key}: {phrase}")

    Q = []
    def q(text: str, category: str, expected: list, hard_negatives: list | None = None, note: str = "") -> None:
        Q.append({"q": text, "category": category, "expected": expected, "hard_negatives": hard_negatives or [], "note": note})
    # authority vs popular
    q("What is the minimum down payment for an SBA 7(a) acquisition?", "authority", [{"source": "yt01", "at": gat("yt01", "minimum ten percent equity injection")}, {"source": "report", "at": 1}], ["pop_weak"], "pop_weak says 'five percent' — wrong and vague")
    q("Can the seller note count toward the equity injection?", "authority", [{"source": "yt01", "at": gat("yt01", "half of that ten percent can come from a seller note")}, {"source": "report", "at": 2}], ["pop_weak"])
    q("Do I really have to sign a personal guarantee?", "authority", [{"source": "yt01", "at": gat("yt01", "unlimited personal guarantee")}, {"source": "report", "at": 3}], ["pop_weak"], "pop_weak calls it a myth")
    q("Is a quality of earnings report necessary on a small deal?", "authority", [{"source": "yt02", "at": gat("yt02", "quality of earnings report costs")}, {"source": "pod"}], ["pop_weak"])
    q("What should I change in the first ninety days after buying a business?", "authority", [{"source": "yt03", "at": gat("yt03", "Do not raise prices in the first ninety days")}], ["pop_weak", "hvac_ops"], "pop_weak says rebrand and raise prices; hvac_ops has 'first ninety days' for new hires")
    # numeric: the exact number among similar numbers
    q("What debt service coverage ratio do lenders want on a business acquisition loan?", "numeric", [{"source": "yt01", "at": gat("yt01", "debt service coverage ratio of at least one point two five")}, {"source": "dscr_numbers", "at": at("dscr_numbers.json", "business acquisition on a 7a loan")}], [], "dscr_numbers has 1.20 / 1.15 / 1.35 / 1.10 / 1.5 for OTHER products in neighbouring chunks")
    q("What DSCR applies to an owner-occupied 504 real estate deal?", "numeric", [{"source": "dscr_numbers", "at": at("dscr_numbers.json", "owner-occupied real estate deal on a 504")}], ["yt01"], "yt01's 1.25 is the acquisition figure, not the answer")
    q("How much is the SBA guarantee fee?", "numeric", [{"source": "yt01", "at": gat("yt01", "guarantee fee is two to three and three quarters percent")}, {"source": "dscr_numbers", "at": at("dscr_numbers.json", "guarantee fee on the 7a piece")}, {"source": "report"}], ["pop_weak"], "pop_weak: 'like a percent'")
    q("What loan-to-value do banks allow on owner-occupied real estate?", "numeric", [{"source": "dscr_numbers", "at": at("dscr_numbers.json", "Loan-to-value on the real estate piece")}], [])
    # contradiction
    q("Can you buy a business with zero percent down?", "contradiction", [{"source": "pod", "at": gat("pod", "zero percent down")}, {"source": "yt01"}], ["pop_weak"], "pod is the contrarian claim; yt01/report the rule; pop_weak the hype")
    q("Do home services businesses sell for more than four times SDE?", "contradiction", [{"source": "pod"}, {"source": "article"}], ["pop_weak"], "pop_weak: 'under five x is a steal'")
    # terminology
    q("How do you set a working capital peg in a business purchase?", "terminology", [{"source": "yt02", "at": gat("yt02", "working capital peg")}, {"source": "yt03", "at": gat("yt03", "working capital peg concept")}, {"source": "article"}], ["startup_wc"], "startup_wc: working capital = runway, 'peg your valuation'")
    q("What does full standby mean for a seller note?", "terminology", [{"source": "yt01", "at": gat("yt01", "Full standby means")}, {"source": "report", "at": 2}], ["hvac_ops"], "hvac_ops: standby generators")
    q("Should the seller stay on after closing, and for how long?", "terminology", [{"source": "yt02", "at": gat("yt02", "transition period, ninety days")}, {"source": "yt03", "at": gat("yt03", "transition services agreement")}], ["hvac_ops", "startup_wc"], "hvac_ops: parts seller; startup_wc: 'transition after a raise'")
    q("How much working capital should a seed startup raise?", "terminology", [{"source": "startup_wc", "at": at("startup_wc.json", "eighteen to twenty four months")}], ["yt02", "yt03"], "the reverse: here the startup source IS the answer and the acquisition sources are the distractors")
    # buried in the long walkthrough, exact locator
    q("How long should the exclusivity period in the LOI be?", "buried", [{"source": "yt03", "at": gat("yt03", "sixty day exclusivity")}], [])
    q("What multiple of SDE do small businesses under a million in SDE trade at?", "buried", [{"source": "yt03", "at": gat("yt03", "two to three and a half times SDE")}, {"source": "article"}], ["pop_weak"])
    q("Can the building be financed on a longer term than the business?", "buried", [{"source": "yt03", "at": gat("yt03", "twenty five year 7a")}, {"source": "report"}], ["dscr_numbers"], "dscr_numbers talks real estate ratios, not terms")
    q("What has to change on closing day — bank signers, payroll, insurance?", "buried", [{"source": "yt03", "at": gat("yt03", "Change the bank signers")}], ["hvac_ops"])
    q("Where do the best off-market deals come from?", "buried", [{"source": "yt03", "at": gat("yt03", "direct outreach to owners over fifty five")}], [])
    # same concept across sources, ordering
    q("How long is the term on an SBA acquisition loan?", "same_concept", [{"source": "yt01", "at": gat("yt01", "term on a business acquisition loan is ten years")}, {"source": "report"}], ["pop_weak"], "pop_weak: 'ten years-ish, depends on the vibe'")
    q("What is the maximum 7(a) loan size?", "same_concept", [{"source": "yt01", "at": gat("yt01", "maximum 7a loan size is five million")}, {"source": "report", "at": 1}], [])
    q("When is customer concentration a deal breaker?", "same_concept", [{"source": "yt02", "at": gat("yt02", "more than twenty percent of revenue")}, {"source": "pod"}], [])
    q("What is a legitimate add-back?", "same_concept", [{"source": "yt02", "at": gat("yt02", "legitimate add-back")}], ["pop_weak"])
    q("Which leases and contracts need to be assignable?", "same_concept", [{"source": "yt02", "at": gat("yt02", "assignable")}], ["hvac_ops"])
    q("What documents will the lender ask for?", "same_concept", [{"source": "yt03", "at": gat("yt03", "three years of personal tax returns")}, {"source": "report"}], ["startup_wc"], "startup_wc: 'not about tax returns'")
    q("What interest rate spread do acquisition loans carry?", "same_concept", [{"source": "yt01", "at": gat("yt01", "prime plus two and a half")}, {"source": "dscr_numbers", "at": at("dscr_numbers.json", "spread on acquisition deals")}], [])
    q("What is global cash flow and why do buyers fail it?", "same_concept", [{"source": "dscr_numbers", "at": at("dscr_numbers.json", "Global cash flow")}], ["startup_wc"])
    q("Is closing possible in thirty days?", "authority", [{"source": "yt01", "at": gat("yt01", "Closing takes sixty to ninety days")}], ["pop_weak"], "pop_weak claims thirty days; yt01 says sixty to ninety")
    q("How should service technicians write up their notes?", "terminology", [{"source": "hvac_ops", "at": at("hvac_ops.json", "service notes on every ticket")}], ["yt01", "report"], "the reverse: 'notes' here means service notes, not seller notes")
    fixture = {"version": 1, "sources": sources, "queries": Q,
               "grading": {"media_locator_tolerance_s": 120, "hard_negative_false_positive": "a hard-negative source ranks ABOVE the first expected hit",
                           "ndcg": "binary source relevance per hit, top 10", "locator_exact": "the FIRST hit of an expected source is at its graded locator"}}
    (HERE / "retrieval.json").write_text(json.dumps(fixture, indent=1))
    print(f"{len(sources)} distractor sources, {len(Q)} graded queries, {sum(1 for x in Q for e in x['expected'] if 'at' in e)} locators, {sum(len(x['hard_negatives']) for x in Q)} hard negatives")


if __name__ == "__main__":
    build()

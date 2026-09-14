"""Generates the frozen ranking fixture (Mission E2): ~80 proposed videos with predetermined relevance grades against
the Golden Project's brief (buying a small main-street business with an SBA 7(a) loan). Run once; ranking.json is
what is frozen. Grades: 3 = squarely on the brief, 2 = relevant angle / adjacent, 1 = weakly related, 0 = irrelevant.
Categories name the trap each item sets for a ranker."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

# (category, grade, title, description, minutes, views)
ITEMS = [
    # ---- clearly relevant (3)
    ("relevant", 3, "SBA 7(a) loans for buying a business: down payment, terms, guarantees", "Everything a first-time buyer needs to know about the 10% equity injection, seller notes on standby, 10-year terms and the personal guarantee.", 24, 48000),
    ("relevant", 3, "How to do due diligence on a small business (quality of earnings, add-backs)", "A step by step diligence checklist: QoE reports, add-backs that are not legitimate, customer concentration, working capital pegs.", 31, 22000),
    ("relevant", 3, "Valuing a main street business: SDE multiples explained", "Why businesses under $1M in earnings trade at 2-3.5x SDE and what moves the multiple up or down.", 18, 35000),
    ("relevant", 3, "Full walkthrough: buying an HVAC company with an SBA loan", "From LOI to closing day on a $1.4M HVAC acquisition: financing structure, diligence findings, transition.", 52, 15000),
    ("relevant", 3, "Letter of intent for a business purchase: what to include", "Exclusivity, price basis in SDE, working capital, seller transition — the LOI terms that protect a buyer.", 16, 9000),
    ("relevant", 3, "The first 90 days after buying a business", "Don't change prices, meet every employee, keep the revenue you paid for: a post-close playbook.", 21, 12000),
    ("relevant", 3, "Seller financing vs SBA: structuring a small business acquisition", "How a seller note interacts with the SBA equity injection and when full standby is required.", 27, 8000),
    ("relevant", 3, "Customer concentration killed my deal — here's what I learned", "One customer was 45% of revenue. How to spot it, price it, or walk away.", 14, 6000),
    ("relevant", 3, "Working capital peg negotiation in an SMB deal", "How to compute a normal level of AR + inventory - AP and write it into the purchase agreement.", 19, 4100),
    ("relevant", 3, "DSCR explained: will the bank fund your acquisition?", "Debt service coverage of 1.25 and what lenders actually compute from the tax returns.", 12, 7700),
    ("relevant", 3, "Buying a landscaping business: numbers from a real 2025 deal", "Purchase price, SDE, multiple, SBA terms and the surprises in diligence.", 38, 19000),
    ("relevant", 3, "What the SBA lender will ask you for (document checklist)", "Personal financial statement, three years of returns, business plan, resume — and why they matter.", 11, 5200),
    ("relevant", 3, "Searching for a business to buy: brokers, BizBuySell, direct outreach", "Where deals actually come from and how to write a one-page buyer profile.", 22, 14000),
    ("relevant", 3, "Transition period and seller holdbacks", "Why the seller should stay 90 days and how a holdback keeps them motivated.", 13, 3800),
    ("relevant", 3, "Add-backs: the honest ones and the fantasy ones", "Owner salary, personal vehicle, one-time legal fees — which add-backs a lender will accept.", 15, 6600),
    ("relevant", 3, "Assignable leases and contracts: the diligence item everyone skips", "A non-assignable lease can kill a closing; how to check every contract before signing.", 10, 2900),
    # ---- moderately relevant / adjacent (2)
    ("moderate", 2, "How SBA loans work (all programs overview)", "7(a), 504, microloans, express: what each is for and who qualifies.", 20, 91000),
    ("moderate", 2, "Franchise vs independent business: which should you buy?", "Costs, control and financing differences between buying a franchise unit and an independent business.", 25, 33000),
    ("moderate", 2, "Running a home services company: pricing, crews, cash flow", "Operations of an HVAC/plumbing company for a new owner.", 44, 28000),
    ("moderate", 2, "Reading a P&L and balance sheet for non-accountants", "The three statements, working capital, and what a healthy small company looks like.", 29, 120000),
    ("moderate", 2, "Business brokers: how they work and how they get paid", "Commission structures, listing agreements and what a broker will and won't tell a buyer.", 17, 8800),
    ("moderate", 2, "Search funds explained", "Raising a fund to buy one company, the ETA model and how it differs from a self-funded search.", 34, 41000),
    ("moderate", 2, "Selling your small business: how to prepare for buyers", "The seller's side: cleaning up books, documenting systems, timing the exit.", 26, 17000),
    ("moderate", 2, "Personal guarantees: what you're really signing", "How unlimited personal guarantees work on business loans and how to protect your family.", 14, 12000),
    ("moderate", 2, "Business insurance for a new owner: what to buy on day one", "General liability, workers comp, key person and what changes at closing.", 16, 5100),
    ("moderate", 2, "Negotiation tactics for buying a company from a retiring owner", "Emotional sellers, price anchoring and keeping the deal alive.", 23, 15500),
    ("moderate", 2, "Rollover of equity and earnouts in small deals", "When an earnout bridges a valuation gap and how to structure it fairly.", 19, 6900),
    ("moderate", 2, "Hiring a CPA and attorney for an acquisition", "What each professional does in a deal and typical fees.", 12, 4300),
    # ---- weakly related (1)
    ("weak", 1, "How to start an LLC in 2026", "Formation, EIN, operating agreement, bank account.", 9, 210000),
    ("weak", 1, "Should you buy a business or start one?", "A high level comparison of risk, capital and speed.", 15, 67000),
    ("weak", 1, "Real estate investing with SBA 504 loans", "Using the 504 program to buy commercial property for your company.", 21, 24000),
    ("weak", 1, "Small business taxes: S corp vs LLC", "Tax treatment and reasonable salary rules.", 18, 155000),
    ("weak", 1, "Entrepreneurship mindset: 10 lessons from founders", "Motivation and habits from people who built companies.", 27, 88000),
    ("weak", 1, "Bookkeeping basics for a small business", "Setting up QuickBooks, chart of accounts, monthly close.", 22, 73000),
    ("weak", 1, "How to get a business credit card", "Building business credit and card comparisons.", 11, 39000),
    ("weak", 1, "Commercial lease negotiation for retail tenants", "Rent, TI allowances and renewal options.", 20, 12000),
    # ---- irrelevant (0)
    ("irrelevant", 0, "Van life in Utah: solar, water and a sunrise hike", "Our off-grid setup and a five-mile red rock hike.", 14, 320000),
    ("irrelevant", 0, "Sourdough starter for beginners", "Feeding schedule, bulk fermentation and a dutch oven bake.", 12, 480000),
    ("irrelevant", 0, "Best budget mechanical keyboards 2026", "Switches, keycaps and sound tests.", 16, 210000),
    ("irrelevant", 0, "Marathon training plan: 16 weeks to your first race", "Weekly mileage, long runs and tapering.", 19, 95000),
    ("irrelevant", 0, "Home espresso: dialing in a grinder", "Grind size, dose and extraction time.", 13, 140000),
    ("irrelevant", 0, "iPhone camera tricks for travel photos", "Composition and editing on your phone.", 9, 260000),
    ("irrelevant", 0, "Learn Spanish in 30 days: my method", "Apps, immersion and daily routines.", 17, 180000),
    ("irrelevant", 0, "Building a raised garden bed", "Materials, soil mix and planting.", 11, 66000),
    # ---- misleading / clickbait (0-1): business words, no substance
    ("clickbait", 0, "I BOUGHT A BUSINESS FOR $0 (you won't believe this)", "Reaction video and giveaway announcement — subscribe for part two!", 8, 900000),
    ("clickbait", 1, "Get RICH buying businesses with NO MONEY DOWN!!!", "Secret method the banks don't want you to know. Course link below.", 6, 750000),
    ("clickbait", 0, "Millionaire reacts to small business owners (hilarious)", "Reacting to TikToks of business owners.", 15, 1200000),
    ("clickbait", 0, "This SBA loan HACK changed my life", "Motivational clip, no details, sponsored by an app.", 4, 410000),
    ("clickbait", 1, "Top 10 businesses to buy in 2026 (ranked)", "A listicle of industries with stock footage; no numbers or process.", 10, 530000),
    ("clickbait", 0, "Day in the life of a business buyer (vlog)", "Coffee, gym, a couple of broker calls, dinner.", 18, 98000),
    # ---- authoritative but low view count (3)
    ("authoritative_low_view", 3, "SBA SOP 50 10 change of ownership rules: a lender's walkthrough", "A bank's SBA department head explains equity injection, seller standby and eligibility line by line.", 47, 620),
    ("authoritative_low_view", 3, "CPA panel: quality of earnings for sub-$5M acquisitions", "Three CPAs on what a QoE covers, costs, and the red flags they see most.", 58, 410),
    ("authoritative_low_view", 3, "M&A attorney: purchase agreement clauses that protect buyers", "Reps and warranties, indemnity caps, holdbacks and working capital true-ups in main street deals.", 41, 880),
    ("authoritative_low_view", 3, "Small business valuation webinar (certified appraiser)", "How a CVA builds an SDE-based valuation and reconciles market comps.", 63, 1300),
    ("authoritative_low_view", 2, "Lender Q&A: DSCR, collateral shortfalls and projections", "Recorded office hours with an SBA preferred lender.", 39, 290),
    # ---- popular but irrelevant (0)
    ("popular_irrelevant", 0, "How I made $1M on YouTube in one year", "Monetisation, sponsorships and merch.", 24, 4300000),
    ("popular_irrelevant", 0, "Crypto is about to EXPLODE (buy now)", "Price predictions and exchange referral links.", 13, 2900000),
    ("popular_irrelevant", 0, "Dropshipping in 2026: full beginner course", "Shopify store setup and TikTok ads.", 95, 3100000),
    ("popular_irrelevant", 0, "Passive income: 7 ideas that actually work", "Dividends, rentals, courses and print on demand.", 21, 5200000),
    ("popular_irrelevant", 0, "Stock market crash incoming? What to do", "Macro commentary and portfolio moves.", 17, 1800000),
    # ---- duplicates / adjacent variants of relevant items (the ranker should prefer one)
    ("duplicate", 3, "SBA 7(a) loans for buying a business: down payment, terms, guarantees (re-upload)", "Re-uploaded with fixed audio. Everything a first-time buyer needs to know about the 10% equity injection.", 24, 3100),
    ("duplicate", 2, "SBA loan down payment: 5 minute summary", "A short clip cut from the full 7(a) explainer.", 5, 21000),
    ("duplicate", 3, "Due diligence checklist part 2: legal and contracts", "Continuation of the diligence series: leases, licenses, employee agreements.", 26, 9800),
    ("duplicate", 2, "Due diligence checklist part 1 (old version, 2022)", "The original version of the diligence video; some numbers are outdated.", 28, 30000),
    ("duplicate", 3, "SDE multiples explained — extended interview cut", "Same conversation as the valuation explainer, longer and less edited.", 41, 4400),
    # ---- more moderate/weak filler to reach ~80 with realistic noise
    ("moderate", 2, "Owner-operator vs absentee owner: which businesses work", "What you can realistically run yourself and when you need a GM.", 18, 11000),
    ("moderate", 2, "Turnaround basics: fixing a business you just bought", "Cash, pricing and people in the first year of a struggling acquisition.", 33, 7400),
    ("weak", 1, "Marketing plan for a local service business", "Google Business Profile, reviews and referral programs.", 24, 45000),
    ("weak", 1, "How to hire your first employee", "Job posts, interviews, payroll setup.", 14, 52000),
    ("weak", 1, "Cash flow forecasting in a spreadsheet", "A 13-week cash flow template walkthrough.", 20, 31000),
    ("irrelevant", 0, "Restoring a 1970s motorcycle: part 4", "Carburettor rebuild and paint.", 35, 77000),
    ("irrelevant", 0, "Weekend meal prep: 5 high protein recipes", "Batch cooking for the week.", 16, 390000),
    ("irrelevant", 0, "Chess opening traps every beginner falls for", "Five traps and how to avoid them.", 12, 610000),
    ("clickbait", 0, "Business buying EXPOSED: the truth nobody tells you", "Rant about gurus; no actionable content.", 11, 340000),
    ("moderate", 2, "Acquisition entrepreneurship podcast: buying a plumbing company", "Interview with a searcher who bought a $2M plumbing business, financing and lessons.", 71, 6200),
    ("relevant", 3, "Standby seller notes: what 'full standby' means to the SBA", "No principal, no interest until the SBA loan is repaid — and why sellers push back.", 9, 2700),
    ("relevant", 3, "Closing day checklist for a business purchase", "Wires, signatures, bank signers, merchant accounts, payroll admin, insurance — all on day one.", 12, 3600),
    ("weak", 1, "Retirement planning for small business owners", "SEP IRAs, solo 401(k)s and exit timing.", 22, 27000),
    ("moderate", 2, "How lenders underwrite a business acquisition (bank insider)", "Cash flow analysis, global cash flow, and what gets a deal declined.", 30, 9900),
]


def build() -> dict:
    items = []
    for i, (cat, grade, title, desc, mins, views) in enumerate(ITEMS):
        items.append({"id": f"rank{i:03d}", "external_id": f"rk{i:03d}0000000"[:11], "category": cat, "grade": grade, "title": title,
                      "description": desc, "duration": mins * 60, "view_count": views, "published_at": f"2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}"})
    return {"version": 1, "want": 20, "items": items}


def main() -> None:
    fx = build()
    (HERE / "ranking.json").write_text(json.dumps(fx, indent=1))
    from collections import Counter
    print(len(fx["items"]), "items", Counter(x["category"] for x in fx["items"]), Counter(x["grade"] for x in fx["items"]))


if __name__ == "__main__":
    main()

"""Generates the frozen Golden Project fixtures (Mission A1). Run once: `python tests/fixtures/golden/build.py`.

Everything is synthetic and deterministic: no network, no real people. The topic is buying a small business with
an SBA loan, chosen because it has numbers, disagreements between sources, a spreadsheet that is genuinely a
calculator, and a lot of realistic filler to hide the nuggets in. The generated files are committed so the eval never
depends on this script; re-run it only when you deliberately change the corpus (and bump manifest "version").
"""
from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20260906)

# ---------------------------------------------------------------- transcripts (timestamped segments)

def segs(lines: list[str], start: float = 0.0, secs_per_line: float = 6.0) -> list[dict]:
    out, t = [], start
    for ln in lines:
        d = max(2.0, min(12.0, len(ln.split()) / 2.6))
        out.append({"start": round(t, 1), "end": round(t + d, 1), "text": ln})
        t += d
    return out


FILLER = [
    "So before we get into it, if you're new here, hit the subscribe button, it really helps the channel.",
    "Quick shout out to today's sponsor, they do accounting software for small businesses, link in the description.",
    "Alright, let me pull up my notes here, give me one second.",
    "And I get this question all the time in the comments so I figured I'd just make a video about it.",
    "Anyway, that's a tangent, let's get back to the main topic.",
    "I'll put a link to the spreadsheet I use for this down below.",
    "Let me know in the comments if you want a deeper video on that part.",
    "Okay so where was I, right, the next thing.",
    "Honestly this is the part most people skip and then they regret it.",
    "We're going to do a live deal review next week so make sure you're subscribed for that.",
]


def with_filler(core: list[str], every: int = 3) -> list[str]:
    out = []
    for i, ln in enumerate(core):
        out.append(ln)
        if i % every == every - 1:
            out.append(rng.choice(FILLER))
    return out


YT01 = with_filler([
    "Today we're talking about how SBA 7a loans actually work when you're buying a small business.",
    "The headline number everybody asks about is the down payment, and for an acquisition the SBA requires a minimum ten percent equity injection.",
    "So on a one million dollar purchase you need to bring one hundred thousand dollars to the table.",
    "Now here's the part people miss: half of that ten percent can come from a seller note, as long as the seller note is on full standby for the life of the loan.",
    "Full standby means the seller gets no payments, not principal and not interest, until the SBA loan is paid off.",
    "The term on a business acquisition loan is ten years, and the rate is usually prime plus two and a half to three percent.",
    "Every owner with twenty percent or more of the business has to sign an unlimited personal guarantee.",
    "That personal guarantee is the thing that keeps people up at night, so understand it before you sign the letter of intent.",
    "The maximum 7a loan size is five million dollars, and above that you're looking at conventional financing or a combination.",
    "Lenders want to see a debt service coverage ratio of at least one point two five, meaning the cash flow covers the loan payment with twenty five percent to spare.",
    "Most lenders will also want you to have some industry experience or a management team that does.",
    "Closing takes sixty to ninety days from a signed purchase agreement, and it's slower if the business owns real estate.",
    "One more thing, the SBA guarantee fee is two to three and three quarters percent of the guaranteed portion, and you can roll it into the loan.",
    "So to recap: ten percent down, half of it can be a standby seller note, ten year term, personal guarantee, DSCR of one point two five.",
], every=3)

YT02 = with_filler([
    "This video is about due diligence, the ninety days between your accepted offer and the day you actually own the business.",
    "The single most important document is the quality of earnings report, and yes you should pay for one even on a small deal.",
    "A quality of earnings report costs somewhere between eight and twenty thousand dollars for a business under five million in revenue.",
    "What it does is verify that the seller's discretionary earnings number is real, by tying the tax returns to the bank statements.",
    "Add-backs are where deals go wrong: the seller adds back their salary, their truck, their cell phone, and suddenly the earnings look great.",
    "My rule is that a legitimate add-back is an expense that will genuinely disappear when the seller leaves, and nothing else.",
    "Customer concentration is the second killer: if any single customer is more than twenty percent of revenue, price that risk in or walk.",
    "Ask for the customer list by revenue for the last three years and look for churn, not just the top ten.",
    "Working capital is the thing first time buyers forget; you need to negotiate a working capital peg so you don't buy a business with an empty bank account.",
    "A normal peg is the trailing twelve month average of accounts receivable plus inventory minus accounts payable.",
    "Talk to at least three customers and three employees before closing, with the seller's permission, obviously.",
    "Check that every lease, contract and license is assignable; a non-assignable lease has killed more deals than bad financials.",
    "Finally, get the seller to stay for a transition period, ninety days is typical, and put it in the purchase agreement with a holdback.",
], every=3)

# a long one: ~45 minutes, five sections, nuggets buried among a lot of talk
LONG_SECTIONS = {
    "search": [
        "Let's start with the search phase, which is where most people spend a year and buy nothing.",
        "The businesses that sell are the boring ones: HVAC, landscaping, commercial cleaning, small manufacturing.",
        "You will look at a hundred listings to get to ten conversations to get to one letter of intent, that's the funnel.",
        "Brokers list on BizBuySell and the like, but the best deals I've bought came from direct outreach to owners over fifty five.",
        "Write a one page buyer profile: who you are, what you're looking for, and how you'll finance it, and send it to every broker in your metro.",
    ],
    "loi": [
        "Now the letter of intent, which is non binding except for exclusivity and confidentiality.",
        "Put a sixty day exclusivity period in the LOI, that's enough time for diligence and it keeps the seller from shopping your offer.",
        "Price the LOI at a multiple of seller's discretionary earnings, and state the SDE number you're basing it on so there's no argument later.",
        "Small businesses under a million in SDE typically trade at two to three and a half times SDE, and anything above four needs a special reason.",
        "Include the working capital peg concept in the LOI even if you don't have the number yet.",
    ],
    "financing": [
        "On financing, the structure I like is ten percent equity, ten percent seller note, and eighty percent SBA.",
        "The seller note in that structure is separate from the equity injection unless it's on full standby, which most sellers won't accept.",
        "Get a term sheet from two lenders, because the rates differ by a full point and the closing timelines differ by a month.",
        "Lenders will ask for a business plan, three years of personal tax returns, and a personal financial statement.",
        "If the business owns its building, the real estate can go on a twenty five year 7a or a 504 loan, which lowers the monthly payment a lot.",
    ],
    "closing": [
        "Closing day is boring if you did the work: you sign, the lender wires, and the seller hands over the keys and the passwords.",
        "Have the transition services agreement signed before closing, with the seller's hours per week spelled out.",
        "Change the bank signers, the merchant account, the payroll admin and the insurance the same day, not next week.",
    ],
    "first90": [
        "The first ninety days: change nothing that customers can see.",
        "Meet every employee one on one in the first week and ask what they'd fix; then fix the cheapest one immediately.",
        "Do not raise prices in the first ninety days, do not change the name, do not fire anyone unless it's a safety issue.",
        "Your only job in the first quarter is to keep the revenue that you just paid for.",
    ],
}
_SUBJ = ["a client of mine", "a guy I talked to last month", "my first deal", "one of my students", "a broker I know", "the seller on my second deal"]
_VERB = ["spent six months on", "completely ignored", "got burned by", "over-thought", "nailed", "argued with the lender about"]
_OBJ = ["the paperwork", "the timeline", "the inventory count", "the employee handbook", "the lease renewal", "the truck fleet", "the software subscriptions"]
_TAIL = ["and it worked out fine in the end.", "and honestly it didn't matter.", "which is a story for another day.", "and we laugh about it now.",
         "and that's why I always say, keep it simple.", "so, you know, your mileage may vary."]


def chatter() -> str:
    return f"{rng.choice(_SUBJ).capitalize()} {rng.choice(_VERB)} {rng.choice(_OBJ)} {rng.choice(_TAIL)}"


LONG_LINES: list[str] = []
for name, core in LONG_SECTIONS.items():
    LONG_LINES.append(f"Okay, next section, let's talk about {name.replace('first90', 'the first ninety days').replace('loi', 'the letter of intent')}.")
    for ln in core:
        LONG_LINES.append(ln)
        for _ in range(38):          # ~75 minutes of talk: the nuggets have to be found, not read
            LONG_LINES.append(rng.choice(FILLER) if rng.random() < 0.25 else chatter())

PODCAST = with_filler([
    "Welcome back to the show, today my guest is a serial acquirer who has bought eleven businesses with none of his own money.",
    "So the first thing I tell people is that the ten percent down payment is a myth, you can buy a business with zero percent down using seller financing for the whole purchase.",
    "The way you do it is you find a tired owner, you offer full price, and you pay them over five to seven years out of the business's own cash flow.",
    "I've never used an SBA loan and I never will, the personal guarantee is a trap and the paperwork takes three months.",
    "On valuation, everyone quotes two to three times earnings, but in home services I'm regularly seeing four to six times SDE because private equity is rolling those up.",
    "So if you're a seller in HVAC or plumbing right now, don't accept three times, you're leaving money on the table.",
    "The other thing I'd push back on is the quality of earnings report, on a deal under two million I just have my bookkeeper look at the bank statements, saves fifteen grand.",
    "Where I do agree with the conventional advice is customer concentration, one customer over twenty percent and I'm out.",
], every=4)

VLOG = with_filler([
    "Good morning from the van, we woke up at a trailhead in Utah and the sunrise was unreal.",
    "Today's plan is coffee, a short hike, and then we drive three hours to the next spot.",
    "A lot of you asked about the solar setup, it's four hundred watts on the roof and a two hundred amp hour battery.",
    "The water tank is twenty gallons and it lasts us about four days if we're careful.",
    "Alright the hike was about five miles, lots of red rock, and we saw exactly zero people.",
], every=2)


def transcript(path: str, lines: list[str]) -> dict:
    s = segs(lines)
    return {"segments": s, "duration": s[-1]["end"]}


# ---------------------------------------------------------------- article (html)

ARTICLE = """<html><head><title>How small businesses are valued: SDE and EBITDA multiples explained</title></head>
<body><nav><a href="/">Home</a> <a href="/blog">Blog</a></nav>
<article>
<h1>How small businesses are valued: SDE and EBITDA multiples explained</h1>
<p>Most businesses with under $1 million in earnings are priced on seller's discretionary earnings (SDE): net profit plus the owner's salary, benefits, and one-time or personal expenses run through the business. Businesses with professional management and more than about $1 million in earnings are priced on EBITDA instead, because a buyer will have to pay a manager.</p>
<h2>Typical multiples</h2>
<p>Across the main-street market, SDE multiples cluster between 2.0x and 3.5x. The multiple rises with earnings size, recurring revenue, documented systems, and a workforce that runs without the owner. It falls with customer concentration, owner dependence, and declining revenue. Businesses with more than $1 million of EBITDA typically trade at 4x to 6x EBITDA in the lower middle market.</p>
<h2>What moves the multiple</h2>
<p>Three factors dominate: how transferable the revenue is, how much the owner does personally, and how clean the books are. A business with contracts that assign to a new owner, a general manager in place, and reviewed financials can command the top of the range. A business whose revenue depends on the owner's relationships, with cash sales and a shoebox of receipts, will sit at the bottom or below it.</p>
<h2>Working capital and inventory</h2>
<p>The quoted price usually excludes cash and includes the inventory needed to operate. Whether accounts receivable transfer is negotiated deal by deal. A working capital peg &mdash; a normal level of receivables plus inventory minus payables that the seller must deliver at closing &mdash; protects the buyer from a seller who collects every receivable the week before closing.</p>
<h2>Sanity check with the lender</h2>
<p>Whatever multiple you agree on, an SBA lender will independently require the business's cash flow to cover the proposed loan payments with a debt service coverage ratio of at least 1.25. If it does not, the price is too high for that financing structure regardless of what comparable sales say.</p>
</article>
<footer>&copy; Example Advisory. Not financial advice.</footer></body></html>"""

# ---------------------------------------------------------------- report (pdf), hand-built so there is no dependency

def _pdf(pages: list[list[str]]) -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids = []
    kids_placeholder = add(b"")   # pages object, filled later
    for lines in pages:
        content = ["BT /F1 11 Tf 50 750 Td 14 TL"]
        for ln in lines:
            safe = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.append(f"({safe}) Tj T*")
        content.append("ET")
        stream = "\n".join(content).encode("latin-1")
        c = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        p = add(f"<< /Type /Page /Parent {kids_placeholder} 0 R /MediaBox [0 0 612 792] /Contents {c} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
        page_ids.append(p)
    objs[kids_placeholder - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(page_ids)} >>".encode()
    catalog = add(f"<< /Type /Catalog /Pages {kids_placeholder} 0 R >>".encode())
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def wrap(text: str, width: int = 90) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


REPORT_PAGES = [
    ["SBA 7(a) Business Acquisition Lending - Program Summary (fixture)", ""]
    + wrap("This summary describes the standard terms a lender applies to a change-of-ownership loan under the 7(a) program. It is a fixture for testing and not guidance.")
    + [""] + wrap("1. Maximum loan amount. The maximum gross loan amount under 7(a) is $5,000,000. The guaranteed portion is 75% for loans above $150,000 and 85% for loans of $150,000 or less."),
    ["2. Equity injection", ""]
    + wrap("For a complete change of ownership the borrower must inject equity of at least 10% of the total project cost. Seller debt may count toward the equity injection only when it is on full standby (no payments of principal or interest) for the entire term of the 7(a) loan, and only up to half of the required injection.")
    + [""] + wrap("3. Maturity. Loans financing a business acquisition without real estate have a maximum maturity of 10 years. Where real estate is the largest component of the loan, the maturity may be up to 25 years."),
    ["4. Guarantees and collateral", ""]
    + wrap("Each owner of 20% or more of the applicant business must provide an unlimited personal guarantee. The lender must take available collateral, including the assets of the business acquired, but a loan is not declined solely for lack of collateral.")
    + [""] + wrap("5. Repayment ability. The lender must document that the business's historical and projected cash flow covers the proposed debt service. Lenders commonly require a debt service coverage ratio of at least 1.25 on a trailing twelve month basis.")
    + [""] + wrap("6. Guarantee fee. The upfront guarantee fee ranges from 2% to 3.75% of the guaranteed portion depending on loan size and maturity, and may be financed as part of the loan."),
]

# ---------------------------------------------------------------- calculator (xlsx)

def build_xlsx(path: Path) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deal"
    rows = [
        ("Deal calculator (fixture)", None),
        ("Purchase price", 1000000),
        ("Down payment %", 0.10),
        ("Seller note %", 0.10),
        ("Interest rate", 0.105),
        ("Term (years)", 10),
        ("Annual SDE", 320000),
        ("Buyer salary", 90000),
        (None, None),
        ("Down payment", "=B2*B3"),
        ("Seller note", "=B2*B4"),
        ("SBA loan amount", "=B2-B10-B11"),
        ("Monthly payment", "=-PMT(B5/12,B6*12,B12)"),
        ("Annual debt service", "=B13*12"),
        ("Cash flow after salary", "=B7-B8"),
        ("DSCR", "=B15/B14"),
        ("Cash left after debt", "=B15-B14"),
    ]
    for i, (a, b) in enumerate(rows, 1):
        if a is not None:
            ws.cell(row=i, column=1, value=a)
        if b is not None:
            ws.cell(row=i, column=2, value=b)
    wb.save(path)


# ---------------------------------------------------------------- write everything

def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    tr = {
        "yt01_sba_basics.json": transcript("yt01", YT01),
        "yt02_due_diligence.json": transcript("yt02", YT02),
        "yt03_deal_walkthrough_long.json": transcript("yt03", LONG_LINES),
        "podcast_contrarian.json": transcript("pod", PODCAST),
        "vlog_irrelevant.json": transcript("vlog", VLOG),
    }
    for name, payload in tr.items():
        (HERE / name).write_text(json.dumps(payload, indent=1))
    (HERE / "article_valuation.html").write_text(ARTICLE)
    (HERE / "report_sba_summary.pdf").write_bytes(_pdf(REPORT_PAGES))
    build_xlsx(HERE / "deal_calculator.xlsx")
    (HERE / "irrelevant_sourdough.txt").write_text(
        "Sourdough starter notes\n\nFeed the starter equal weights of flour and water every twelve hours at room temperature. "
        "A starter is ready to bake with when it doubles within four to six hours of feeding. Bulk fermentation at 78F takes "
        "about five hours; shape, then cold retard in the fridge overnight. Bake at 500F in a covered dutch oven for twenty "
        "minutes, then uncovered at 450F for twenty five minutes. Let the loaf cool fully before slicing or the crumb will be gummy.\n")
    print("wrote fixtures to", HERE, "crc", zlib.crc32(b"".join(sorted((HERE / n).read_bytes() for n in tr))))


if __name__ == "__main__":
    main()

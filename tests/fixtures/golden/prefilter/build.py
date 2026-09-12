"""Generates the frozen labeled-window fixture for the findings pre-filter (Rung H1). Run once:
`python tests/fixtures/golden/prefilter/build.py`. Deterministic, synthetic, no real people.

The Golden Project's own ten windows are too few and too small to say anything about a rejection filter (its two
irrelevant sources are ~500 chars each). These extra sources are added to the SAME golden project by the pre-filter
eval and labeled PER WINDOW:

  beekeeping   two long windows, both irrelevant (a beekeeping podcast)          → the filter should drop both
  marathon     one long window, irrelevant (a marathon training vlog)            → drop
  mixed        two windows of one 'small business owner' video: window 0 is restaurant social-media marketing (irrelevant to an
               acquisition), window 1 has a planted seller-transition nugget        → window-level, not source-level, decisions
  tangent      one long window that is 95% rambling filler with ONE buried acquisition nugget (working capital peg)
                                                                                  → must be KEPT: the hard recall case
Labels live in labels.json (per source: windows, relevant flags, planted nuggets with the window they sit in). A test
asserts the generated files still produce exactly these windows under findings._windows.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20260907)


def segs(lines: list[str], start: float = 0.0) -> list[dict]:
    out, t = [], start
    for ln in lines:
        d = max(2.0, min(12.0, len(ln.split()) / 2.6))
        out.append({"start": round(t, 1), "end": round(t + d, 1), "text": ln})
        t += d
    return out


def prose(topic: list[str], n: int, filler: list[str], every: int = 4) -> list[str]:
    out = []
    for i in range(n):
        out.append(rng.choice(topic))
        if i % every == every - 1:
            out.append(rng.choice(filler))
    return out


GENERIC_FILLER = [
    "So before we get into it, if you're new here, hit the subscribe button, it really helps the channel.",
    "Alright, let me pull up my notes here, give me one second.",
    "And I get this question all the time in the comments so I figured I'd just make a video about it.",
    "Anyway, that's a tangent, let's get back to the main topic.",
    "Let me know in the comments if you want a deeper video on that part.",
    "Okay so where was I, right, the next thing.",
    "Honestly this is the part most people skip and then they regret it.",
    "We had some audio issues earlier so apologies if the first minute sounded weird.",
    "I'm going to grab some water, hold on.",
    "The dog is barking again, sorry about that, he does that when the mail comes.",
]

BEES = [
    "A healthy colony in spring will have a laying queen, capped brood in a good pattern, and at least four frames of bees.",
    "When you inspect the hive, work from the outside frames in and keep the smoker going the whole time.",
    "Varroa mites are the number one killer of managed colonies, so do a sugar roll or alcohol wash count every month.",
    "If you count more than three mites per hundred bees, you need to treat, and oxalic acid vapor is what most beekeepers use in winter.",
    "Swarm season starts when the maples bloom; look for queen cups along the bottom bars and add a second brood box early.",
    "Foundationless frames let the bees draw natural comb, but they need a guide strip or they build it crooked.",
    "Harvest honey only from the supers, never from the brood boxes, and leave the colony at least sixty pounds for winter.",
    "An uncapped frame can be too wet; check it with a refractometer and only extract below eighteen percent moisture.",
    "Requeening every second year keeps the colony vigorous; mark the queen with the year's color so you can find her.",
    "A nuc is a five frame starter colony and it is by far the easiest way for a beginner to start.",
    "Feed one to one sugar syrup in spring to stimulate brood and two to one in autumn to build stores.",
    "The entrance reducer stays on through winter to keep mice out and to help the guard bees defend the hive.",
    "Propolis is sticky and everywhere; keep a hive tool in your back pocket and a bucket of soapy water for your gloves.",
    "Drones get evicted in the fall, which is the colony's way of cutting costs before winter.",
    "If you see wax moth webbing in a weak hive, combine it with a stronger colony using the newspaper method.",
    "Pollen patties in late winter help the colony build up before the first natural pollen comes in.",
]
BEE_FILLER = GENERIC_FILLER + [
    "My neighbor's kids came over to watch the inspection and one of them got a little too close to the entrance.",
    "The weather this week has been all over the place, which the bees do not love.",
]

RUN = [
    "The eighteen week plan builds from twenty five miles a week to a peak of fifty, with a cutback every fourth week.",
    "Long runs go up by no more than two miles at a time, and the longest one is twenty miles three weeks out from race day.",
    "Easy days need to be genuinely easy, which for most people means a conversational pace that feels almost too slow.",
    "Tempo runs are twenty to forty minutes at the pace you could hold for an hour, and they're the workout that moves the needle most.",
    "Fuel every forty five minutes on the long run with gels or chews, and practice with exactly what you'll use on race day.",
    "I rotate two pairs of shoes and retire them around four hundred miles, whichever pair feels flat first.",
    "The taper is where people panic; cut volume by about forty percent over the last two weeks but keep a little intensity.",
    "Race morning breakfast is oatmeal and a banana three hours before the start, then a gel fifteen minutes before the gun.",
    "Hydration on the course is two cups at every aid station, alternating water and sports drink, and salt tabs if it's hot.",
    "Strength work twice a week: single leg squats, calf raises, and a plank, nothing fancy, twenty minutes.",
    "If a niggle lasts more than three runs, take three days off; a week off now beats six weeks off later.",
    "Pace the first ten kilometers slower than goal pace, that's the whole secret to not blowing up at mile twenty.",
    "Track the long run heart rate; if it drifts more than ten percent in the second half you're going too hard.",
    "The week before the race, lay out the kit, pin the bib, and do nothing new.",
]
RUN_FILLER = GENERIC_FILLER + [
    "Today's run was along the river path, it was foggy and honestly gorgeous.",
    "Quick shout out to the running club, they organized the water stops for the long run this weekend.",
]

RESTAURANT_MARKETING = [
    "If you run a restaurant, your Instagram grid is your menu now, so shoot every dish in daylight next to the window.",
    "Post three times a week and put the daily special in stories with a countdown sticker; it drives lunch traffic.",
    "Reply to every Google review within a day, the bad ones especially, and never argue in public.",
    "A loyalty punch card sounds old fashioned but the return rate on the tenth-visit free meal is still the best value in marketing.",
    "Local micro-influencers with five thousand followers convert better than anyone with a hundred thousand, and they'll come for a free dinner.",
    "Run the email list off the wifi login; people give you their address for the password and that list is worth more than any ad.",
    "The neighborhood Facebook group is where reservations actually come from for a place like mine.",
    "Menu photos with a person's hand in the frame get about twice the saves, don't ask me why.",
    "Update the Google listing hours before every holiday, the number of angry people who show up to a closed door is amazing.",
    "Short video of the kitchen at service beats any polished ad; people want to see the flame and the noise.",
]
OWNER_TRANSITION = [
    "Now the second half of today is about the deal we did last year when we bought the second location from the retiring owner.",
    "We used an SBA loan and the broker walked us through the purchase agreement, which was more paperwork than I expected.",
    "The thing I'd tell anyone buying a small business: expect the seller to stay for ninety days of transition, and write the hours into the agreement.",
    "Our seller stayed three months, introduced us to every supplier, and that alone kept two accounts we would have lost.",
    "We negotiated a holdback of ten percent of the price that was paid out after the transition period, which kept everyone honest.",
    "The lender wanted a personal guarantee and three years of tax returns from us, and the whole close took about seventy days.",
    "Working capital was the surprise: the bank account came empty on day one because the peg wasn't in the agreement.",
    "If I did it again I'd insist on a working capital peg based on the trailing twelve months, like the advisors say.",
    "The staff were nervous, so the seller and I did a joint meeting on day one and said nothing changes for ninety days.",
    "That's the deal story; next week we're back to marketing and the new patio.",
]

TANGENT = [
    "So we're driving up to the lake house and the whole family is in the car, which is chaos.",
    "The kids wanted to stop at that diner with the giant pancakes, you know the one.",
    "I've been thinking about repainting the garage, maybe a darker grey, the light grey shows every mark.",
    "My brother-in-law swears by that pressure washer, I might borrow it before the winter.",
    "The podcast I was listening to last week was about the history of the postal service, weirdly fascinating.",
    "We finally fixed the sprinkler zone that's been broken since spring, turned out to be a cracked fitting.",
    "The neighbors got a puppy and now our dog stands at the fence all day.",
    "I tried making pizza dough from scratch, it was fine, not great, the oven doesn't get hot enough.",
    "Traffic on the interstate was backed up for an hour because of a boat trailer that lost a wheel.",
    "My phone updated overnight and moved all the icons around again, which drives me crazy.",
    "We're hosting the reunion this year, so I've been looking at rental tables and a tent.",
    "The lawn has that brown patch again; I think it's grubs, the guy at the hardware store said to check.",
    "Anyway the weather this weekend looks perfect for the lake, seventies and no wind.",
    "I need to remember to renew the trailer registration before the end of the month.",
]
TANGENT_NUGGET = [
    "Oh, one thing from the business side, since a few of you asked: the accountant told us to negotiate a working capital peg equal to the trailing twelve month average of receivables plus inventory minus payables, otherwise you buy a company with an empty bank account.",
    "That was the whole lesson from the acquisition: get the peg in the purchase agreement, don't take the seller's word for it.",
]


def build() -> None:
    bees = prose(BEES, 700, BEE_FILLER)                       # ~2 windows at WINDOW_CHARS 60000
    marathon = prose(RUN, 420, RUN_FILLER)                    # ~1 window
    mixed = prose(RESTAURANT_MARKETING, 470, GENERIC_FILLER) + prose(OWNER_TRANSITION, 100, GENERIC_FILLER)  # window 0 = marketing only (the 60k cut falls inside it); window 1 = its tail + the deal story
    tang = prose(TANGENT, 250, GENERIC_FILLER)
    tang = tang[:180] + TANGENT_NUGGET + tang[180:]           # the nugget buried two thirds in
    files = {
        "beekeeping.json": {"segments": segs(bees), "duration": None},
        "marathon.json": {"segments": segs(marathon), "duration": None},
        "mixed.json": {"segments": segs(mixed), "duration": None},
        "tangent.json": {"segments": segs(tang), "duration": None},
    }
    for name, payload in files.items():
        payload["duration"] = payload["segments"][-1]["end"]
        (HERE / name).write_text(json.dumps(payload, indent=1))
    labels = {
        "version": 1,
        "sources": [
            {"id": "beekeeping", "file": "beekeeping.json", "platform": "youtube", "external_id": "prefilt0001", "url": "https://www.youtube.com/watch?v=prefilt0001",
             "title": "Backyard beekeeping: a full season, start to finish", "channel": "Hive Mind", "windows": 2, "relevant": [False, False], "nuggets": []},
            {"id": "marathon", "file": "marathon.json", "platform": "youtube", "external_id": "prefilt0002", "url": "https://www.youtube.com/watch?v=prefilt0002",
             "title": "My 18-week marathon training plan, week by week", "channel": "Slow Miles", "windows": 1, "relevant": [False], "nuggets": []},
            {"id": "mixed", "file": "mixed.json", "platform": "youtube", "external_id": "prefilt0003", "url": "https://www.youtube.com/watch?v=prefilt0003",
             "title": "Restaurant owner vlog: marketing that works + how we bought our second location", "channel": "Table for Two", "windows": 2, "relevant": [False, True],
             "nuggets": [{"window": 1, "quote": "expect the seller to stay for ninety days of transition", "why": "seller transition rule in the relevant window of a mixed source"}]},
            {"id": "tangent", "file": "tangent.json", "platform": "youtube", "external_id": "prefilt0004", "url": "https://www.youtube.com/watch?v=prefilt0004",
             "title": "Lake weekend, garage paint and one business lesson", "channel": "Weekend Rambles", "windows": 1, "relevant": [True],
             "nuggets": [{"window": 0, "quote": "negotiate a working capital peg equal to the trailing twelve month average", "why": "one nugget in 95% filler: the filter must keep this window"}]},
        ],
        # the golden project's own windows: everything is relevant except the two planted off-topic sources
        "golden": {"yt01": [True], "yt02": [True], "yt03": [True, True], "pod": [True], "vlog": [False], "article": [True], "report": [True], "calc": [True], "sourdough": [False]},
    }
    (HERE / "labels.json").write_text(json.dumps(labels, indent=1))
    for name in files:
        n = sum(len(s["text"]) for s in files[name]["segments"])
        print(name, n, "chars")


if __name__ == "__main__":
    build()

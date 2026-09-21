# Completing the Discovery relevance work — checklist (2026-09-21)

Everything below closes out the thread that began with Kyle's *"I have been BULK approving everything so I don't
think I have been providing good data back to the app."* Full history is in HANDOFF.md; this is only what is
left. Each item says WHO does it, because the three agents on this repo have different reach: the Cowork session
can edit files and now run the test suite (Linux VM, temp DBs only), Claude Code and Codex have the real macOS
shell and the live database, and some judgements are only Kyle's.

---

## A. Finish the run that is already in flight

**A1. Promote the candidates a bug of mine stranded.** `--resurface` only moved items whose OLD score was under
the cutoff, so ~322 that were already lifted by an earlier slice never moved. Fixed in the tool; this collects
them. Free, no model calls. — *Claude Code*

```
.venv/bin/python tools/rescore_candidates.py --project c752ed152ec942dd97b9a94c3f1b3b96 --resurface-only
```

**A2. Top up descriptions for the ~408 candidates that arrived in `available` after the backfill.** ~9 quota
units of 10,000, seconds. — *Claude Code*

```
.venv/bin/python tools/backfill_descriptions.py --project c752ed152ec942dd97b9a94c3f1b3b96 --limit 500
```

**A3. Confirm two test failures are environmental, not real.** Both fail in the Cowork VM for reasons that look
like the environment (`doctor` wants a configured provider; `sample_findings` uses `E5_COHORT`, source ids that
exist only in the live database). If they pass on the Mac, the suite is clean. — *Claude Code*

```
.venv/bin/pytest tests/test_j3_fallback.py tests/test_l05_sample_findings.py -q
```

---

## B. Stop the problem from rebuilding itself

**B1. ~~Wire `youtube_api.playlist_items` into `media.enumerate_entries`.~~ DONE 2026-09-21 — shipped as an ENRICHMENT rather than a replacement listing; see the note below.** This was the highest-value item left.
Today's backfill cleared a backlog; without this, every new channel adds description-less candidates and the
backlog returns. The API gives id + title + description + publishedAt at 1 quota unit per 50, so a 400-video
channel enumerates with descriptions in seconds — strictly better than the current flat listing, which is fast
precisely because it fetches none of that. Must fall back to yt-dlp when no key is set or the source is not
YouTube, so behaviour is unchanged for anyone without a key. Needs tests and a live check on one real channel.
— *Cowork writes it; Claude Code verifies against a real channel*

> **What shipped, and why it differs from the plan above.** Listing through `playlistItems` would have been a
> REPLACEMENT for the flat listing, and that turns out to lose things: a channel's uploads playlist omits
> members-only videos, and the API has no equivalent of the Shorts tab `enumerate_entries` scans. It would have
> traded one blind spot for another. So the flat listing stays the sole authority on which videos exist, and
> `media._enrich_youtube` fills in only what flat extraction cannot carry — description, publish date, duration,
> view count, captions-exist — for the first `media.ENRICH_MAX` (600) entries, filling EMPTY fields only. No key,
> spent quota, or an outage leaves the listing exactly as it was. Also wired into `enumerate_search`, since
> Discover hands those straight to the ranker. 21 new tests (`test_ad8_*`, `test_ad9_*`); full suite 2,221 passed
> in the sandbox with only the two known environmental failures.
>
> **Still owed:** the live check against one real channel, which needs a key and the Mac. — *Claude Code*
>
> ```
> .venv/bin/python -c "from neurosearch import media; i,e = media.enumerate_entries('https://www.youtube.com/@AcquiringMinds'); print(len(e), 'entries;', sum(1 for x in e if x.get('description')), 'with descriptions')"
> ```

**B2. ~~A lockfile on `rescore_candidates.py`.~~ DONE 2026-09-21.** New `tools/_runlock.py`: an exclusive
`flock` held for the life of the process, taken by `rescore_candidates.py` AND `backfill_descriptions.py` (same
problem, shared daily quota). The kernel releases it on process death for any reason, so there is no stale-lock
state and nothing to clean up. `--dry-run` does not take it; `--ignore-lock` exists and says out loud that every
budget ceiling becomes per-run. Scoped per tool, not per project — a second run against a DIFFERENT project would
still double the spend against the same API key, which is the thing that actually costs money. — *Cowork*

---

## C. Prove the fix actually worked (the real closure)

**C1. Re-run the AD4B blind review against the NEW scores.** The 77% that justified all of this was measured
against the broken filter. Nothing yet measures the FIXED one from Kyle's side — the 0-19 band dropping from 6%
to 0.3% shows noise stays down, but not whether the things now surfacing are things he wants. Same tool, same
blind method, directly comparable number. ~20 minutes of Kyle's time, no model cost. — *Claude Code generates;
Kyle judges*

```
.venv/bin/python tools/ad4b_blind_sample.py --project c752ed152ec942dd97b9a94c3f1b3b96 --out evals/ad4b-sample-after-fix.json --html
```

Then open `evals/ad4b-sample-after-fix.html`, judge all 30 blind, and run the scorer on the downloaded file.
**Pass:** the kept-rate falls well below 77% — the filter is no longer discarding things he wants. If it stays
high, the prompt still is not matching his judgement and the band table says where.

**C2. Decide the AI-automation creators.** Nick Puru, Nate Herk and Liam Ottley clear the cutoff on a
business-acquisition project because the prompt rewards "teaches transferable method" and their descriptions are
dense with business language. Two levers: Lose them in focus review (creator_verdict drives them to −12 after
three real rejections), or exclude them outright via `project_excludes` with `kind='creator'`, the mechanism
already filtering laundromats. The first teaches the system; the second is immediate and total. — *Kyle decides*

---

## D. Judgement calls, then small builds

**D1. ~~Should a dismissed finding count NEGATIVELY against a creator, or just at zero?~~ DECIDED 2026-09-21:
stays at zero. NO CODE CHANGE NEEDED** — that is already the behaviour. `candidates.creator_yield` filters with
`COALESCE(status,'') <> 'dismissed'`, so a dismissed finding is excluded from the count rather than subtracted
from it. Verified in place rather than assumed. The asymmetry with sources (where a Lose is worth exactly what
a Keep is worth) is now a deliberate, recorded choice: dismissing a finding usually means "not this claim", not
"not this creator". — *decided by Kyle*

**D2. ~~A findings focus reviewer.~~ CLOSED 2026-09-21 — not worth building, on D1's answer.** This item was
explicitly gated: "only worth it if D1 makes finding-level judgement load-bearing." D1 decided that a dismissed
finding counts zero, so finding-level judgement feeds nothing downstream — there is no scoring signal for hours
of review to improve. Reopen only if some future feature gives a finding decision weight beyond the finding
itself. — *closed on Kyle's D1 answer*

**D3. Backfill descriptions for the remaining states.** `skipped_limit` (574, none have descriptions) and
`acquired` (841, 2%). Cheap — ~28 quota units total. Lower value than A2 since these are not in the review path,
but it makes the index uniform. — *Claude Code*

---

## E. Optional, tied to existing features rather than to a platform

**E1. ~~FRED~~ CLIENT DONE 2026-09-21 — needs a free key before it does anything.** `neurosearch/fred.py`:
`prime()`, `observation(series, on=...)`, `rates([...])`, `max_rate(spread)`. Key-gated exactly like
`youtube_api` — without `NEUROSEARCH_FRED_API_KEY`, `available()` reports off and nothing calls it, so the app
is unchanged until Kyle adds one.

Two things it deliberately does NOT do. It does not read FRED's `.` (a weekend, a bank holiday) as a number —
that would make a prime rate of 0.0, which nothing downstream would catch; every read walks back to the most
recent real value. And it does not know the SBA spread: that is SOP 50 10's, and SOPs get superseded, so a
constant here would be a second unversioned copy of a document `works.py` exists to version. `max_rate(spread,
spread_source=...)` takes it and says in the result where it came from. 19 tests. — *Cowork*

**BLOCKED 2026-09-21 — Kyle reports FRED is not available to him right now; revisit later.** The module stays
inert and costs nothing while it waits. A keyless path exists in principle (`fredgraph.csv`, FRED's own public
CSV download, same series ids, no key), but BOTH the Cowork sandbox and the device VM have `fred.stlouisfed.org`
blocked by egress policy, so it could not be verified from here — and shipping unverified network code is the
exact mistake `youtube_api` got away with once. Not built. Say the word and it is a small addition, verified on
the Mac rather than guessed.

**Kyle: the key, when it is available.** Free, no card, about a minute — sign in at
https://fredaccount.stlouisfed.org/apikeys, request an API key, then add the line to `.env` (git-ignored)
exactly as the YouTube one was added:

```
NEUROSEARCH_FRED_API_KEY=your-key-here
```

Then, to check it: `.venv/bin/python -c "from neurosearch import fred; print(fred.available()); print(fred.prime())"`

**E2. ~~Wayback Machine~~ DONE 2026-09-21.** `neurosearch/wayback.py` plus two functions in `works.py`:
`superseded_text(source_id)` returns the last capture taken strictly BEFORE the successor's effective date —
the text a dated finding was actually true of — and `rescue_link(url)` turns a 404'd citation into the nearest
capture. No key, no quota, nothing to configure; it works now.

The design point worth keeping: it uses `before()`, never `nearest()`. The archive's closest capture to a
version's effective date is frequently the one just AFTER it — which is the NEW text, returned confidently as
though it were the old. That is worse than returning nothing, because it reads like an answer. Every failure
mode (never archived, outage, rate limit, a local uploaded copy that was never on the public web) returns None
rather than raising, because an archive outage is not a reason to call a finding unsupported. 25 tests.

**UI DONE 2026-09-21.** `GET /api/sources/{id}/archived` plus a "What it said then" button on the source
drawer. The endpoint labels its answer `superseded` (the capture from before the successor took effect — the
text a dated finding was drawn from) or `nearest` (just the newest capture, worth having for a 404'd citation
but evidence of nothing in particular), and the drawer says different things about each. On demand only: a test
asserts the lookup does not appear anywhere inside `sourceDrawer`, or every source anyone opened would hit
archive.org. 11 tests. — *Cowork*

Explicitly NOT recommended after checking the data: the Podcast Index API. Free and it exposes publisher
transcripts, but Kyle has **zero** podcast-platform sources — 1,471 of 1,616 are YouTube. Revisit only if that
changes.

---

## Order

A1 → A2 → A3 (minutes, finishes what is running) → **C1** (the measurement that says whether any of this
worked) → B1 (stops the backlog returning) → everything else by whatever C1 reveals.

# State of the App — 2026-09-22 21:30 PT

Written by Claude Desktop at the close of P11 EA-9 live setup. The previous note
(`docs/archive/state/STATE-OF-THE-APP-2026-09-21-2300.md`) covers everything before P11 went live.

## Where main is

- Version **0.64.0** (`pyproject.toml`, `neurosearch/__init__.py`, `web/js/state.js`, `index.html` meta).
  Extension unchanged (1.9.6).
- Full suite **2,471 passed, 0 failed** (Cowork Linux VM, temp DBs). `neurosearch release-check` was **not** run
  (heavyweight, Mac-side).
- Publishing works from the Cowork VM with the committed publisher (`tools/publish_request.py` → PASS receipts).

## P11 — external AI access is live for Kyle

Kyle's own ChatGPT (Pro, Developer mode) reads and writes his Neuro projects:

```
ChatGPT → Secure MCP Tunnel (tunnel_6ab30bc…, LaunchAgent com.neurosearch.tunnel) → Neuro /ext/mcp/
sign-in: WorkOS AuthKit (staging), CIMD client https://chatgpt.com/oauth/<id>/client.json
token checks in Neuro: signature · issuer · aud = tunnel-service URL (NEUROSEARCH_OAUTH_AUDIENCE) · expiry
link: owner approves the pending sign-in in Neuro (banner) — ChatGPT blocks pasted nsi_ codes
```

Measured live (EA-9A–F): read (list/open/consult), explicit write → committed fact quoting the user, inferred
write → held in "Waiting for your review", inferred project → `confirm_project`, late save from a normal chat,
catch-up read in a fresh chat, file attached before Neuro was mentioned → original kept (after S83). Pro allowed
writes, so `account_tier_write_unavailable` does not apply to Kyle.

Fixed from live failures today: owner-approved sign-ins (S82); strict `openai/fileParams` schema, tolerant
`client_capabilities`, descriptive (not directive) tool text that ChatGPT no longer flags as "Suspicious
Instruction", account-level approval banner, Settings auto-refresh (S83).

## Not done / open

- **Gio (9G) not started.** For a personal ChatGPT account the tunnel is associated via that person's personal
  Platform organization (OpenAI docs). Plan: add Gio's `org-…` ID to the tunnel; if that is refused, a second
  tunnel in Gio's org served by a second tunnel-client profile on Kyle's Mac. Gio's guide: Claude Doc
  "Connect your ChatGPT to Neuro".
- **Neuro server auto-start** is written (`tools/server_agent.py`, `com.neurosearch.server`,
  `tools/install_server_agent.sh`) but **not installed** — needs one run on the Mac.
- Runtime key for the tunnel (`CONTROL_PLANE_API_KEY`) never expires and appeared in a chat; rotate to a
  90-day key.
- WorkOS is the **staging** environment; fine for two users.
- The Mac must be awake for collaborators to reach Neuro.

## 2026-11-03 — S112 billing correction (live; delivery recorded in HANDOFF)

Kyle changed from Max to Pro and reported repeated Claude usage-credit reloads. The old assumption that
subscription-authenticated Claude Code calls are free is invalid. Version **0.64.5** extends the existing
usage ledger and Spending valve with monthly plan/billing declarations, conservative unverified estimates,
per-call billing snapshots, separate subscription-fee context, and budget checks for potentially paid local
work and probes. Legacy rows are not rewritten as invoices or newly verified savings. No external account
setting or provider credential is changed. Exact validation, publication and live activation are in HANDOFF's
S112 entry; the older snapshot above remains historical.

## 2026-11-12 — Sources and project review updates

Version **0.64.7** is live on the Mac. Sources filters and pages the complete
project list. Re-ranking preserves source selections, the Master Plan download
uses the latest saved plan when available, and the Claims review queue opens
recorded evidence on demand. Deep-read progress counts completed passages.
HANDOFF records the production checks, benchmark, and release evidence.

## 2026-11-12 — Find passages in Sources

Version **0.64.8** is live on the Mac. Find passages searches indexed source
text in the project or within one source, and opens results at available
source locators. It uses the existing full-text index. HANDOFF records the
live verification, release gates, and read-only review of novelty flags.

## 2026-11-12 — Claim challenges and novelty assessments

Version **0.64.9** is live on the Mac. Claims review distinguishes corroboration,
qualification, and cited disagreement. Show evidence opens the paired passages
and Challenge this claim searches project passages and optional library leads
for manual assessment. The downloadable assessment records the scope and date
of the search, passage judgments and remaining gaps. See HANDOFF for the live
checks and release evidence.

## 2026-11-12 — Queue progress

Version **0.64.10** is live on the Mac. The open queue checks every two
seconds while active. Its bars follow measured work where a count is
available, with current stage and worker check-in visible during longer
steps. The previously repeating Claims harvest finished in one pass.
HANDOFF records the live check and release evidence.

## 2026-11-12 — Claims provider fallback and Accelerate

Version **0.64.11** is live on the Mac. Claude Code remains the primary
provider for Claims extraction, and the connected ChatGPT plan is the
first fallback. Priority Claims use the same local-preferred policy as
bulk Claims. The paid API remains available by explicit choice.
Accelerate quotes the remaining Claims work, with the quote visible
during a Claude hold. See HANDOFF for the synthetic pilot, release
gates, and live checks.

## 2026-11-12 — Claims stream and response recovery

Version **0.64.12** is live on the Mac. A dropped ChatGPT stream gets a
short retry through the existing provider ledger. ChatGPT Claims calls
now use strict structured output and retry an unexpected schema mismatch
once on the connected plan. See HANDOFF for the release checks and
live queue recovery.

## 2026-11-12 — ChatGPT capacity in the queue

Version **0.64.13** is live on the Mac. Jobs waiting for the connected
ChatGPT plan's slot show “Queued for ChatGPT” and stay queued while the
slot is occupied. The queue reports actual provider outages separately.

## 2026-11-12 — Source profiles on this Mac (0.64.14)

Requested source profiles default to Qwen3.5 9B on loopback Ollama on macOS.
Pause Mac work is on the project list and in the project sidebar. It stops
admission, lets the current source profile finish, and keeps the pause across
restarts. The model unloads after each profile. Claude and ChatGPT can still
process their own queues. Claims normalization remains on its existing route.

## 2026-11-12 — Mac Findings overflow (0.64.15)

Gemma 4 26B can take up to two ordinary Findings jobs waiting on a
spending limit or ChatGPT's occupied slot. It shares the existing job
queue and Pause Mac work control. Claims still uses the subscribed
providers because the tested local models failed qualifier checks.

## 2026-11-12 — ChatGPT gives Finding suggestions the next slot (0.64.16)

When Finding suggestions are ready and queued for the connected ChatGPT
plan, they go ahead of Claims extraction on that plan. An in-flight
request finishes. Claims can use Claude as usual, and eligible Findings
can still run on the Mac in parallel.

## 2026-11-12 — Faster research-map refresh (0.64.17)

Evidence-target matching reuses a project lookup during a refresh.
A large backup project went from 858.53 s to 78.70 s with matching
research results. HANDOFF records the comparison across three
projects and the ingestion-to-first-Finding baseline across four.

## 2026-11-12 — Saved challenges and Plan evidence (0.64.18)

Claim evidence can save and reopen the latest manual challenge
assessment, with warnings when the Claim or reviewed passages have
changed. Pending Master Plan updates with a recorded Claim link
can show the Claim and its cited passages next to the proposed edit.

## 2026-11-12 — Precedent and counterevidence in Claim Challenge (0.64.19)

Claim Challenge can search separately for earlier examples and
failures, retain distinct passages from the same Work, and show
searchable-source coverage. Saved assessments flag changes to the
searched collection. The review reports human passage judgments
and leaves novelty unassessed when no equivalent is confirmed.
An 11-case blind review is prepared across six projects.

## 2026-11-12 — Reuse completed research work (0.64.20)

Bulk Claims jobs combine map refreshes across passes. Claim Challenge and
Evidence Targets reuse recorded search work while the corresponding inputs
remain current and expose a full-search action. The Source drawer explains
whether work is waiting, failed, finished with zero findings or ready to start.
Master Plan checks retain completed results and rejection reasons. Accepted
exact wording edits can save a new version with execution status and notes
intact. Repeated query embeddings reuse a bounded local cache.

## 2026-11-12 — Fresh evidence in busy Plan checks (0.64.21)

Master Plan checks reserve prompt space for findings, facts, sources and
conversation so a long findings history cannot crowd out a newly added
source. A changed transcript updates the source timestamp. The three-project
reuse benchmark, queue timing sample and six-project blind review first pass
are recorded in the 0.64.21 handoff.

## 2026-11-12 — First wave for new ingest requests (0.64.22)

New collection requests prioritize their first three items. Direct
small link requests, browser-session imports and queued uploads also
get priority. A four-project queue replay measured earlier first starts
and earlier first transcripts. Results and limitations are in the handoff.

## 2026-11-12 — Earlier YouTube collection cutoff (0.64.23)

Collection items with valid publication dates before the cutoff can be
skipped during listing using the existing batched metadata. Skipped
sources stay available for Ingest anyway. A four-project replay estimated
that p90 collection completion fell from 17m 25s to 11m 26s. The Sources
add endpoint now gives small direct imports the existing priority lane.

## 2026-11-12 — Ingest timing and novelty fixtures (0.64.24)

The performance endpoint shows metadata lock wait, request spacing and
fetch time. Ingest retries use an already-downloaded audio file without
fetching metadata again. Six synthetic novelty cases test whether search
surfaces independent precedents and close passages with different scope.

## 2026-11-12 — Milestone view in Master Plan (0.64.25)

The Plan opens on the active milestone, next actions, and decisions or
blockers. Linked tasks share progress. Rebuilds carry progress to matched
tasks and flag ambiguous matches. Confirmed deadlines and recorded decisions
are project facts. The review area shows verified quotes where available,
and Markdown and HTML exports begin with the milestone and next actions.

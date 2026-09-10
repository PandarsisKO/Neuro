# MISSION — External AI Access + Bidirectional Project Intelligence

**Status: FILED, NOT STARTED.** Kyle dictated this on 2026-09-10 while a fix queue was in progress and said
explicitly: *"I don't want you to work on the expansion mission but I want to add information."* So nothing here is
implemented, nothing here is scheduled, and the sequencing decision is his. The brief below ends with "then
IMPLEMENT IT" and calls two scenarios release blockers — that is the instruction **for when this mission is
started**, not authorisation to start it now. A session picking this up should confirm with Kyle that this is the
current work before writing code.

**Its relationship to the other open mission.** `TRANSCRIPT-INTELLIGENCE-MISSION.md` is about understanding source
material more cheaply. This is about letting other AI clients use what Neuro Search knows. They share one
dependency and one rule: both need project state to be queryable and cheap to assemble, and both are bound by
*never pay twice to rediscover something Neuro Search already learned* — `get_project_context` in particular must
aggregate state the app has already computed, never compute it in the request. The recent fixes make that possible:
0.62.2 moved the research-state pass out of the request path (it cost 431 s), and 0.61.4/0.62.0 did the same for
findings row assembly.

---

## §1 What this is

Neuro Search should be usable by external AI clients — ChatGPT, Claude, future tools — as a private, persistent
project intelligence layer. This is **not** an attempt to recreate Neuro's internal Chat experience inside ChatGPT.

The conceptual separation:

```text
Neuro Search
= ingestion + research memory + project state + retrieval
+ findings + claims + evidence + sources + decisions + provenance

ChatGPT / Claude / future AI clients
= conversation + reasoning + explanation + drafting
+ user-specific personality/context
```

An external AI should be able to:

1. Discover which Neuro projects it has permission to access.
2. Orient itself to a project quickly.
3. Search that project's accumulated knowledge.
4. Retrieve findings, claims, facts, decisions, sources, and evidence as needed.
5. Reason about that material itself.
6. Show citations/evidence only when useful or explicitly requested.
7. Send new evidence back into Neuro.
8. Send PDFs, spreadsheets, documents, correspondence, URLs, and other supported materials into the correct project.
9. Record explicit user decisions, constraints, requirements, or negotiating positions.
10. Never accidentally turn AI speculation or AI-generated drafts into research evidence.
11. Allow multiple humans — Kyle and Gio — to use their own separate ChatGPT accounts against shared Neuro
    projects, without sharing ChatGPT conversations or granting access to every Neuro project.

```text
                    NEURO SEARCH
                         |
                Project Intelligence
                         |
        +----------------+----------------+
        |                |                |
     ChatGPT           Claude        Future clients
        |                |                |
   Kyle's chats      Gio's chats       other tools
        |                |
        +------- same shared --------+
                Neuro projects
```

**The knowledge can be shared without sharing the conversation.**

## §2 First: inspect the actual current repository

Do not begin by blindly implementing this brief. The application has evolved quickly. Read, at minimum: `CLAUDE.md`,
`README.md`, current handoff/architecture documentation, `db.py`, `api.py`, `mcp_server.py`, the current
search/retrieval implementation, the current findings implementation, the current Claims/Research implementation,
the ingestion pipeline, the job system, the source model, the project model, the current auth implementation, the
current tests, and the current UI for Sources, Projects, Research, Settings and ingestion.

Search the repo for related functionality before adding anything. **The current repository is the source of
truth.** If this brief describes a concept that already exists under another name, extend or reuse it rather than
creating a parallel architecture. Do not regress newer functionality merely because an older handoff describes an
earlier implementation.

Preserve Neuro's existing hard-won rules: additive schema migrations · no external direct writes to the SQLite
database · writes go through the running application · the existing job architecture · the existing ingestion
pipeline · existing duplicate handling · existing source processing · existing cost controls and model-routing
behaviour · existing error handling · existing release/version conventions · existing tests.

Avoid unnecessary dependencies. Prefer free, local, open-source and existing components wherever practical. **This
feature should not itself require paid model calls. Tests must not make paid API calls.**

## §3 Core product principle — Neuro is the substrate, not the external chatbot

The external AI should generally **not** call Neuro's existing `ask()` to answer the user's question. That creates:

```text
User -> ChatGPT -> Neuro QA -> another LLM -> Neuro retrieval
```

Redundant, slower, potentially more expensive, and it makes the external conversation behave too much like Neuro's
internal chat. The preferred architecture is:

```text
User -> ChatGPT -> Neuro retrieval / project intelligence -> Neuro database
```

ChatGPT or Claude receives Neuro's evidence and project state and performs its own reasoning. Keep the existing
`ask()` for existing Neuro/Claude workflows if it is useful — do not break it. We are adding a retrieval-first
external interface alongside it.

## §4 Target experience, and citations as available-not-mandatory

Gio opens her own ChatGPT account: *"Look at our accounting firm acquisition project in Neuro. What should we be
most worried about right now?"* ChatGPT retrieves project context — goal, brief, important user facts, constraints,
decisions, approved findings, claims with strength/readiness/freshness, tensions, important sources, evidence
targets, current plan, unresolved questions — and answers normally.

We do **not** want every response to look like *"Source 72 at 14:32 says…"*. The normal experience is
conversational.

**This distinction is critical: never discard provenance; disclose it progressively.** Neuro should always know
where a claim or finding came from, but an external AI does not need to display provenance in every response.

```text
normal answer -> user asks "why?" -> more detail -> user asks "show me" -> precise evidence
```

Design retrieval responses so an AI can *see that deeper evidence exists* without forcing huge evidence payloads
into every call:

```json
{
  "claim": "Customer relationships appear dependent on the current owner.",
  "strength": "strong",
  "evidence_count": 4,
  "evidence_refs": ["..."],
  "evidence_available": true
}
```

The detailed evidence need not be returned until requested. And: do not imply evidence exists when it does not.

## §5 A compact project orientation tool

One of the most important additions is conceptually `get_project_context(project_id, depth="standard")` — exact
naming is a decision to make after inspecting existing MCP/API conventions. The purpose is to let an external AI
understand a project in **one inexpensive call**. Do not make ChatGPT call ten or fifteen tiny tools to discover
what a project is.

A standard response contains a compact structured representation of whatever currently exists:

```text
PROJECT         name · goal · brief · mode · status
USER CONTEXT    facts · constraints · requirements · decisions · rejected options
RESEARCH STATE  important approved findings · important claims · strength · readiness ·
                freshness · tensions · evidence targets · knowledge gaps · open questions
SOURCES         important sources · source summaries · source IDs · source types
PLAN            current objective · current recommendation · major steps · risks ·
                unresolved decisions
```

Do not blindly return everything. Support depth or budget controls (`compact` / `standard` / `deep`, or an
equivalent token/content budget). **The default is optimised for orientation, not exhaustive export.**

## §6 External read interface

After inspecting what already exists, expose a small coherent interface covering:

1. **Projects** — `list_projects()`, only projects this external identity is authorised to access.
2. **Orientation** — `get_project_context(project_id, depth)`.
3. **Project search** — `search_project(project_id, query, filters?)`, the general workhorse. It must leverage
   Neuro's existing hybrid retrieval rather than creating a second search engine. Allow useful filtering if the
   architecture supports it: findings · claims · facts · correspondence · sources · transcripts · documents ·
   specific source · source type · date · topic. Do not overcomplicate the first implementation.
4. **Claims / research state** — `get_claims(project_id, topic?, filters?)`. Reuse the current Claims system rather
   than cloning it for MCP.
5. **Sources** — `get_sources(project_id, query?, type?)`.
6. **Evidence drill-down** — `get_evidence(...)`: given a claim/finding/source/evidence identifier, return excerpt,
   quote, surrounding context, timestamp, page, section, spreadsheet location, URL, source metadata.
7. **Transcript/source content** — retain or extend the existing retrieval where useful.

**Do not export internal chat by default.** Neuro project chats belong to Neuro's own conversational history;
external conversations stay independent. If prior Neuro conversation contains something promoted into a fact,
decision, requirement, approved finding, claim or plan state, that structured information can be used normally.
Raw chat history is opt-in.

## §7 Bidirectional access, and strict information classification

External clients need a safe way to send new information **into** Neuro.

Worked example. Gio receives a seller email: *"We don't think a 10% seller note is appropriate because the company
has grown consistently for five years and we have another interested buyer."* She brings it into ChatGPT and asks
what to think, considering everything in the Neuro acquisition project. ChatGPT retrieves context and answers. Then:
*"Save their email to Neuro and remember that we're holding at 10% seller financing for now."* That is **two
different operations**:

```text
1. Seller email      -> external evidence / correspondence source
2. "We're holding at 10%" -> user decision / fact
```

Do not conflate these. There are at least three classes of incoming information:

**Class A — external evidence.** Seller/broker/lender email, text from an accountant, LOI, CIM, purchase agreement,
P&L, tax return, lease, customer report, PDF, spreadsheet, attachment, web page, counterparty document. These can
become SOURCES and should go through Neuro's normal ingestion, indexing, deduplication, finding-generation and
research pipeline as appropriate.

**Class B — user-authored project state.** *"We won't pay more than $1.8M."* · *"We prefer 10% seller financing."* ·
*"Gio is willing to extend the transition period."* · *"We rejected an earnout."* · *"Our current negotiating
position is 10% seller financing."* · *"We need this acquisition to produce at least X."* These become facts,
decisions, constraints, requirements, rejected options — whichever current Neuro primitives represent them. Reuse
the current data model.

**Class C — AI-generated material.** ChatGPT's theory that the seller is bluffing, AI negotiation strategy, AI
interpretation, AI brainstorming, an AI draft email, AI-generated financial assumptions. **These must not silently
become research evidence, claims, approved findings or user facts.** An AI-generated draft can be saved as an
explicitly labelled draft/note if the user asks. It must remain distinguishable from external evidence. This is a
hard requirement: **AI interpretation cannot become self-validating evidence for Neuro's future reasoning.**

## §8 Project Inbox

Create a lightweight **Project Inbox**: the receiving layer for information sent by external tools. Do not
necessarily create a major new top-level UI tab if that would make Neuro more cluttered — decide the smallest clear
UI after inspecting the current Sources workflow.

```text
External AI -> PROJECT INBOX -> correspondence
                             -> document/source ingestion
                             -> spreadsheet ingestion
                             -> URL ingestion
                             -> project fact/decision
                             -> AI-generated note/draft
```

Inbox records need enough state to make failures and routing understandable: `received · routing · queued ·
processing · ready · needs_review · failed`. **Reuse the existing jobs/status system; do not create a second
generic background-processing system.**

A write from an external AI should return quickly:

```json
{"accepted": true, "inbox_id": "...", "source_id": "...", "job_id": "...", "status": "queued"}
```

Do not make MCP calls block while a PDF is fully analysed.

Expose incoming material inside Neuro so the user can understand what happened. The UX should answer: what came in ·
who sent it · which project it went to · what type Neuro classified it as · whether ingestion succeeded · whether
processing is still running · whether it failed · whether anything needs review. Do not build a complicated email
client; keep it operational and clear, reusing current jobs/source UI patterns.

## §9 Correspondence as a first-class source type

Evaluate a first-class `correspondence` concept for email, message, letter, counterparty communication. Do not
implement it as a brittle special case if the current source model already has a better extensible mechanism.

Metadata it should be able to carry (none required): from · to · cc · date · subject · participants · thread
identifier · external message identifier · attachments · original body · project.

**This unlocks chronology.** A future query — *"How has the seller's position on seller financing changed during
negotiations?"* — should eventually reconstruct:

```text
Sep 2   Buyer requested 10% seller financing.
Sep 4   Broker said seller would discuss structure.
Sep 7   Seller requested cash at closing.
Sep 10  Seller cited another interested buyer.
Sep 10  Kyle/Gio decided to hold at 10%.
```

Design today's storage so that is possible later without rebuilding correspondence. **Do not build a giant CRM.**

## §10 File ingestion from external clients

Target: *"Add these four files to the accounting firm project and tell me whether anything changes your view."*
PDF · XLSX · CSV · DOCX · TXT · images/screenshots · anything else already supported.

Use the existing ingestion pipeline. **Do not duplicate PDF parsing, spreadsheet handling, chunking, embeddings or
job logic inside the external connector.** The external interface is an entry point into the same pipeline.

Because MCP clients differ in how they support binary/file inputs: inspect the current FastMCP version and
capabilities; determine the cleanest supported file transport; keep the underlying REST/API ingestion path usable
independently of MCP; if direct MCP file transfer is not reliably available, provide a clean upload endpoint or
another protocol-neutral mechanism rather than embedding giant base64 blobs everywhere; and do not design the entire
Neuro data layer around one ChatGPT implementation quirk.

```text
wanted:  External client -> thin adapter -> normal Neuro ingestion
not:     External client -> special ingestion architecture
```

## §11 Multi-person access, permissions, security

Neuro historically used one shared application token. That is not sufficient for sharing with another person's
ChatGPT account. We need lightweight external identities and project-specific authorisation — **not** full SaaS
multi-tenancy:

```text
Kyle external credential      Project A/B/C   read/write
Gio external credential       Business Acquisition   read + contribute
                              House Project          read + contribute
                              Neuro Development      no access
                              Career Project         no access
```

**The critical requirement: possession of an external credential must not automatically expose every project.**

Granular scopes without going overboard. An initial model might be `project:read` · `project:search` ·
`source:read` · `source:add` · `fact:add` · `note:add`, potentially with `project:admin` · `source:delete` ·
`research:approve` for owners only. Gio's normal external access should support reading shared projects, searching
them, retrieving evidence, adding incoming sources, adding correspondence and recording explicit user
decisions/facts — but **not** deleting sources or projects, changing budgets or system settings, approving AI
findings, modifying access control or administering Neuro.

Security, because this could eventually be exposed outside the LAN: separate external credentials · project ACL
enforcement on every external operation · revocable credentials · credentials stored securely, preferably hashed ·
plaintext only when necessary · never expose the primary application secret unnecessarily · never allow an
unauthorised project ID to bypass list filtering · validate authorisation server-side · protect against IDOR ·
sanitise filenames · prevent path traversal · validate file sizes · validate file types reasonably · no arbitrary
filesystem paths from an MCP caller · no secrets or giant document bodies in logs · preserve current cookie/security
rules · keep destructive/admin operations out of ordinary shared credentials.

Do not break the current local workflow. A new endpoint/middleware for better external auth while retaining legacy
local auth is acceptable. Prefer Authorization/Bearer-style credentials over secrets in URLs where the current
libraries and clients permit — inspect actual client/FastMCP support rather than guessing.

**Access management UI.** The smallest clear UI for Kyle to manage external access, probably under Settings or
Project Settings: identity name, shared project count, permissions, last used, Revoke/Rotate. Creating access
should allow naming the identity/client, choosing projects, choosing a sensible preset, generating the credential,
showing connection information, and revoking later. Presets: **Read Only · Read + Contribute · Owner.** Do not
present twenty checkboxes without a compelling reason.

**Auditability.** Lightweight, for external writes and meaningful access events: who did what to which project
when — e.g. *"Gio / ChatGPT · added correspondence · Business Acquisition · 2026-09-10 10:14"*. Prefer metadata; do
not log complete sensitive document contents merely for auditing.

**Idempotency and duplication.** External clients retry. A network retry must not create five copies of the same
seller email or PDF. Support `client_request_id` · `external_message_id` · file hash · content hash as appropriate,
integrating with Neuro's current deduplication rather than replacing it. If the same seller email arrives twice by
two paths, Neuro should have a reasonable chance of recognising it.

## §12 External write tools

Names are flexible; functionality should conceptually include:

```text
add_project_material(project_id, material_type, content, title?, source?, metadata?, client_request_id?)
```

with `material_type` mapping to `correspondence · external_evidence · user_fact · user_decision · user_constraint ·
ai_note · ai_draft · url`. Do not use arbitrary uncontrolled strings if a clear typed model makes more sense.

Plus `add_project_file(...)` using the transport the actual stack supports, and reuse of the existing fact/decision
system for project state — do not create duplicate "external facts" if `project_facts` or its successor already
solves the problem.

**Tool descriptions matter**, because the external model must use the interface correctly without Neuro controlling
its system prompt. Conceptually:

> `search_project` — Retrieve project knowledge for the external assistant to reason over. Neuro provides research
> and provenance, not a prewritten conversational answer. Do not display citations by default unless the user
> requests sources or verification, but do not imply evidence exists when it does not.

> `add_project_material` — Add user-supplied or externally supplied material to a Neuro project. Classify
> counterparty documents and correspondence as external evidence. User-stated decisions/constraints should be
> recorded as project state. AI-generated interpretations or drafts must not be submitted as evidence.

## §13 Acceptance scenarios (release blockers)

**Negotiation, end to end.** Gio has access to `Accounting Firm Acquisition` and is using her own ChatGPT account.
She pastes the seller email and asks where they are right, where they are applying pressure, and how to respond. An
external AI must: find the correct authorised project · retrieve project context · search relevant acquisition
research · retrieve relevant findings/claims/facts as needed · independently reason about the seller's argument ·
answer conversationally without mandatory citations. Then *"Draft a response"* — ChatGPT does that independently.
Then *"Save their email to Neuro and record that we're holding at 10% seller financing for now."* The integration
must: store the email as external correspondence/evidence · preserve sender/date/subject metadata if supplied ·
queue it through the appropriate pipeline · separately record "hold at 10%" as a user decision/fact · **not** treat
ChatGPT's analysis as evidence · **not** treat the draft email as evidence · return useful IDs/statuses · avoid
duplicates if retried.

**Documents, end to end.** `2025 P&L.pdf` · `2024 Tax Return.pdf` · `Customer Revenue Breakdown.xlsx` ·
`Draft LOI.pdf`, added by an external AI, must flow into the existing document pipeline, spreadsheet pipeline, jobs,
indexing and findings/research process — no parallel parsing implementation. Afterwards an external AI can query
that new information. If processing is asynchronous, **clearly return that state instead of pretending analysis is
complete.**

## §14 Cost, processing, and layering rules

External ingestion must respect the same processing architecture as ordinary ingestion. It must not bypass budget
controls · queue controls · current Claude Code/API routing · processing modes · bulk behaviour · deduplication ·
existing analysis settings. If an incoming file would normally trigger findings, claims, extraction or embeddings,
use the same configured behaviour. **Do not introduce new mandatory LLM calls merely because a source arrived
through ChatGPT.**

The capability must exist **below** the MCP layer:

```text
Core Neuro service functions -> REST/API -> MCP adapter
```

Do not make important functionality exist only inside `mcp_server.py`. This protects against changes in ChatGPT,
Claude, MCP or future clients. The goal is a general **Neuro Project Intelligence Interface**; MCP is one transport.

**Performance.** External orientation should feel fast. Do not run a model just to assemble
`get_project_context()` — it primarily aggregates already-computed state. `search_project()` uses existing
indexes/retrieval. Large project responses need sensible caps: avoid dumping hundreds of findings or a
100,000-word transcript when ten relevant results will do, and let the AI drill deeper.

**Failure behaviour.** Never pretend a write succeeded when it merely queued. Never pretend a queued source is fully
analysed. Never return inaccessible information because an internal helper forgot an ACL check. Make states
explicit: `accepted · queued · processing · ready · failed · needs_review`, using current Neuro terminology where
possible.

**Backward compatibility.** Do not break the existing UI · internal chat · existing Claude MCP workflows ·
ingestion · current tokens (unless migration is intentional and safe) · CLI · browser extension · existing
project/source IDs · the existing database · current research processing. If old MCP tools remain useful, leave them
working; if they should be deprecated, do so deliberately and document the replacement.

**Database.** Additive migrations only. Before creating new tables, determine whether current tables can safely
carry the new concepts. Likely new concepts *may* include equivalents of `external_clients` ·
`external_project_permissions` · `project_inbox` · `external_audit_log` — examples, not mandatory names. Avoid schema
proliferation. Use JSON metadata thoughtfully for correspondence and evolving integrations, without hiding the
entire domain model inside JSON and sacrificing queryability.

**Observability.** External integration errors must be understandable: external client · project · operation ·
request ID · result · job/source/inbox ID · error category. Do not log credentials. Do not log entire private
emails/documents unless already part of intentional, adequately protected debug behaviour.

**Product language.** Feature name: **External AI Access**. Receiving concept: **Project Inbox**. Permission
presets: Read Only · Read + Contribute · Owner. Do not expose internal MCP jargon unnecessarily in the main UX;
technical connection instructions can mention MCP/API.

## §15 Testing

Meaningful automated tests, no paid API calls, using the existing fake-model mechanisms.

*Authorisation* — Kyle's credential sees authorised projects; Gio's sees only shared projects; Gio cannot access a
private project by guessing its ID; a read-only token cannot write; a revoked credential stops working; existing
primary/local authentication remains valid.

*Retrieval* — `list_projects` is permission scoped; project context is compact and structured; project context does
not dump raw chat by default; project search remains project scoped; evidence can be drilled into; source provenance
remains available; normal retrieval does not require generating an AI answer.

*Writes* — correspondence can be added; its metadata persists; a user decision routes to facts/decisions; an AI
draft routes to a non-evidence note/draft; AI-generated material never silently becomes approved evidence; file
ingestion uses the existing pipeline; a write returns queued/processing status correctly; failed ingestion is
visible; retry/idempotency does not duplicate material.

*Files/security* — an unsupported file is rejected cleanly; an excessive file is handled safely; path traversal is
blocked; an unauthorised upload is blocked.

*Regression* — run the entire existing suite.

## §16 Non-goals

Do **not**: rebuild Neuro's internal chat · route external AI calls through `qa.ask()` by default · automatically
synchronise ChatGPT conversation history into Neuro · require citations in every external response · remove
provenance · treat AI interpretation as evidence · give every external client access to every project · build full
SaaS multi-tenancy · build an email client · reimplement ingestion · add a second job queue · introduce paid model
calls just to make the integration work · depend on one current ChatGPT implementation detail · throw away existing
MCP functionality · modify the SQLite database directly from another process.

## §17 Architectural north star

```text
                       NEURO SEARCH
                            |
               Project Intelligence Layer
                            |
       +--------------------+--------------------+
       | READ               | WRITE              | MANAGEMENT
 list projects        add correspondence     credentials
 project context      add documents          permissions
 search project       add URLs               audit
 claims/findings      record decisions       revocation
 sources              add notes
 evidence
 transcripts
       +--------------------+--------------------+
                            |
                   API / MCP adapters
                            |
          +-----------------+-----------------+
      ChatGPT            Claude          Future AI
          |                 |
      Kyle chats         Gio chats
          +------- shared Neuro --------+
                   project knowledge
```

## §18 Implementation approach and deliverables

Before coding: inspect the current implementation · identify reusable components · identify the minimum
schema/API/MCP/UI additions · identify security boundaries · **identify any assumptions in this brief that are
outdated because the repo has moved forward** · produce a concise Mission + Ladder · then implement it. Do not stop
after producing the plan unless there is a genuine blocker that cannot be resolved from the repository. Work through
the ladder autonomously, in small coherent releases matching the existing release discipline. At each checkpoint:
run relevant tests, run full tests when appropriate, fix regressions before continuing, keep the tree coherent,
update documentation, update version numbers per the current ritual. **Do not claim something works merely because
code exists. Verify it.**

Deliverables: working functionality (not just architecture documentation) · the read interface · the bidirectional
write interface · separate external identities · the Project Inbox · provenance separation · optional evidence
disclosure · tests · documentation (what External AI Access is, how to create/revoke access, permissions, available
MCP/API capabilities, how external evidence is handled, how AI-generated content is handled, how file ingestion
works, current client limitations, how to connect ChatGPT/Claude where supported) · and a final plain-English
implementation report covering what changed, what new user flows work, the security model, data/schema changes, MCP
tools added/changed, API endpoints added/changed, UI changes, tests added, test results, caveats, anything deferred,
and what remains dependent on external ChatGPT/Claude platform capabilities.

**Success looks like this.** Gio, in her own ChatGPT: *"The seller sent me this email and two PDFs. What do you
think?"* → ChatGPT consults the shared Neuro acquisition project and interprets their position → *"What supports
that?"* → it retrieves evidence → *"Draft a response"* → it drafts independently → *"Good. Save their email and PDFs
to Neuro. Also remember we're still holding at 10% seller financing."* → *"Seller correspondence accepted. 2
documents queued for Neuro ingestion. Negotiating position recorded. AI analysis/draft not added as evidence."*
Meanwhile Kyle queries the same project from a completely different conversation in his own ChatGPT account.
Neither person shares ChatGPT history. Neither uses Neuro's internal chat behaviour. Both use Neuro as the
persistent research and project intelligence layer.

---

## §19 Repository notes as of 0.62.5 — what already exists, and what in the brief is already outdated

Filed at the same time as the brief, by the session that had just been working in this code, because §2 and §18 both
ask for it and it is cheapest to write while it is known. **This section is observation, not design.** Nothing here
has been built for this mission.

**Already exists and should be extended, not recreated:**

- `mcp_server.py` already exposes 17 tools over FastMCP: `search_knowledge`, `ask`, `list_projects`,
  `create_project`, `add_to_project`, `list_sources`, `list_collections`, `get_transcript`, `ingest`, `job_status`,
  `findings`, `masterplan`, `build_master_plan`, `get_master_plan`, `record_fact`, `update_brief`, `save_note`. So
  `list_projects`, source listing, transcript retrieval, URL ingestion, job status, findings and fact recording all
  exist in some form — the mission's read interface is substantially a *reshaping* of these plus ACLs, not a new
  surface.
- `record_fact(project, kind, content)` and `save_note` already cover much of Class B and the labelled-draft case.
  §12's warning against duplicate "external facts" applies directly: `project_facts` exists.
- Retrieval is `search.search` (FTS + embeddings + RRF) with `library.recall` for cross-project material and
  `candidates.seen_for_query` (0.62.5) for seen-but-unread sources. §6's "leverage existing hybrid retrieval" means
  these, and nothing else should be built.
- Claims, evidence, strength/readiness/freshness, tensions and evidence targets exist (`claims.py`,
  `knowledge.py`), with `claims_view.query` already producing plain-language one-liners and `claims_view.for_source`
  already answering "why this answer" — which is close to §4's progressive disclosure.
- `research_view.overview(full=1)` is the closest thing to `get_project_context` today. **Warning for whoever
  builds it:** it ships **5.7 MB** on Kyle's large project and `/api/projects/{id}` shipped 8 MB of findings before
  0.60.1 bounded it. §14's caps are not theoretical.
- Ingestion for PDF/XLSX/CSV/DOCX/TXT/EPUB already exists (`documents.py`, `sheets.py`, `ingest.py`) behind
  `POST /api/ingest/file` with an `immediate=true` path, and `resources.classify`/`route` is the single classifier
  every new input kind must extend rather than bypass.
- The jobs table, lanes (`priority < normal/slow < low`), dedupe keys, dependency policies and derived statuses
  already provide every state §8 lists. `dedupe_key` is the idempotency mechanism §11 asks for.

**Outdated or contradicted by the current repo:**

- **Auth is a single shared token** (`NEUROSEARCH_APP_TOKEN`), checked by `api.require_auth`, with
  `TokenPathMiddleware` accepting either `/mcp/<token>` in the path or a Bearer header. The brief's §11 is therefore
  the largest genuinely new piece of work, and the path-token form is exactly the "secret in the URL" §11 wants to
  move away from — but it is also what current MCP clients use, so it cannot simply be removed.
- **There is no ACL layer of any kind.** Every tool above is all-or-nothing. `_resolve_project` resolves a project
  by name or id with no permission check, so every read tool is an IDOR by construction the moment a second identity
  exists. This is the security boundary to design first.
- **`ask()` exists and is an MCP tool**, so an external client can already route through Neuro's QA — §3's
  preference has to be expressed in tool descriptions and defaults rather than by removing it.
- **Cost controls the brief must not bypass are stricter than it assumes**, and three of them changed today:
  spend is now dated when incurred rather than when learned about (0.62.3), the rate ceiling ignores late bookings,
  and `usage.reconcile` reports mixed accounting bases. Anything external that queues paid work inherits all of it.
- **"Do not run a model just to assemble project context" is now enforced by precedent, not just preference.**
  `claims.ensure` in a request path cost 431 s on Kyle's project (0.62.2); the steering path is
  `claims.ensure_cheap`, which reads existing state and queues the refresh. `get_project_context` must use that
  shape.

**Open questions this brief does not settle**, for whoever starts it:

1. Whether an external identity is a row in a new `external_clients` table or a scoped variant of the existing
   token, given that the desktop UI, CLI and extension all authenticate with the same secret today.
2. Whether `correspondence` is a new `platform`/`content_type` on `sources` or a sibling table — the source model
   already carries `platform`, `channel`, locators and `completeness`, and §9 explicitly warns against a brittle
   special case in either direction.
3. Whether the Project Inbox is a new table or a view over `jobs` + `sources` + a `received_via` column. §8 says
   reuse the job system; the states it lists map almost exactly onto existing derived job statuses.
4. What FastMCP version is pinned and what it supports for binary transport — §10 requires this be inspected, not
   assumed, and it is the one item that cannot be answered from the repository alone.

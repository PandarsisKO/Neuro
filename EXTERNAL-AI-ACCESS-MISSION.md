> **STATUS (2026-09-22): P11 — ACTIVE / FINAL READINESS — execution begins only after Kyle explicitly accepts the execution plan.** Kyle's directive of 2026-09-22 supersedes every earlier
> status line in this file ("PARKED", "FILED, NOT STARTED", §38's "P11 remains PARKED", §66–§67's "does not admit"): those were
> true when written and are kept as history. The Frozen Architecture (§38–§67) is ACCEPTED and is not to be redrafted.
> The execution plan is `docs/P11-EXECUTION-PLAN-2026-09-22.md`. **Update, same day: Kyle authorised execution; EA-0…EA-8 are
> built (HANDOFF 2026-09-22 "EA-0 → EA-8"), EA-9 is gated on transport and account steps.** P11 joins the NOW queue
> without replacing or rewriting other admitted work.

# MISSION — External AI Access + Bidirectional Project Intelligence

**AMENDED 2026-09-11 — see §20–§37.** Kyle dictated an amendment while the fix queue was running: *"I have an
amendment to a future mission… Do NOT create a separate mission for these changes. Update the existing
`EXTERNAL-AI-ACCESS-MISSION.md` so these requirements become part of the same mission. Where this amendment
conflicts with wording in the original mission, this amendment takes precedence."* It is therefore part of THIS
mission, not a second one, and **§20–§37 override §1–§19 wherever they disagree.** The passages it supersedes are
marked in place with a pointer, so a future session cannot read the old rule without meeting the new one. Nothing
here is implemented and nothing is scheduled.

**Status (historical, 2026-09-10): FILED, NOT STARTED** — superseded 2026-09-22 by the banner at the top of this file. Kyle dictated this on 2026-09-10 while a fix queue was in progress and said
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

> **AMENDED (§20, §26–§29).** "Not `ask()`" must not be read as "raw retrieval only". Neuro has accumulated
> higher-order intelligence — findings, claims, tensions, decisions, relationships, evidence strength, open
> questions — and a substantive turn should get it. What external clients must not receive is Neuro's **verbose
> native chat response**. The addition is a compact project-intelligence packet (§27), not a conversational
> answer: ChatGPT owns the final reasoning, Neuro contributes what the project knows.

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

> **AMENDED (§22–§24).** Class A may arrive by **either** of two paths: raw material for Neuro's own extraction
> (Path A), or an **already-processed package** from an external AI that has read the image, parsed the PDF or
> opened the URL (Path B). Both feed the same knowledge system. And Class A splits into two layers that must not
> be collapsed: the **source** (evidence) and the **extraction** (an AI representation of what is visibly present
> in it). Class C stays exactly as written — interpretation is never evidence.

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

> **AMENDED (§22–§26, §31).** The rule is about the KNOWLEDGE ARCHITECTURE, not about who extracts. Precisely:
> *do not create a second persistent ingestion/indexing architecture, but do allow an external AI to perform
> upstream extraction that Neuro reuses.* **One Neuro knowledge architecture, several extraction producers.** So
> Neuro must not re-OCR a screenshot ChatGPT has already read, or pay a model to reread a PDF ChatGPT has already
> parsed, merely because Neuro is the thing that stores it. Chunking, embeddings, dedupe, findings, claims and the
> job queue stay exactly where they are.

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

> **AMENDED (§28–§31, §34).** Two additions. (a) A write does **not** require the user to say *"save this"*: a
> clearly durable decision, constraint, position or rejected option made inside a Neuro-connected project
> conversation is eligible for automatic synchronisation, while indiscriminate transcript storage stays forbidden
> (§30 lists what counts and what does not). (b) `add_processed_material` (§25) joins `add_project_material` as
> the entry point for externally extracted packages.

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

> **AMENDED (§32).** The ladder gains a rung ABOVE everything else: *has the external AI already processed this?*
> If so, reuse that work rather than re-extracting. **Avoid paying twice for cognition that has already
> happened.** The rest of the ladder — free local tooling, then Claude Code, then the paid API — is unchanged.

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

---

# AMENDMENT — 2026-09-11 (§20–§37)

Kyle: *"The original External AI Access mission remains valid, but several important behaviors need to be clarified
and expanded before implementation begins."* These sections are part of this mission and **take precedence over
§1–§19 wherever they conflict**. The core correction in one sentence:

> External AI clients such as ChatGPT are **not** thin transport into Neuro, and **not** independent chatbots that
> occasionally search it. **ChatGPT owns the live conversation and the immediate reasoning; Neuro owns durable
> project intelligence and persistent memory; both exchange useful information during substantive project work.**
> And ChatGPT may process attachments itself before passing structured results to Neuro, so nothing is extracted
> twice.

## §20 Updated north star

```text
                        NEURO SEARCH
                             ^
                             |
                    durable project memory
                             |
         evidence / decisions / context / relationships
                             |
                             v
USER <-----------------> CHATGPT
                              ^
                              |
                     concise Neuro intelligence
                     when substantive project
                     reasoning requires it
```

**ChatGPT owns:** the live conversation · immediate reasoning · interpreting newly attached material · vision ·
document understanding · writing · tone · rewriting · presentation · conversational follow-ups.

**Neuro owns:** durable project memory · research state · sources · evidence · findings · claims · relationships ·
project facts · constraints · requirements · decisions · rejected options · counterpart positions · historical
project context · persistent chronology.

The experience should feel like **ChatGPT that understands and remembers the entire Neuro project** — not like
Neuro's native research chat reproduced inside ChatGPT.

## §21 ChatGPT may process material before Neuro

When ChatGPT has already viewed an image · read a screenshot · parsed a PDF · opened a URL · read an email ·
inspected a table · interpreted a document · extracted text · identified metadata · recognised entities ·
understood document structure — **reuse that work.** Do not force Neuro to repeat expensive or difficult extraction
merely because Neuro is what ultimately stores the material.

```text
wanted:                             not:
User material                       User material
    |                                   |
    v                               ChatGPT processes it
ChatGPT processes it                    |
    |                               sends original to Neuro
    v                                   |
structured extraction               Neuro OCRs/parses it again
    |                                   |
    v                               another model rereads it
Neuro persists / indexes / relates
```

**One Neuro knowledge architecture; several extraction producers.**

## §22 Two ingestion paths, both supported

**Path A — raw Neuro ingestion.** `Raw source → Neuro extraction → Neuro knowledge system.` Use when Neuro receives
material directly · external extraction is unavailable · verification is required · the source needs special Neuro
processing · bulk processing is appropriate · the external client cannot inspect the content.

**Path B — externally processed ingestion.** `Raw source → external AI → structured extraction → Neuro knowledge
system.` Use when the external AI has already done useful processing.

**Do not remove Neuro's existing ingestion pipeline.** This amendment adds a producer of normalised source
information; it replaces nothing.

## §23 Source, extraction, interpretation — three layers, never collapsed

```text
ORIGINAL MATERIAL  ->  EXTERNAL EXTRACTION  ->  EXTERNAL INTERPRETATION
```

**Original material** — seller email · screenshot · PDF · contract · spreadsheet · URL · financial statement ·
broker message · tax return. **This is evidence.**

**External extraction** — visible text from a screenshot · email sender · date · PDF page text · headings · tables ·
explicit amounts · names · dates · document structure · explicit seller positions · stated objections · contractual
terms. **An AI representation of what is visibly or explicitly present in the source.** Neuro may use it to
construct the normalised source representation.

**External interpretation** — *"The seller is probably bluffing." · "This clause is unusually aggressive." · "They
seem nervous about retention." · "This expense probably isn't sustainable."* **Analytical judgments. These must NOT
silently become factual evidence.** They may be retained as AI analysis · hypotheses · candidate findings ·
candidate relationships · suggested interpretations — always distinguishable from the source.

## §24 Processed source packages

Extend the external write interface so ChatGPT can submit structured processed material rather than only raw files.
Conceptually — **use naming consistent with the live repo**:

```text
add_processed_material(
    project_id, source_type, original_metadata, extracted_content,
    structured_data?, provenance?, candidate_findings?, candidate_relationships?,
    interpretations?, original_artifact?, client_request_id?
)
```

A package may carry:

- **Source identity** — title · source type · URL · author · sender · recipients · date · filename · MIME type ·
  external message id · thread id.
- **Extracted content** — full readable text · page boundaries · screenshot text · sections · headings · tables ·
  message body · spreadsheet values.
- **Structured information** — people · companies · amounts · dates · topics · deadlines · explicit positions ·
  objections · offers · counteroffers · commitments · referenced documents.
- **Provenance** — page · section · URL · source attachment · timestamp · screenshot region where practical ·
  message metadata.
- **Optional candidate intelligence** — candidate findings · relationships · tensions · hypotheses · uncertainties.

**Do not require every field.** Design it as an extensible representation.

## §25 Retain original artifacts when practical

The ideal pattern is `original artifact + external extraction + structured metadata + candidate semantic
information` — e.g. `seller-email.png` + extracted body + sender/date/subject + identified positions, or `CIM.pdf` +
page-bounded text + tables + entities. That gives Neuro immediate usable intelligence, durable original evidence,
and the future ability to reprocess with better tools.

**But inability to transfer the original binary must never prevent Neuro from accepting useful structured
extraction** — external clients differ in file transport.

**Screenshots / images (§26a).** External vision may be better than Neuro's local pipeline. Accept visible text ·
document type · sender/recipient · names · dates · amounts · tables · visual structure · source context · candidate
findings · explicit statements. **Do not re-OCR an image just to recreate what ChatGPT already extracted.** Store
the image as the artifact when possible.

**PDFs (§26b).** Accept filename · title · page count · page-bounded text · headings · tables · metadata ·
entities · explicit facts · candidate findings, and create a normal searchable source **without paying another
model to reread the whole PDF**. Preserve page provenance. Retain the original when transferable.

**URLs (§26c).** Accept canonical URL · title · author · publication date · normalised text · headings · structured
data · extracted facts · candidate findings. **Do not automatically refetch** merely because URL ingestion
historically worked that way. Refetch only when useful: extraction incomplete · verification requested · freshness
matters · the source may have changed · richer metadata needed · archival capture wanted. This is especially
valuable for sites that block Neuro but not the external AI.

**Email / correspondence (§26d).** Accept sender · recipients · date · subject · thread context · body ·
attachments · explicit claims · questions · objections · offers · counteroffers · commitments · deadlines ·
amounts · people/companies · candidate relationships. The evidence is **what the counterparty actually said**:

```text
Seller statement: "We have another interested buyer."   -> Evidence: seller assertion.
ChatGPT: "The seller is bluffing."                      -> NOT evidence.
```

**Spreadsheets (§26e).** Preserve Neuro's existing spreadsheet/formula capabilities. Extracted values, trends,
table structure, anomalies and key rows may be passed as extraction — but when Neuro needs the workbook for formula
evaluation · calculator features · editable inputs · formula inspection · workbook structure, use a hybrid approach
and process the workbook normally as well.

## §26 Neuro builds the durable relationships

External preprocessing exists to free Neuro for what only Neuro provides: **persistent relationships across time,
sources, research, decisions and project state.**

```text
New financial statement      -> SUPPORTS      -> existing growth claim
Seller email                 -> CONFLICTS WITH -> buyer financing preference
New seller position          -> SUPERSEDES    -> earlier seller position
Financial concentration data -> SUPPORTS      -> existing customer-retention risk
```

External AI may *suggest* these. **Neuro owns the persistent version.**

## §27 The Neuro intelligence packet

Expose something conceptually equivalent to `consult_project(project_id, question, new_material_context?,
mode="concise")` — **exact implementation follows the live architecture.** The purpose is a compact project
intelligence packet, not a long conversational answer:

```text
CURRENT PROJECT POSITION   - Buyer prefers 10% seller financing.
WHAT MATTERS               - Seller financing is intended to align transition risk.
                           - Customer retention remains a known concern.
                           - Updated numbers support historical growth.
                           - No independent evidence confirms another buyer.
WHAT CHANGED               - New financials strengthen the historical-performance argument.
                           - They do not eliminate transition risk.
TENSIONS                   - Seller explicitly opposes the 10% note.
                           - Buyer preference now conflicts with seller position.
                           - Competitive-buyer claim is unverified.
NEURO ASSESSMENT           - Do not abandon the 10% request solely because the business performs well.
                           - Reframe the request around transition alignment.
EVIDENCE STATE             - Historical growth: strongly supported.
                           - Competing buyer: seller assertion only.
                           - Transition risk: supported.
SOURCE REFERENCES          - available if requested
```

ChatGPT uses the packet as **one input** into its own response. It must not print it.

## §28 External responses are far less verbose than native chat

Native Neuro chat may carry detailed citations · timestamps · source links · long evidence explanations · research
caveats · explicit gap analysis. That is right inside Neuro and **too heavy for ordinary ChatGPT conversation.**

External advisory mode defaults to: concise · decision-oriented · project-aware · low repetition · no giant source
lists · no inline transcript timestamps · no explicit source linking unless needed · no methodology unless
relevant. Roughly **200–700 useful tokens** rather than a research report — **not a hard limit** where the situation
genuinely requires more.

**Citations are progressive.** Neuro always preserves provenance; ChatGPT need not surface it constantly. *"The
updated financials strengthen the seller's case that the business is healthy, but they don't eliminate your
transition-risk rationale for the note."* → *"Why?"* explain → *"What evidence supports that?"* retrieve deeper →
*"Show me the sources."* then names · excerpts · URLs · pages · timestamps · precise evidence relationships.

**ChatGPT synthesises** `NEW MATERIAL + USER QUESTION + CHAT HISTORY + NEURO INTELLIGENCE + ITS OWN REASONING`. The
answer should read like ChatGPT, not like a packet.

## §29 Read and write are separate decisions

For every turn, two independent questions:

```text
1. DOES CHATGPT NEED NEW INFORMATION FROM NEURO?
2. DID THIS TURN CREATE DURABLE PROJECT INFORMATION NEURO SHOULD REMEMBER?
```

The answers frequently differ.

| turn | classification | read | write |
|---|---|---|---|
| *"Does this new PDF change our seller-note position?"* | new evidence · substantive reasoning · project context | **yes** | **yes** |
| *"Agreed. We'll stay at 10%."* | user decision | usually no | **yes** |
| *"Turn that into a polite email I can send the seller."* | presentation / transformation | no | usually no |
| *"Make the email shorter and a little warmer."* | presentation | no | no |
| *"Actually, change the offer to 7.5%. I'm willing to compromise."* | presentation + **new decision** | probably no | **yes** (10% → 7.5%, reason: willing to compromise) |
| *"How does that compare with what the broker said last week?"* | historical project question | **yes** | interaction context at most |
| *"Did our research say seller notes are common for businesses like this?"* | research question | **yes** | usually no |

**Local continuation rule.** After a Neuro-informed substantive turn, ChatGPT continues locally while the context
remains in the conversation. These should generally NOT trigger another retrieval: draft the email · rewrite it ·
shorten it · make it friendlier · make it firmer · turn it into a text message · into call talking points · explain
it simply · translate it · five broker questions · make paragraph two less aggressive. **Do not repeatedly retrieve
the same project knowledge.**

**Consult again when substantive reasoning changes:** *"Does this new document change your recommendation?" · "What
did the seller say before?" · "How does this compare to our research?" · "What risks are we still missing?" · "What
happens if we offer 5% instead?" · "Does the tax return support their claim?" · "What did we decide last week?" ·
"What evidence supports that?"*

## §30 What flows back — and what must not

**The user's question itself may create project context.** *"Does this change how we should approach the seller
note?"* reveals the current concern (financing negotiation), the decision under consideration (whether to change the
request) and the project stage (active counterparty negotiation).

**User responses must flow back. This is a hard requirement.** If ChatGPT recommends holding at 10% and Gio says
*"That makes sense. Let's stay at 10% but explain that it's about making sure the transition goes well, not because
we think the company is weak"* — Neuro should receive:

```text
DECISION          Maintain 10% seller financing request.
RATIONALE         Transition alignment / successful handoff.
REJECTED FRAMING  Do not present seller financing as concern about company quality.
```

**without Gio having to say "save that to Neuro".**

```text
wanted:  conversation -> durable-state extraction -> Neuro
not:     conversation -> save every message forever
```

**Durable:** decisions · changed decisions · constraints · requirements · negotiating positions · rejected options ·
user-provided facts · counterpart positions · unresolved questions · active concerns · commitments · deadlines ·
important rationale · project-relevant preferences.

**Not project memory by default:** *"Thanks" · "Make that shorter" · "Use a warmer tone" · "Try again" · "Change the
first paragraph" · "Make it sound less corporate" · "Give me three options."* Those are presentation instructions.

**AI analysis may be retained, never as evidence.** ChatGPT's *"the stronger financials change the framing but not
necessarily the structure"* may be stored as `EXTERNAL ASSISTANT ANALYSIS` with its provenance intact. It must not
become a factual source claim because ChatGPT said it.

**User acceptance promotes a recommendation into a decision.** ChatGPT: *"I recommend holding at 10% but changing
the rationale."* → Gio: *"Agreed. Let's do that."* → Neuro records a USER DECISION with that rationale. **The user
should not have to restate the recommendation — conversation semantics matter.**

## §31 Worked multi-format scenario (the acceptance shape)

Gio sends `[seller-email.png]` `[Updated-Financials.pdf]` with *"The seller sent these. Does this change how we
should handle the 10% seller note?"*

1. **ChatGPT processes both attachments.** PNG → visible text, seller identity, seller position, objection to 10%,
   competitive-buyer statement. PDF → page text, figures, tables, trends, page provenance. Two independent
   potential Neuro sources.
2. **ChatGPT consults Neuro** with the question plus concise structured context from the new material — enough for
   Neuro to understand what changed. Neuro returns the §27 packet.
3. **ChatGPT answers naturally**, no citation dump: *"The new financials strengthen the seller's argument that the
   business has performed well, so I'd stop framing the note around protecting yourself from weak performance. But
   I wouldn't abandon the 10% request yet… the 'other interested buyer' comment adds pressure, but nothing
   independently verifies it, so I wouldn't negotiate against yourselves on it alone."*
4. **The turn feeds back:** two sources under one intake event (correspondence · financial document, each with its
   external extraction and the artifact retained when available), plus interaction context — active issue, seller
   position, seller rationale, buyer question, `AI ANALYSIS`, and *no final buyer decision yet*.
5. **Gio decides** → `USER DECISION` + rationale + rejected framing (§30). No new read needed.
6. **Gio asks for the email** → entirely inside ChatGPT. No Neuro query, no research, no source retrieval, no
   project-context rebuild.

**Neuro ends up knowing:** the new correspondence and financial document · the seller's objection and stated
rationale · the extracted financial information · the active negotiation issue · Gio's decision and rationale · the
relationship to previous project state. **Neuro does not misclassify** ChatGPT speculation · draft language · tone
preferences · rewrite requests as factual project evidence.

## §32 Cost routing

```text
Has ChatGPT already processed it? --yes--> reuse that work
                 | no
Can local/free Neuro tooling do it? --yes--> use local
                 | no
Can Claude Code do it cheaply? --yes--> use Claude Code
                 | no
                 v  paid API fallback
```

Do not implement this ladder rigidly if the live architecture already has a better routing mechanism. The principle
is what binds: **avoid paying twice for cognition that has already happened.**

## §33 External processing is not external truth

External extraction is useful; external reasoning is fallible. Preserve confidence and provenance boundaries:

```text
SOURCE                  Seller email
EXPLICIT STATEMENT      "We have another interested buyer."
EXTRACTION CONFIDENCE   High
NEURO STATUS            Seller assertion, independently unverified
CHATGPT INTERPRETATION  May be negotiation pressure
INTERPRETATION STATUS   AI hypothesis
```

**Never collapse that into** `FACT: Seller definitely has another buyer.`

## §34 Wording in §1–§19 that this amendment replaces

Each of these is annotated in place, at the passage itself:

| where | old reading | replaced by |
|---|---|---|
| §3 | ChatGPT independently reasons over raw Neuro retrieval | ChatGPT owns the final conversation and reasoning, **and** Neuro may provide concise higher-order project intelligence on substantive turns (§27) |
| §7 Class A | external AI just sends material into the existing ingestion pipeline | external AI is another extraction/understanding layer feeding the same persistent knowledge system (§21–§24) |
| §10 | "do not recreate parsing" | do not create a second persistent ingestion/indexing architecture, **but** allow external upstream extraction that Neuro reuses (§21) |
| §12 | writes happen when the user says "save this" | externally connected project conversations may automatically synchronise clearly durable decisions, facts, constraints, concerns and state, while avoiding indiscriminate transcript storage (§30) |
| §14 | cost ladder starts at local tooling | the ladder starts one rung higher: has the external AI already done this work? (§32) |

## §35 Questions for the implementation session to resolve from the live repo

**Inspect what exists before inventing anything parallel.** Determine: how to represent externally processed
normalised sources · whether processed material needs a new provenance field or existing metadata suffices · how
external assistant analysis is stored without contaminating evidence · whether external interaction state needs its
own table or can extend facts/notes/project context · how to detect durable user decisions without saving every
message · how to decide read / write / both / neither · how to generate the compact advisory packet efficiently ·
whether the existing findings/claims/research system can produce it **without paid inference** · when additional
inference is justified · how externally processed attachments interact with deduplication · how provenance survives
external extraction · what the pinned FastMCP/client versions support for binary transport · how much of this can
live **below** MCP so future clients reuse it.

## §36 Updated success experience

```text
Gio: [PNG] [PDF]  The seller sent these. Does this change our position?
ChatGPT: [understands attachments] [consults Neuro] [combines new information with durable intelligence]
         "I wouldn't change the structure yet. The new numbers strengthen their argument that the
          company is healthy, but your seller-note rationale is really about transition alignment…"
Gio: That makes sense. Let's stay at 10%, but frame it around transition.
ChatGPT: [records the durable decision back to Neuro]  "Understood."
Gio: Can you turn that into a polite email?
ChatGPT: [current conversation only] [drafts email] [does NOT query Neuro]
```

## §37 Final product principle

> **ChatGPT handles the moment. Neuro remembers what the moment means to the project.**

ChatGPT should be free to use its own multimodal and conversational strengths. Neuro should quietly contribute the
project's accumulated intelligence when needed and quietly absorb durable new knowledge when the conversation
creates it. **Neither system should redundantly repeat work the other has already done.** The result is a fast,
concise, natural ChatGPT experience backed by Neuro's persistent research, evidence, relationships and memory.


---

# FROZEN ARCHITECTURE — 2026-09-22 (§38–§67)

**Source note.** §1–§37 are historical context: the original brief, the 2026-09-11 amendment, and the
2026-09-11-session's repository observations. This section is the authoritative, self-contained frozen architecture
for External AI Access / P11, developed in a parallel architecture review and reconciled here against the repo at
commit `09a8439c` (`release: 0.63.95`). **Where this section and §1–§37 disagree, this section governs**, the same
precedence rule §20 and the 2026-09-11 amendment already established for their own predecessors. **P11 remains
PARKED.** This is documentation only; nothing below is built, and nothing here admits P11 into the active queue.
Historical §1–§37 are kept for the worked scenarios and repository observations they still usefully record, not as
a second, competing spec.

## §38 Core product boundary

ChatGPT, Claude and future LLM clients own the live conversation, immediate reasoning, multimodal understanding,
drafting, rewriting, tone, translation, and OCR/transcription when they already performed it, plus conversational
follow-up. Neuro owns durable project intelligence: sources, evidence, findings, Claims, research state, facts,
constraints, requirements, decisions, rejected options, rationale, counterpart positions, chronology, plan state,
provenance, and persistent relationships.

**Principle: ChatGPT handles the moment. Neuro remembers what the moment means to the project.** Neither side
repeats cognition the other already performed.

## §39 Structured external interface

New P11 operations return versioned structured JSON. Markdown-string MCP responses are not the durable machine
contract. Existing MCP tools remain compatibility wrappers over the structured contract, not the contract itself.

Every external response should carry, where applicable: `schema_version · project_id · project_revision · as_of ·
truncated · next_cursor · data`.

Core service functions live below MCP, matching §14's existing layering rule:

```text
Core Neuro service -> REST/API -> MCP/client adapters
```

## §40 External identity and ACL

Named external identities, revocable credentials, and per-project permissions. Possession of an external credential
never implies access to every project (§11's core requirement, restated as a hard boundary here).

Presets remain **Read Only · Read + Contribute · Owner** (§11). Read + Contribute may search/read evidence, add
sources/correspondence, submit processed material, and record permitted user-authored state. It may not delete
projects/sources, change budgets/settings, administer access, or approve research findings unless explicitly
granted.

**Actor identity and client identity are separate.** Neuro must be able to distinguish "Gio using ChatGPT" from
"Kyle using ChatGPT" — the credential identifies the client connection, not necessarily which person is at the
keyboard.

## §41 Disclosure policy is separate from ACL

Project access does not imply permission to disclose every object in that project. `authorize()` returns both
operation permissions and the disclosure policy. Read-assembly functions receive that policy and construct only
from permitted material. **Never retrieve everything and filter restricted material at egress** — the policy is an
input to assembly, not a post-hoc filter.

Disclosure is enforced inside: `open_project · get_project_changes · search_project · consult_project ·
get_evidence · timeline/chronology queries · future read paths`.

Data classes, at minimum: `standard · correspondence · financial · tax · identity · restricted`. Unclassified
external-disclosure state is restrictive by default. A client-declared class may only make material *more*
restrictive, never downgrade it — only an authorized owner can lower a classification, and that change is audited.

## §42 Sensitivity propagates through provenance

Source filtering alone is insufficient. Findings, Claims, Tensions, open Questions, plan-derived state, and
project-change events inherit the most restrictive relevant disclosure floor from the evidence/state they depend
upon, via the provenance link §4, §26 and §33 already require Neuro to keep. **A derived artifact may not be
disclosed more broadly than its contributing material.**

P11 v1 may conservatively withhold a derived artifact entirely rather than compute a disclosure-safe subset.
Re-deriving a narrowed version from only the evidence a given identity is permitted to see is a **future
optimisation**, filed here so it is not mistaken for a v1 requirement or a design ceiling.

## §43 Legacy sensitivity backfill

Do not classify by platform alone. Existing material provably acquired anonymously or publicly — no authenticated
session, cookies, private browser capture, or user-private input involved — may backfill to `standard`.
Authenticated, session-scoped, browser-private, or user-private material becomes `restricted`, regardless of
platform. Material whose acquisition provenance cannot establish either case **stays restricted/unclassified for
external disclosure** — uncertainty defaults closed, consistent with §41's classification rule.

**EA-0 (§66) defines and tests this backfill.**

## §44 Project change ledger

One narrow, append-only project-change ledger, rather than specialised history tables for every object. Conceptual
fields:

```text
id AUTOINCREMENT
project_id
event_type
object_type
object_id
actor_id
external_client_id
intake_id / request_id
before
after
disclosure_floor
created_at
```

Existing domain tables remain authoritative current state. **The ledger is not event sourcing and must never become
a second state model.** It provides the external sync cursor, chronology, actor attribution, state-transition
history, auditability, conflict context, and change feeds.

Each ledger row's `disclosure_floor` (§42) is the maximum — most restrictive — sensitivity of every field its
`before`/`after` payload exposes, so an event cannot become readable to a lower-clearance identity merely because
the event record itself was not separately classified.

## §45 Ledger mutation invariant

Ledger append happens through a single mutation choke point, inside the same database transaction as the
authoritative state change. Correct ordering:

```text
BEGIN
read only the small tracked before-fields
perform mutation
compare exact tracked old/new values
append event when appropriate
COMMIT
```

After commit: materiality / Decision Impact classification, cache invalidation, notification/sync preparation.
**Never perform expensive loops, inference, network work, or large diff construction while holding the write
transaction.** `before`/`after` contain only bounded decision-relevant state — never whole rows, source bodies,
transcript excerpts, or giant JSON.

## §46 Exact no-op suppression

Derived recomputation that lands on identical tracked values creates no project-change event. An idempotent retry
with the same request identity (§11's `client_request_id` / file hash / `external_message_id`) creates no duplicate
event. Internal maintenance work — job heartbeats, usage rows, caches, worker state, and similar operational
mutations — does not belong in the project-intelligence ledger at all.

Derive the ledgered event taxonomy primarily from the state already fingerprinted by `conversation_delta_revision()`
(`db.py`) plus user facts/decisions, because that existing code deliberately excludes irrelevant job churn.

## §47 Explicit user reaffirmation exception

§46's no-op suppression is for *incidental* recomputation landing on an unchanged value. An **explicit user
reaffirmation** is meaningful even when the current-state value is unchanged. Example: the seller applies new
pressure, and Gio says *"I understand. We are still staying at 10%."* The current decision remains 10%, but Neuro
records a `decision_reaffirmed` event with actor, context, timestamp and rationale when available — the underlying
decision row is left unchanged, not overwritten or duplicated.

Summary: derived same-value recomputation = no event · idempotent retry = no event · explicit user reaffirmation =
chronology event, current-state row unchanged.

## §48 Semantic external delta

External clients must not synchronise on "rows were touched" — reassessment is not itself intelligence change.
Example: 56 Claims reassessed, 54 unchanged, 2 genuinely changed — only the 2 changed Claims enter the semantic
change stream. Materiality and Decision Impact ordering happen after commit, over actual changed events. One global
ledger ID sequence can provide filtered/scoped views rather than five separate physical counters.

Delta responses are bounded, impact-ordered and cursor-based. A large overnight research run should surface as
something like *"56 reassessed · 3 materially changed · 1 could change an active decision"* rather than dumping 56
refreshed objects. `conversation_delta_revision()` remains useful as a cheap change/fingerprint token but is not
itself a diff log.

## §49 Durable user state model

Current `project_facts` (`db.py`) is insufficient for multi-person automatic sync. The eventual additive model must
support, conceptually: `actor_id · external_client_id · rationale · status · effective_at · supersedes_fact_id ·
explicitness · client_request_id`. A changed decision supersedes prior state rather than leaving contradictory
"current" facts. Preserve history. Distinguish individual preference from project decision.

## §50 Auto-sync boundary

Explicit durable user state may commit directly: *"We are staying at 10%." · "Agreed, do that." · "Change it to
7.5%."* Inferred durable state is proposed/reviewable: *"Maybe we should be more flexible." · "I'm worried about
retention."* Presentation chatter is not project memory: *"Make it shorter." · "Use a warmer tone."* — matching §30's
existing durable/not-durable split. User acceptance can promote an assistant recommendation into an explicit user
decision without requiring the user to restate the whole recommendation (§30's existing rule).

## §51 Optimistic concurrency

Important external state writes may carry the project/change revision they were based on. If Kyle and Gio change
the same state concurrently, Neuro must not silently use last-writer-wins — return a conflict with current state and
proposed state when appropriate. Evidence/source ingestion generally does not require the same conflict semantics;
project truth does.

## §52 External Intake Event

One external conversation turn may contain multiple distinct things — screenshot, PDF, spreadsheet, correspondence,
user decision, AI interpretation. Keep those objects distinct but group them under one durable intake event carrying
actor/client/project/request/provenance/idempotency state. `source_captures` (`db.py`, `ingest.py`, `api.py`) is the
architectural precedent: one canonical source may already correspond to several meaningful capture/intake events.
The Project Inbox (§8) may be a view rather than a second queue. Orphaned/incomplete intakes surface as
`needs_review`; they must never disappear silently.

## §53 Raw and processed ingestion

Both paths supported, as §22 already establishes: **Path A** — raw material → Neuro extraction → Neuro knowledge
system. **Path B** — raw material already understood by an external AI → structured extraction → Neuro knowledge
system. One Neuro persistent knowledge architecture, several extraction producers (§21). Do not OCR, transcribe,
parse or refetch merely to reproduce work the external LLM already performed.

Preserve: original material when practical · extracted representation · structured information ·
provenance/locators · producer · extraction method · confidence where applicable · interpretation kept separately.
Source, extraction and interpretation never collapse (§23). AI interpretation is never evidence merely because an
AI generated it.

## §54 Multimodal processed-material contract

The processed-material schema (§24's `add_processed_material`) must be capable of representing: screenshots/images
with visible text and regions · PDFs with page-bounded text · URLs with canonical URL/headings/text ·
correspondence metadata/body/thread information · spreadsheets with structured values plus original workbook when
Neuro features require formulas (§25e) · audio/video with timestamped transcript segments, optional speaker
identity, language and confidence.

A separate public `add_processed_media` convenience tool may be a fast-follow; the v1 schema must not require a
retrofit to support it.

## §55 Artifact transport abstraction

Keep intake metadata/processed JSON separate from large binary transport. Conceptually:

```text
create_intake
add_processed_material
attach_artifact(intake_id, artifact_ref)
finalize_intake
```

`artifact_ref` can resolve through supported transport mechanisms — multipart REST upload, temporary client file
handle, supported MCP resource, signed temporary URL, or future attachment reference. The domain model must not
hardcode one client's file-transfer mechanism.

Signed/remote refs are an SSRF boundary: allowlisted ref kinds, existing validated/safe fetch machinery, no
internal/link-local access or unsafe redirects, streaming size enforcement, resolved-byte hashing and normal Neuro
dedupe. Finalization is idempotent: repeating the same request ID returns the original result rather than
duplicating the intake.

## §56 Read interface

Keep the stable external surface small. Conceptually: `list_projects · open_project · get_project_changes ·
search_project · get_evidence · consult_project · add_intake / processed-material operations · sync_project_state ·
get_intake_status`, eventually `get_project_timeline`. Existing detailed MCP operations (§19's 17 tools) may remain
for compatibility.

## §57 Project orientation and revisions

`open_project` returns compact orientation, client/server capabilities, disclosure constraints and
revision/cursor information in one inexpensive structured call — the same "one inexpensive call" requirement §5
already places on `get_project_context`. Do not require ten tiny discovery calls. Do not run a model just to orient
a client (§14's existing performance rule).

## §58 `consult_project` semantics

A compact deterministic/stored intelligence packet — not Neuro native chat, and not a newly generated advisory
answer. It may contain stored state and named deterministic derivations Neuro already owns: current user/project
position · relevant constraints · relevant research state · changed intelligence · tensions/watch-outs · current
plan implications · unresolved questions · evidence availability. Derived values identify their basis/version where
appropriate — a Planner recommendation returns as `stored_plan_recommendation` with the plan/version that owns it.
ChatGPT/Claude performs the immediate final reasoning, consistent with §27's packet and §28's "ChatGPT synthesises"
rule.

## §59 Read/write decisions per turn

Every external turn independently asks the two questions §29 already poses: does the LLM need new Neuro
information, and did this turn create durable project information Neuro should remember. Read/write/both/neither
are all valid answers. Once project information has been retrieved, presentation transformations continue locally
until substantive reasoning or project state changes (§29's local-continuation rule).

## §60 Chronology

Chronology storage begins in v1 because lost history cannot be reconstructed later. A rich `get_project_timeline`
experience may be additive after the vertical slice (§65), but the ledger (§44) and actor/state-event model
required to answer chronology must exist from the start.

## §61 Revocation

Revoking an external credential stops new requests and uncommitted external state mutations. Material already
durably accepted into Neuro remains part of the project and continues through Neuro's own authorized processing
pipeline with its original attribution. The revocation boundary itself is audited.

## §62 Transport and disclosure are independent

Server reachability and information disclosure are separate security questions. Current preferred direction: local
Neuro UI/tools → local/LAN · private-network-capable clients → LAN/VPN/private connection · ChatGPT → optional
Secure MCP Tunnel where required · public inbound Neuro endpoint → **not** P11 v1. The tunnel is optional and
independently switchable — Neuro continues working locally if it is unavailable. Separate per-client disclosure
rules (§41–§42) govern what project material may be sent through that connection.

## §63 Capability negotiation

External client capabilities vary and must not be hardcoded by vendor. Capability description may include: vision ·
OCR · PDF understanding · table extraction · transcription · speaker diarization · web access · binary/file
transport · read/write support. Transport capability and disclosure permission (§41) remain separate.

## §64 External AI Health

Do not render one generic "connected/not connected" status. Health should distinguish: transport/tunnel offline ·
credential invalid or revoked · project unauthorized · disclosure policy denial · client capability limitation ·
Neuro API/integration failure. Where useful, show transport, last handshake, last request, last success and last
policy denial, without logging sensitive payloads.

## §65 P11 v1 vertical slice

"Full data model and contract, narrower surface" still means a real, usable end-to-end slice: external identity +
project ACL · disclosure policy · structured project orientation · revision/change cursor · bounded semantic
changes · project search + evidence drill-down · raw/processed intake · explicit user decision/state sync with
actor and supersession · intake/status receipt · one real external client completing the loop. Timeline UI/query
richness, Undo UI, a richer Project Inbox, dedicated processed-media convenience tools, and additional clients may
follow once this slice is proven.

## §66 EA-0 responsibilities

**EA-0 is discovery and contract-shaping work, not implementation.** It resolves, from the current repo and current
client capabilities: structured contract/schema versions · external identity/ACL shape · capability matrix ·
transport options · disclosure classes/policies · legacy classification backfill (§43) · externally-observable
event taxonomy · per-object exact equality fields · materiality/Decision Impact rules and versions ·
processed-material envelope · artifact transport support. **It does not reopen the architecture above without
finding a concrete contradiction in current code, and completing it does not itself admit P11 or authorise writing
implementation code** — admission is a separate, explicit scheduling decision (§67), governed by the same rule §13
already states: a session picking this mission up confirms with Kyle that this is the current work before writing
code.

## §67 Sequencing

> *2026-09-22, after this section was frozen:* Kyle re-opened P11 — ACTIVE / FINAL READINESS. The paragraph below
> records the sequencing that held at the time of the freeze; the admission it said would be "decided separately" has
> now been decided. Implementation still waits for Kyle's explicit acceptance of the execution plan.

P11 remains PARKED behind the current NOW queue (confirmed live against `PRODUCT-SCHEDULER.md` and `HANDOFF.md`'s
PARKED line at the commit checked for this amendment). This documentation work does not admit P11 and does not
authorise implementation. Neither does EA-0 (§66) on its own — admission is decided separately, when Kyle reopens
the mission.

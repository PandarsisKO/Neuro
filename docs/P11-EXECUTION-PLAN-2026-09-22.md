# P11 EXECUTION PLAN — External AI Access + Bidirectional Project Intelligence

**Written 2026-09-22 against `origin/main` `9d08fcc` (0.63.95).** Status: **PLAN READY FOR FINAL REVIEW — implementation
NOT started.** Authority: `EXTERNAL-AI-ACCESS-MISSION.md` §38–§67 (Frozen Architecture, accepted, not redrafted here) and
Kyle's 2026-09-22 directive. This document is the one consolidated readiness pass the directive asked for; the nine
P11-P1…P9 questions are answered as sections 1–10 below, and the rungs EA-0…EA-9 are the execution order. Nothing in
sections 1–10 reopens a frozen decision; where the current code shaped a choice, the code is cited.

Lanes: **Cowork/Desktop** = planning, code and tests it can write, doc updates. **Claude Code** = Git delivery, live Mac,
live app, `release-check`, version bumps. Kyle/ChatGPT = review of this plan and the three decisions in §12.

---

## 1. Reuse map — what exists, what is added

| Need (frozen §) | Exists today (exact) | Verdict |
|---|---|---|
| Auth (§40) | `api.py` one shared secret `NEUROSEARCH_APP_TOKEN`: `_token_ok`, `_request_token`, `require_auth`, `TokenPathMiddleware` (`/mcp/<token>`), `ns_token` cookie, `/api/login` | **Keep unchanged** for UI/CLI/extension. External principals are a second, parallel auth path (`external.authorize`) that never touches this one. |
| MCP (§39, §56) | `mcp_server.py`: 17 markdown tools (`search_knowledge`, `ask`, `list_projects`, `create_project`, `add_to_project`, `list_sources`, `list_collections`, `get_transcript`, `ingest`, `job_status`, `findings`, `masterplan`, `build_master_plan`, `get_master_plan`, `record_fact`, `update_brief`, `save_note`), mounted at `/mcp` | Keep as compatibility wrappers. New structured tools are added in a second MCP module bound to the external service; the old tools are not rewritten. |
| Durable user state (§49) | `project_facts` (id, project_id, kind ∈ decision/constraint/requirement/rejected/context, content, origin ∈ user/assistant, created_at); `db.add_fact/list_facts/delete_fact`, `facts_revision()`, `/api/projects/{id}/facts`, MCP `record_fact` | **Extend in place** (additive columns, §2). Existing rows stay valid with defaults. |
| Change fingerprint (§46, §48) | `db.conversation_delta_revision()` (membership hash, sources count/max updated, `project_notes_revision`, claims count/max, `claim_evidence` max id, tensions, evidence targets, current plan id) — explicitly excludes jobs/heartbeats/usage | Its read set **is** the ledgered taxonomy's object list. Kept as the cheap revision token in every envelope. |
| Materiality / Decision Impact (§48) | `decision_impact.py` (`decision_impact(project_id, claim_ids)`), `plan_impact.py`, `conversation_delta.py` (material vs supporting units, `_attach_plan_impact`), `delta.py` (`_project_delta` for the nightly) | Reused post-commit, over changed events only. No new impact engine. |
| Intake event precedent (§52) | `source_captures` + `db.create_or_get_capture_ingest_request()` (client id + job id in one insert, retry-safe) | Pattern copied for `external_intakes`; `source_captures` itself untouched. |
| Path B ingestion (§53, §54) | `POST /api/ingest/text` → `ingest.ingest_text`; `POST /api/import` → `ingest.store_transcript(payload)` (segments+chapters extracted elsewhere); `sources.transcript_kind='manual'`; `documents.py` page locators, `sheets.py` sheet locators, `claim_evidence.locator`; `images.py` + `/read-image` | Processed-material adapters call these. **No new ingestion pipeline.** |
| Raw ingestion (§53) | `POST /api/ingest`, `/api/ingest/file`, `jobs` kinds `ingest_url` / `ingest_file` / `ingest_source`, `identity.resolve_or_create_source` (fingerprint dedupe) | Reused verbatim; intake items enqueue these jobs. |
| External fetch (§55) | `safe_fetch.safe_fetch()` (`LIMITS` per content class, pinned resolver, `FetchBlocked`) | The **only** resolver for URL-kind `artifact_ref`. |
| $0 stored derivations for `consult_project` (§58) | `research_view.overview/watchouts/questions/attention`, `claims_view`, `findings_view`, `sources_value.digest`, `plan_state.py`, `plan_narrative.py`, `research_needs.py`, `assumptions.py` | Assembled, never recomputed with a model. |
| Search (§56) | `search.py` (FTS + embeddings + RRF), `evidence.py` | Wrapped with a disclosure-aware source-id prefilter passed **into** the query (never post-filtered). |
| Promotion door | `claims.set_status` (the only Claim promotion path) | Ledger hook lives inside it. |
| Health | `db.health()`, `/api/health`, Health tab | Adds an `external_ai` section. |
| Provenance for legacy classification (§43) | `sources.platform`, `transcript_kind`, `access_gate`, `canonical_url`; `source_captures` rows; `platform='file'` uploads; Instagram-only-via-extension rule (CLAUDE.md) | **Finding: no acquisition-provenance column exists.** Backfill derives from these; the underivable stays restricted. |

**Genuinely new:** external principals + credentials + grants; disclosure classes and the assembly-time policy; the
project change ledger and its choke point; fact supersession; intake events + items; the structured external service
and its REST/MCP adapters; artifact-ref resolution; External AI Health; the Access management card.

---

## 2. Final additive data model (all `CREATE … IF NOT EXISTS` + `ALTER … ADD COLUMN` in `db.py`, no migration tool)

```sql
-- Principals. Actor = a person. Client = an LLM product/connection. One credential binds exactly one (actor, client)
-- pair, so "Gio using ChatGPT" and "Kyle using ChatGPT" are two credentials, never a header the caller can forge.
CREATE TABLE IF NOT EXISTS external_actors (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'person',   -- person | service
    created_at REAL NOT NULL, disabled_at REAL);
CREATE TABLE IF NOT EXISTS external_clients (
    id TEXT PRIMARY KEY, label TEXT NOT NULL,                       -- free label ("Gio's ChatGPT"), never a vendor enum
    capabilities TEXT NOT NULL DEFAULT '{}',                        -- JSON, §63 vocabulary, last declared by the client
    transport TEXT NOT NULL DEFAULT 'local',                        -- local | lan | tunnel
    created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS external_credentials (
    id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES external_actors(id), client_id TEXT NOT NULL REFERENCES external_clients(id),
    token_prefix TEXT NOT NULL UNIQUE,                              -- first 12 chars of the secret; the lookup key and the only part ever logged
    token_hash TEXT NOT NULL,                                       -- sha256(secret); secret shown once at creation, never stored
    created_at REAL NOT NULL, created_by TEXT, expires_at REAL, last_used_at REAL,
    revoked_at REAL, revoked_by TEXT, revoke_reason TEXT, rotated_from TEXT);
CREATE TABLE IF NOT EXISTS external_project_grants (               -- ACL, on the ACTOR (survives credential rotation)
    id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES external_actors(id),
    role TEXT NOT NULL,                                             -- read | contribute | owner   (§40 presets)
    disclosure_classes TEXT NOT NULL DEFAULT '["standard"]',        -- JSON list of classes this actor may receive in this project (§41)
    extra_permissions TEXT NOT NULL DEFAULT '[]',                   -- JSON: approve_findings | administer_access … (explicit grants only)
    granted_by TEXT, granted_at REAL NOT NULL, revoked_at REAL, revoked_by TEXT,
    UNIQUE(project_id, actor_id));

-- Sensitivity. Stored on the ORIGINAL material; everything derived computes its floor from provenance at assembly.
ALTER TABLE sources ADD COLUMN disclosure_class TEXT;              -- standard|correspondence|financial|tax|identity|restricted; NULL = unclassified = restricted for external disclosure
ALTER TABLE sources ADD COLUMN disclosure_origin TEXT;             -- backfill_public | backfill_private | client_declared | owner_set
ALTER TABLE sources ADD COLUMN acquisition_provenance TEXT;        -- anonymous | authenticated | browser_private | user_private | external_processed | unknown  (written by every new ingest; NULL on legacy rows until backfill)
ALTER TABLE project_facts ADD COLUMN disclosure_class TEXT;        -- user state is classified directly (default 'standard' on write)
CREATE TABLE IF NOT EXISTS disclosure_audit (                       -- only lowering a class is audited separately (§41); raising is ordinary
    id INTEGER PRIMARY KEY, object_type TEXT NOT NULL, object_id TEXT NOT NULL, from_class TEXT, to_class TEXT NOT NULL,
    actor_id TEXT, reason TEXT, created_at REAL NOT NULL);

-- Project change ledger (§44). Append-only. Domain tables stay the current-state authority.
CREATE TABLE IF NOT EXISTS project_change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
    actor_id TEXT, external_client_id TEXT, intake_id TEXT, request_id TEXT,
    before TEXT, after TEXT,                                        -- JSON of the TRACKED fields only (§45), bounded ≤ 4 KB each, enforced
    disclosure_floor TEXT NOT NULL DEFAULT 'restricted',           -- most restrictive class among the fields exposed (§44)
    materiality TEXT, decision_impact TEXT,                         -- filled POST-commit (§45/§48): none|supporting|material ; JSON of affected decisions/plan items or NULL
    created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_pce_project_id ON project_change_events(project_id, id);
CREATE INDEX IF NOT EXISTS ix_pce_object ON project_change_events(object_type, object_id);

-- Durable user state evolution (§49): extend project_facts, keep every existing row valid.
ALTER TABLE project_facts ADD COLUMN actor_id TEXT;                -- NULL = local owner (the UI/CLI path)
ALTER TABLE project_facts ADD COLUMN external_client_id TEXT;
ALTER TABLE project_facts ADD COLUMN explicitness TEXT NOT NULL DEFAULT 'explicit';  -- explicit | accepted_recommendation | inferred
ALTER TABLE project_facts ADD COLUMN status TEXT NOT NULL DEFAULT 'active';          -- active | superseded | proposed | rejected | withdrawn
ALTER TABLE project_facts ADD COLUMN scope TEXT NOT NULL DEFAULT 'project';          -- project | personal   ("I personally prefer 10%" is personal)
ALTER TABLE project_facts ADD COLUMN rationale TEXT;
ALTER TABLE project_facts ADD COLUMN effective_at REAL;
ALTER TABLE project_facts ADD COLUMN supersedes_fact_id INTEGER;
ALTER TABLE project_facts ADD COLUMN client_request_id TEXT;
ALTER TABLE project_facts ADD COLUMN updated_at REAL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_facts_request ON project_facts(external_client_id, client_request_id) WHERE client_request_id IS NOT NULL;

-- External Intake Events (§52) — the source_captures pattern, generalised.
CREATE TABLE IF NOT EXISTS external_intakes (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL, client_id TEXT NOT NULL, credential_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,                                -- idempotency key, resent verbatim on retry
    status TEXT NOT NULL DEFAULT 'received',                        -- received|routing|queued|processing|ready|needs_review|failed
    needs_review_reason TEXT, error TEXT,
    base_revision TEXT,                                             -- project_revision the client reasoned against (§51)
    conversation_ref TEXT,                                          -- opaque client thread id, never parsed
    created_at REAL NOT NULL, updated_at REAL NOT NULL, finalized_at REAL,
    UNIQUE(client_id, client_request_id));
CREATE TABLE IF NOT EXISTS intake_items (
    id TEXT PRIMARY KEY, intake_id TEXT NOT NULL REFERENCES external_intakes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                                             -- raw_artifact | processed_material | user_state | interpretation
    material_type TEXT,                                             -- image|pdf|url|correspondence|spreadsheet|transcript|text (§54)
    artifact_ref TEXT,                                              -- JSON {kind: multipart|mcp_resource|signed_url|client_handle, …} (§55)
    sha256 TEXT, bytes INTEGER, content_type TEXT,
    producer TEXT, extraction_method TEXT, confidence REAL,         -- §53 provenance of the processing
    payload TEXT,                                                   -- processed-material JSON (bounded; large text goes to the source, not here)
    source_id TEXT REFERENCES sources(id),                          -- NULL until resolved (may resolve to an EXISTING source — dedupe)
    ingest_job_id TEXT, fact_id INTEGER,                            -- written in the SAME insert that creates the item, never a later UPDATE
    status TEXT NOT NULL DEFAULT 'received', error TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL);

-- Request audit for Health (§64) and revocation audit (§61). Bounded retention (30 d), no payloads, no tokens.
CREATE TABLE IF NOT EXISTS external_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, credential_id TEXT, actor_id TEXT, client_id TEXT, operation TEXT NOT NULL,
    project_id TEXT, outcome TEXT NOT NULL,                          -- ok | auth_invalid | auth_revoked | project_unauthorized | disclosure_denied | capability_missing | conflict | error
    detail TEXT, duration_ms INTEGER, created_at REAL NOT NULL);
```

Not created: a separate Project Inbox table (it is a view over `external_intakes` + `intake_items`, §52), per-object history
tables (the ledger covers them, §44), any vendor enum.

---

## 3. Final external service contract

Module layout (one service, two adapters, matching §39's layering):

```text
neurosearch/external.py        service: authorize(), the ten operations below, envelope(), disclosure assembly helpers
neurosearch/ledger.py          record() choke point, taxonomy, equality fields, post-commit classify()
neurosearch/intake.py          intake state machine, item routing to existing ingest jobs, artifact_ref resolution
neurosearch/api.py             REST adapter:  /api/ext/v1/<op>   (auth: Authorization: Bearer nsx_…)
neurosearch/mcp_external.py    MCP adapter:   same ten tools, structured JSON text, mounted beside /mcp
```

Every response is the §39 envelope: `{schema_version:"1", project_id, project_revision, ledger_cursor, as_of, truncated,
next_cursor, data}`. `project_revision` = `conversation_delta_revision()` + `facts_revision()`; `ledger_cursor` = max
`project_change_events.id` visible to this identity.

| Op | Input | `data` | Notes |
|---|---|---|---|
| `list_projects` | — | `[{project_id, name, role, disclosure_classes, project_revision, last_change_at}]` | Only granted projects; nothing else exists from the caller's view. |
| `open_project` | `project_id, client_capabilities?` | `{orientation:{brief, goal, current_position:[facts active decision/constraint/requirement], open_questions[≤5], watchouts[≤5], plan_summary, counts}, capabilities:{server, client_echo, negotiated}, disclosure:{classes, withheld_count}, cursor}` | One call, no model (§57). Records `client_capabilities` on `external_clients`. |
| `get_project_changes` | `project_id, since_cursor, limit≤100, min_materiality?` | `{summary:{reassessed, changed, material, decision_affecting}, events:[{id, event_type, object_type, object_id, actor, when, before, after, materiality, decision_impact}]}` | Cursor over ledger ids, floor-filtered, impact-ordered within page (§48). |
| `search_project` | `project_id, query, limit≤20, kinds?` | `[{hit_type: chunk|claim|finding, id, source_id, locator, excerpt, score}]` | `search.py` with allowed-source prefilter as input. |
| `get_evidence` | `project_id, ref:{claim_id|finding_id|source_id, locator?}, depth: summary|excerpt|exact` | Progressive disclosure (§10 of the handoff): summary → excerpt → exact locator/page/timestamp. |
| `consult_project` | `project_id, question, focus?:{claim_ids, fact_ids}` | `{position, constraints, research_state:{claims[], tensions[]}, changed_since_cursor, plan_implications:{basis:"stored_plan_recommendation", plan_id, version}, unresolved, evidence_available:[refs]}` | Deterministic/stored only (§58): `research_view`, `plan_state`, `research_needs`, FTS on `question` for relevance; never `qa.ask`. |
| `create_intake` | `project_id, client_request_id, base_revision?, conversation_ref?` | `{intake_id, status}` | Idempotent on `(client_id, client_request_id)`. |
| `add_processed_material` | `intake_id, material` (§54 envelope) | `{item_id, status, dedupe:{existing_source_id?}}` | Routes to `ingest_text` / `store_transcript` / documents / sheets / images path. Never re-OCRs/re-transcribes. |
| `attach_artifact` | `intake_id, artifact_ref, item_id?` | `{item_id, status}` | Raw path. Ref kinds in §4. |
| `finalize_intake` | `intake_id, user_state?:[{kind, content, explicitness, scope, rationale, supersedes_fact_id?, client_request_id}], interpretations?:[…]` | `{intake_id, status, items:[…], facts:[…], conflicts:[…]}` | Idempotent. User state goes through `sync_project_state` semantics. Interpretations are stored as `intake_items.kind='interpretation'`, never as evidence. |
| `get_intake_status` | `intake_id` | `{status, items:[{id, kind, status, source_id, job}], needs_review_reason}` | |
| `sync_project_state` | `project_id, base_revision, changes:[{op: record|reaffirm|supersede|propose|withdraw, kind, content, fact_id?, rationale, explicitness, scope, client_request_id}]` | `{applied:[…], conflicts:[{fact_id, current, proposed}]}` | §50/§51. Contribute role required. |

`get_project_timeline` follows v1 as a read over the same ledger (§60); no schema change needed.

Processed-material envelope (`material`, §54), one shape for all types:

```json
{"material_type":"pdf|image|url|correspondence|spreadsheet|transcript|text",
 "title":"…","canonical_url":"…?","producer":"<client label>","extraction_method":"vision|ocr|pdf_text|html|asr|table",
 "confidence":0.0, "language":"en", "client_declared_class":"correspondence?",
 "units":[{"locator":"p. 4 | 00:12:34 | sheet!A1 | region:x,y,w,h | msg:<id>", "text":"…", "speaker":"?", "start":0.0,"end":0.0, "confidence":0.0}],
 "correspondence":{"from":"","to":[],"date":"","thread_id":"","subject":""},
 "table":{"columns":[],"rows":[[]]}, "original_ref":{"kind":"…"}}
```

`units[].locator` maps straight onto `claim_evidence.locator` (`"12:34" | "p. 4" | "§ 3" | "sheet!A1"`), so evidence
drill-down works for processed material with no new locator grammar.

---

## 4. Security model

- **Credential generation**: `secrets.token_urlsafe(32)` prefixed `nsx_`; shown once; `token_prefix` = first 12 chars
  (unique lookup), `token_hash` = sha256; verification = prefix lookup → `secrets.compare_digest` on the hash; `expires_at`
  optional; **rotation** = create successor with `rotated_from`, old one revoked after a stated overlap; **revocation**
  sets `revoked_at/by/reason` and appends an `access_revoked` ledger event with floor `restricted`.
- **ACL**: grants live on the actor. `external.authorize(credential, project_id, operation)` returns
  `Authorization(actor, client, role, disclosure_classes, extra_permissions)` or raises; role → operation matrix is a
  constant table (`read`: list/open/changes/search/evidence/consult/intake-status; `contribute`: + intakes + sync;
  `owner`: + nothing external in v1 — administration stays in the local UI). **IDOR**: every operation resolves the
  project through the grant; an ungranted or nonexistent project returns the same `404 unknown_project`; every object
  id (`claim_id`, `source_id`, `fact_id`, `intake_id`) is additionally checked to belong to that project before any
  read; intakes are further scoped to the creating actor.
- **Disclosure-at-assembly** (§41): `Authorization.disclosure_classes` is an argument of every assembly function;
  `allowed_source_ids(project_id, classes)` is computed once per request and passed **into** `search.py`/`evidence.py`
  queries and the claims/findings/tensions selectors. Derived objects: floor = most restrictive class over the
  `claim_evidence → sources` (Claims), `project_notes.source_id` (findings), tension/question → their claims, plan item
  → cited note ids (`decision_impact._plan_cited_note_ids` already walks this). v1 withholds a derived object whose
  floor exceeds the grant entirely and counts it in `disclosure.withheld_count` (§42's conservative rule).
- **Legacy classification backfill** (§43), a one-shot idempotent CLI `neurosearch external backfill-classes --dry-run`,
  deterministic, recorded in HANDOFF with counts: `platform IN (youtube, podcast, web) AND no source_captures row AND
  access_gate IS NULL` → `standard`/`backfill_public`; `platform = instagram` → `restricted`/`backfill_private` (extension
  session, by rule); any source with a `source_captures` row → `restricted` (browser capture); `platform = file` and
  `transcript_kind = manual` → `restricted`/`backfill_private` (user-private input); everything else → NULL (=
  restricted for disclosure). Only an owner action lowers a class afterwards, via `disclosure_audit`.
- **Artifacts / SSRF**: `artifact_ref.kind` allowlist = `multipart` (bytes in the request, existing `/api/ingest/file`
  validation and caps), `mcp_resource` (read through the MCP session, size-capped), `signed_url` (**only** via
  `safe_fetch.safe_fetch(url, content_class=…)` — `LIMITS`, pinned resolver, no private IPs, revalidated redirects,
  streamed byte cap, sha256 of resolved bytes → `identity` dedupe). No second fetch path. Upload validation reuses
  `documents.py`/`images.py` sniffing; declared `content_type` is a hint, never trusted.
- **Audit boundary**: `external_requests` (outcome codes, no payloads) + ledger events with actor/client. **Log hygiene**:
  `logctx` gets an `external_credential=prefix` field; the secret, `Authorization` header and material bodies are never
  logged; a regex test asserts no `nsx_` beyond 12 chars appears in any log line the test suite captures.
- **Transport** (§62): v1 = the existing FastAPI server (local/LAN); a tunnel is EA-7 and optional; no public inbound
  endpoint. Rate limit per credential (token bucket, 60 req/min default) in `authorize`.

---

## 5. Change ledger (`neurosearch/ledger.py`)

**Choke point.** `ledger.record(conn, project_id, *, event_type, object_type, object_id, before, after, actor_id=None,
client_id=None, intake_id=None, request_id=None)` is called **inside the existing `db.tx()` block** of each mutation
site; it compares `before`/`after` on the object's tracked fields and inserts a row only when they differ, or when
`event_type` is in the explicit-chronology set. `db.tx()` gains an optional `after_commit(fn)` hook list so
`ledger.classify(event_ids)` (materiality + Decision Impact via `decision_impact.py`/`plan_impact.py`) runs strictly
post-commit and in a short follow-up write. The write-hold rules of CLAUDE.md (P0) apply: no loops, no model, no network
inside the transaction; `before`/`after` ≤ 4 KB each, enforced by truncation to the tracked fields — never whole rows.

**Mutation sites and tracked equality fields** (derived from `conversation_delta_revision()`'s read set + user state):

| object_type | site | tracked fields | event_types |
|---|---|---|---|
| `source_membership` | `db.add_project_sources` / `db.remove_project_sources` / `excluded=1` / collection attach | `{source_id, member, excluded}` | `source_attached`, `source_removed`, `source_excluded` |
| `source` | ingest stage → ready; re-transcription (`revision`) | `{status, revision, disclosure_class}` | `source_ready`, `source_revised`, `sensitivity_changed` |
| `finding` (`project_notes`) | approve / dismiss / reviewed_at path | `{status, reviewed_at IS NOT NULL}` | `finding_status_changed` |
| `claim` (`project_claims`) | `claims.set_status` (only door); statement/confidence write in `claims.py` upsert | `{status, statement_hash, confidence_band}` | `claim_created`, `claim_status_changed`, `claim_statement_changed` |
| `claim_evidence` | insert in `claims.py` | `{claim_id, source_id, relation}` (new row = event) | `claim_evidence_added` |
| `tension` (`research_tensions`) | open / resolve | `{status}` | `tension_opened`, `tension_resolved` |
| `evidence_target` / question | open / resolve | `{status}` | `question_opened`, `question_resolved` |
| `fact` (`project_facts`) | `db.add_fact`, new `db.supersede_fact`, `db.reaffirm_fact`, `db.set_fact_status` | `{kind, content, status, scope, explicitness}` | `fact_recorded`, `decision_recorded`, `decision_changed`, `decision_reaffirmed`*, `decision_proposed`, `decision_rejected`, `fact_withdrawn` |
| `plan` | new plan version; `plan_items` status | `{plan_id, version}` / `{status}` | `plan_version_created`, `plan_item_status_changed` |
| `project` | brief/goal update | `brief_revision()` | `brief_changed` |
| `intake` | finalize | `{status}` | `intake_finalized`, `intake_needs_review` |
| `access` | grant/revoke/credential revoke | `{role, disclosure_classes}` | `access_granted`, `access_changed`, `access_revoked` (floor `restricted`) |

\* `decision_reaffirmed` is the §47 exception: written even when tracked fields are unchanged, only from an explicit
user action (`sync_project_state op=reaffirm` or the UI), never from recomputation.

**No-op rule (§46).** Equal tracked fields ⇒ no row. Same `(client_id, request_id)` ⇒ the original result is returned and no
row is written (`ux_facts_request`, `external_intakes` UNIQUE). Jobs, heartbeats, usage, caches, `work_units`, invocation
rows: never ledgered — there is no `record()` call on those paths, and a grep-gate test asserts `ledger.record` is called
only from the modules in the table.

**Disclosure floor.** Computed at record time from the object's floor (§4) and stored; `get_project_changes` filters
`disclosure_floor ∈ grant.disclosure_classes` in SQL.

**Cursor/paging.** `since_cursor` = ledger id; page ≤ 100; `summary` counts computed over the whole page window
(`reassessed` = touched objects reported by the pass, from the existing `work_units`/job result, not from the ledger;
`changed` = rows). Ordering inside a page: `decision_affecting` → `material` → rest, then id.

**Conflict behaviour** is in §7.

**Required test (the 56 case, `tests/test_ea2_ledger.py`):** seed 56 Claims; run the reassessment pass under
`NEUROSEARCH_FAKE_AI=1` with the fake returning 54 identical and 2 changed statements, one of which is cited by the
current plan; assert exactly 2 `claim_statement_changed` rows, `summary == {reassessed:56, changed:2, material:≥1,
decision_affecting:1}`, and that `db:write_hold` on `/api/perf` recorded no hold above `WRITE_HOLD_WARN_S`.

---

## 6. Intake model (`neurosearch/intake.py`)

State machine per intake and per item: `received → routing → queued → processing → ready | needs_review | failed`.
Transitions are written by the existing job lifecycle: an item's `ingest_job_id` is created in the same insert as the
item (the `create_or_get_capture_ingest_request` idiom); the job's completion hook (which already runs only after the
job leaves `_running`, CLAUDE.md P0) updates `intake_items.status`, and the intake's status is derived (`ready` when all
items ready; `needs_review` when any item failed or an artifact never arrived within 2 h; `failed` only when the intake
itself could not be recorded). Orphans surface in the Inbox view; nothing is deleted.

| Material | Path | Existing code used | Dedupe |
|---|---|---|---|
| raw file (multipart) | A | `/api/ingest/file` handler → `ingest_file` job | `identity.fingerprint_bytes` |
| processed screenshot | B | `ingest.ingest_text` with `units` → segments, `images.py` stores the original when attached; `source.platform='file'`, `transcript_kind='manual'`, `acquisition_provenance='external_processed'` | sha256 of original if attached, else `identity.fingerprint_text` of units |
| processed PDF | B | `ingest.ingest_text` with page locators (`documents.py` grammar) | same |
| URL (raw) | A | `ingest_url` job → `webpage.fetch` via `safe_fetch` | `media.canonical_url` |
| URL (processed) | B | `ingest_text(url=canonical_url)`; original fetch skipped | `canonical_url` |
| correspondence | B | `ingest_text` + `sources` row tagged `correspondence`, `disclosure_class='correspondence'` minimum, thread/message ids in units' locators | `fingerprint_text(thread_id, message_id)` |
| spreadsheet | B (+ original) | `sheets.py` when the workbook is attached (formulas needed, §25e); otherwise `ingest_text` with `sheet!A1` locators | sha256 / fingerprint |
| audio/video transcript | B | `ingest.store_transcript(payload)` — segments with start/end/speaker, `transcript_kind='manual'`, **no transcription job** | `canonical_url` or fingerprint |

No second job system: every processing step is an existing job kind; `intake` only routes and records.

---

## 7. Durable user state (`project_facts`, extended)

Fields resolved: `actor_id`, `external_client_id`, `explicitness` (explicit / accepted_recommendation / inferred),
`rationale`, `status` (active / superseded / proposed / rejected / withdrawn), `scope` (project / personal),
`effective_at`, `client_request_id`, `supersedes_fact_id`; conflict revision = `base_revision` on the request.

Rules: explicit + project scope ⇒ `active` immediately (Contribute role) and `decision_recorded`; inferred ⇒
`proposed` + `decision_proposed`, reviewable in the local UI; personal scope ⇒ stored, never returned as the project
position; acceptance ("Yes", "Agreed") promotes only when the client names **one** `referent` (the assistant proposal
text); the client is told to ask when the referent is ambiguous — the server enforces this by refusing an
`accepted_recommendation` without a single `referent` string. Supersession: `supersede` writes the new row `active`,
sets the old row `superseded` (`supersedes_fact_id` on the new), one `decision_changed` event with `before={old
content}`, `after={new content}`. Reaffirm: no row change, one `decision_reaffirmed` event with rationale/context.

Worked case (`tests/test_ea2_ledger.py::test_ten_reaffirm_seven_five`):

```text
sync record   kind=decision content="Seller note stays at 10%"  actor=gio explicit  → fact 1 active;   event decision_recorded
sync reaffirm fact_id=1 rationale="new seller pressure"                              → fact 1 unchanged; event decision_reaffirmed
sync supersede fact_id=1 content="Seller note 7.5%" rationale="…"                    → fact 2 active, fact 1 superseded; event decision_changed before={10%} after={7.5%}
open_project.current_position → [fact 2]; get_project_timeline(fact 1) → 3 events in order
```

Conflict (§51): a `supersede`/`reaffirm` whose `base_revision` predates a later change **to that fact** returns
`409 {conflicts:[{fact_id, current, proposed}]}` and applies nothing from that change; other changes in the same call
still apply and are reported in `applied`. Ingestion never conflicts.

---

## 8. Client capability contract (§63)

Vocabulary (booleans, declared by the client on `open_project`, stored on `external_clients.capabilities`): `vision`,
`ocr`, `pdf_text`, `table_extraction`, `web_access`, `transcription`, `diarization`, `file_transport:[multipart|
mcp_resource|signed_url|none]`, `read_tools`, `write_tools`. The server answers with `negotiated`: which intake paths
this client should use (e.g. `pdf: processed` when `pdf_text`, else `raw`). Transport capability never widens disclosure.
**Vendor capabilities are re-verified from current official documentation at EA-7, immediately before each client
adapter is written — not now.**

## 9. Health / failure semantics (§64)

`external_requests.outcome` is the taxonomy; `db.health()["external_ai"]` and a Health card show, per client: transport
(`local|lan|tunnel`, last handshake), last request, last success, last denial with its code. Codes and HTTP mapping:
`transport_offline` (client-side only; server shows "no request in N h"), `auth_invalid` 401, `auth_revoked` 401 with
`reason`, `project_unauthorized` 404 (indistinguishable from unknown, by design), `disclosure_denied` 200 with
`withheld_count` (never an error — the answer is assembled from what is allowed), `capability_missing` 422 naming the
capability, `conflict` 409, `error` 500 with a request id, no payload.

## 10. Test / acceptance matrix

| Scenario | Module | Kind |
|---|---|---|
| Kyle & Gio separate credentials; shared + private project; guessed ids → 404; read-only write → 403; revoked → 401; legacy token path untouched | `test_ea1_access.py` | pytest, temp DB |
| Disclosure leakage: restricted source cannot surface via Claim/Finding/Watch-out/plan implication/event/consult packet | `test_ea1_disclosure.py` | pytest, seeded provenance chains |
| Backfill classification counts + idempotence + NULL-stays-closed | `test_ea1_backfill.py` | pytest on `tests/fixtures/db/` |
| 10 → reaffirm → 7.5; concurrency 409; 56 reassessed; no-op; retry idempotent; ledger never called from job/usage paths (grep gate); write-hold gate | `test_ea2_ledger.py` | pytest |
| Read service: bounded orientation, no model call (`NEUROSEARCH_FAKE_AI` counter = 0), envelope fields, cursor paging | `test_ea3_read.py` | pytest |
| Intake: multi-object one intake; orphan → needs_review; retry no duplicate; processed PDF/screenshot with fake AI asserting zero OCR/model invocations; transcript with zero transcription jobs | `test_ea4_intake.py`, `test_ea5_processed.py` | pytest |
| Worked negotiation flow end to end (seller email → consult → decision → draft locally = no call) | `test_ea6_sync.py` | pytest, scripted client |
| Artifact refs: signed_url through `safe_fetch` (private IP blocked, redirect revalidated, byte cap), multipart caps | `test_ea7_artifacts.py` | pytest with `safe_fetch.RESOLVER/CONNECT` hooks |
| Backward compat: full suite green; `test_s43/s44`, `test_repo_check`, existing MCP tools unchanged, extension flows | existing gates | `release-check` |
| Live: one client end to end, second actor, shared/protected project, attachments, decision sync, chronology, deltas, evidence drill-down, revocation, failure states | EA-9 checklist in HANDOFF | Kyle/Gio, live Mac |

---

## 11. Ladder — dependency order, gates, lanes

Each rung = its own commit(s) on `main` at a coherent boundary, HANDOFF entry, tests green in the Cowork VM before
Claude Code pushes. Version bump + `release-check` only at EA-9 (or earlier if Kyle wants an intermediate release).
New test modules `tests/test_ea*.py` sort after `test_core.py`.

| Rung | Scope (exact) | Gate | Lane | Size |
|---|---|---|---|---|
| **EA-0** Contracts + migration design | **This document is EA-0's output.** Remaining: freeze the JSON schemas as `neurosearch/schemas.py` REGISTRY entries (`external.envelope.v1`, `external.material.v1`, `external.sync.v1`) and add the backfill query to `db.py` as a dry-run function | schemas load; backfill dry-run on `tests/fixtures/db/` prints counts | Cowork | ½ day |
| **EA-1** Principals + ACL + disclosure | tables in §2 (principals, grants, `sources.disclosure_class/origin/acquisition_provenance`, `disclosure_audit`); `external.authorize`; `allowed_source_ids`; floor computation; backfill CLI; every **new** ingest writes `acquisition_provenance`; `test_ea1_*` | isolation, read-only, IDOR, revocation, legacy auth, leakage, backfill tests pass | Cowork; Claude Code runs the backfill dry-run on the live DB via CLI and reports counts | 1–1.5 days |
| **EA-2** Ledger + durable state | `ledger.py`; `project_change_events`; `db.tx` after-commit hooks; `record()` at the §5 sites; `project_facts` columns + `supersede/reaffirm/set_status`; post-commit classify via `decision_impact`/`plan_impact`; `test_ea2_ledger` | 10→reaffirm→7.5; 56-case; no-op; grep gate; write-hold gate | Cowork | 1.5 days |
| **EA-3** Read service | `external.py` ops `list_projects … consult_project`; REST `/api/ext/v1/*`; `mcp_external.py`; `external_requests` audit; `test_ea3_read` | no model call; bounded; disclosure-safe; envelope; cursor | Cowork | 1.5 days |
| **EA-4** Intake events | `intake.py`; `external_intakes`/`intake_items`; `create_intake`/`attach_artifact` (multipart only)/`finalize_intake`/`get_intake_status`; Inbox projection endpoint; `test_ea4_intake` | multi-object linkage; orphan → needs_review; retry idempotent | Cowork | 1 day |
| **EA-5** Processed-material ingestion | `add_processed_material` adapters (§6 table) over `ingest_text`/`store_transcript`/`sheets`/`images`; `test_ea5_processed` | zero duplicate cognition (fake-AI/transcription counters = 0); evidence drill-down reaches locators | Cowork | 1 day |
| **EA-6** Bidirectional state sync | `sync_project_state`; acceptance/referent rule; conflicts; `finalize_intake.user_state`; `test_ea6_sync` | worked flow end to end | Cowork | 1 day |
| **EA-7** Artifact transport + client adapters | `signed_url` + `mcp_resource` ref kinds via `safe_fetch`; capability negotiation finalised; **re-verify Claude/ChatGPT connector capabilities from official docs**; first adapter = Claude (local MCP, no tunnel); ChatGPT adapter + optional tunnel config only if §12-Q1 says v1 | `test_ea7_artifacts`; one real client connects over LAN | Cowork + Claude Code (Mac config) | 1–2 days |
| **EA-8** Access / Inbox / Health UX | Settings card: actors, clients, credentials (create/rotate/revoke, secret shown once), grants + disclosure classes; Inbox view; Health `external_ai` section; `test_s44`-style frontend gates | UI edits never restart the process; gates pass | Cowork | 1 day |
| **EA-9** Live acceptance + release | Kyle/Gio scenarios (§10 last row); full suite; `release-check`; bump 0.64.0; State-of-the-App; HANDOFF closeout | all scenarios recorded in HANDOFF with evidence | Claude Code + Kyle | 1 day + Kyle's time |

Stops during execution (per the directive): a genuine product decision, a security conflict, an irreversible action, a
credential/account step only Kyle can do, or live acceptance needing Kyle's judgment. Nothing else pauses for approval.

---

## 12. Unresolved product decisions — the only genuine blockers

1. **First live client for EA-9.** Recommendation: **Claude** (local MCP over LAN, no tunnel) proves the loop first;
   ChatGPT + the optional tunnel is EA-7's second adapter and can slip to a fast-follow. Alternative: ChatGPT first,
   which makes the tunnel a v1 requirement.
2. **Local actor identity.** UI/CLI writes today have no actor. Recommendation: one `external_actors` row `kyle`
   (`kind=person`) is created by the Access card and stamped on local writes so chronology has a consistent author;
   `actor_id NULL` remains valid for historical rows and is rendered as "Kyle (local)".
3. **Default disclosure for a new grant.** Recommendation: `["standard"]` only; the owner adds `correspondence` /
   `financial` per grant in the Access card. Gio's grant on the buying-businesses project would then need Kyle to add
   `correspondence` before seller emails are consultable by Gio's client.

Everything else in this document is decided by the Frozen Architecture or by the current code.

---

## 13. Checkpoint

```text
P11 PLAN READY FOR FINAL REVIEW

FROZEN ARCHITECTURE        CONFIRMED (§38–§67 at 9d08fcc; not redrafted)
REPO CONTRADICTIONS        none. One EA-0 finding: sources has no acquisition-provenance column; §43 backfill derives it (§4) and defaults closed.
UNRESOLVED PRODUCT DECISIONS   §12 (three; each has a recommendation)
IMPLEMENTATION             NOT STARTED
READY TO EXECUTE           YES — on "P11 plan accepted. Begin execution."
```

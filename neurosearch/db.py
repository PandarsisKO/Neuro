"""SQLite storage: sources, segments, chunks (+FTS5), collections, jobs.

One database file, WAL mode, safe for a single app process with a few worker threads.
"""
from __future__ import annotations

import logging
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
from typing import Iterable, Any, Iterator

import numpy as np

from .config import settings

FALLBACK_POLICY_VERSION = "fallback-policy-v1"    # mirrored from contracts (db must not import contracts)
CHUNK_EMBEDDING_REVISION_KEY = "chunks:embedding-revision"

# R8 storage hygiene, measured 2026-09-11 on a copied 630 MB verified backup. SQLite's default cache was only
# 2 MB and mmap was disabled. The cache is per connection, so 64 MB is deliberately bounded even on a 128 GB Mac.
#
# 0.63.44 — mmap is OFF again, and this is a deliberate reversal of one part of R8. On 2026-09-12 the Mac slept
# from 09:32 to 13:43 (four missed hourly backups, no log line in between) and the FIRST integrity check after it
# woke reported `fts5: corruption found reading blob 824633720836 from table "chunks_fts"`. It repeated at 14:44
# and 15:44 with the SAME blob id, always with 0 foreign-key violations, and was gone after a restart. Every
# hourly backup verified clean throughout — `verify_database` opens its own read-only connection, which never had
# mmap set. That is the signature of a stale memory-mapped page surviving sleep/wake, not of damage on disk: the
# b-tree is intact, one specific mapped page reads as garbage, and a fresh process maps it correctly.
#
# It matters beyond a noisy log. A page that can be served to `quick_check` can be served to a query, so search —
# and therefore findings and chat citations — could read a stale page and nobody would know. R8's measured win was
# the composite index (7.87 ms -> 0.43 ms); mmap was bundled into that rung and never isolated, so there is no
# recorded benefit being given up here. Causation is not proven: the test is whether corruption recurs across a
# sleep with this at 0. If it does, this hypothesis is wrong and the line costs nothing to restore.
# (WAL mode still memory-maps the -shm file regardless of this setting; only table-page reads change.)
SQLITE_CACHE_KIB = 64 * 1024
SQLITE_MMAP_BYTES = 0
ANALYZE_INTERVAL_S = 7 * 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,            -- youtube | instagram | podcast | file | web
    external_id     TEXT,
    url             TEXT NOT NULL,
    title           TEXT,
    channel         TEXT,
    channel_url     TEXT,
    published_at    TEXT,                     -- ISO date
    duration        REAL,                     -- seconds
    description     TEXT,
    thumbnail_url   TEXT,
    language        TEXT,
    transcript_kind TEXT,                     -- captions | transcribed | manual
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | failed | skipped
    error           TEXT,
    tags            TEXT,                     -- JSON list
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_sources_platform_ext ON sources(platform, external_id);
CREATE INDEX IF NOT EXISTS ix_sources_status ON sources(status);

-- Screenshot capture provenance (the "Send screenshot" extension feature). One row per CAPTURE EVENT, not per
-- source: global image-content dedupe (content_fingerprint) means identical screenshot bytes resolve to ONE
-- `sources` row even though two captures of the same calculator can represent different configurations,
-- timestamps, notes or projects -- capture-specific columns on `sources` itself would overwrite the first
-- capture's provenance or lose a later one. `source_id` starts NULL: the API writes this row BEFORE enqueueing
-- the async ingest job (which only ever carries a capture_event id, never nine raw fields, in its payload) and
-- fills `source_id` in once ingestion resolves one -- so provenance survives the job-queue boundary rather than
-- being passed as function arguments that vanish with the job. `capture_note` is the user's own optional context,
-- kept here and never merged into the source's title or OCR-derived evidence.
CREATE TABLE IF NOT EXISTS source_captures (
    id                      TEXT PRIMARY KEY,
    source_id               TEXT REFERENCES sources(id) ON DELETE CASCADE,   -- NULL until the ingest job resolves one
    project_id              TEXT,
    capture_url             TEXT NOT NULL,
    capture_page_title      TEXT,
    captured_at             REAL NOT NULL,
    capture_mode            TEXT NOT NULL,      -- full_page | visible_only | partial_page
    capture_partial_reason  TEXT,                -- set only when the capture stopped before a complete full_page
                                                  -- grid: ceiling_pixels | ceiling_folds | ceiling_time |
                                                  -- fallback_after_error (NULL = complete)
    capture_page_width      INTEGER,
    capture_page_height     INTEGER,
    capture_viewport_width  INTEGER,
    capture_viewport_height INTEGER,
    capture_dpr             REAL,
    capture_note            TEXT,
    -- client_capture_id: the extension's own stable capture_id (one per "Send screenshot" press, reused
    -- verbatim on every retry). NULL-safe partial-unique so a retry with the SAME id can never create a
    -- second row -- see create_or_get_capture_ingest_request(), the one place this column is ever written.
    client_capture_id       TEXT,
    -- ingest_job_id: the ingest_file job this capture event enqueued. Populated in the SAME insert statement
    -- that creates this row (never a later UPDATE) so a committed row can never point at no job -- see
    -- create_or_get_capture_ingest_request()'s docstring for why that atomicity matters.
    ingest_job_id            TEXT,
    created_at              REAL NOT NULL,
    updated_at              REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_captures_source ON source_captures(source_id);

CREATE TABLE IF NOT EXISTS segments (
    id        INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    idx       INTEGER NOT NULL,
    start     REAL NOT NULL,
    end       REAL NOT NULL,
    text      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_segments_source ON segments(source_id, idx);

CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    idx       INTEGER NOT NULL,
    start     REAL NOT NULL,
    end       REAL NOT NULL,
    text      TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(source_id, idx);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS collections (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,   -- playlist | channel | manual
    url         TEXT,
    title       TEXT,
    external_id TEXT,
    created_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_collections_ext ON collections(kind, external_id);

CREATE TABLE IF NOT EXISTS source_collections (
    source_id     TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, collection_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,          -- ingest_url | ingest_source | reembed
    payload     TEXT NOT NULL,          -- JSON
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
    progress    REAL NOT NULL DEFAULT 0,
    message     TEXT,
    result      TEXT,                   -- JSON
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    brief       TEXT,                 -- what this project is trying to find out; guides answers
    tags        TEXT,                 -- JSON list: sources carrying any of these tags are included
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_sources (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id  TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, source_id)
);
CREATE TABLE IF NOT EXISTS project_collections (
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, collection_id)
);
CREATE TABLE IF NOT EXISTS project_notes (
    id         INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,         -- saved findings / pinned answers
    citations  TEXT,                  -- JSON
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_excludes (
    id         INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,         -- keyword | creator -- what `term` is matched against
    term       TEXT NOT NULL,         -- keyword: substring matched case-insensitively against candidate title/description/topic
                                       -- creator: exact creator/channel name, case-insensitive
    reason     TEXT,                  -- why, in the user's own words -- shown back when a candidate is filtered
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_facts (
    id         INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,         -- decision | constraint | requirement | rejected | context
    content    TEXT NOT NULL,
    origin     TEXT NOT NULL DEFAULT 'user',   -- user | assistant
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version    INTEGER NOT NULL,
    plan       TEXT NOT NULL,         -- JSON (structured plan)
    snapshot   TEXT,                  -- JSON: counts of sources/notes/messages/facts at generation time
    status     TEXT NOT NULL DEFAULT 'planning',   -- planning | started
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_plans_project ON plans(project_id, version);

CREATE TABLE IF NOT EXISTS plan_items (
    id         INTEGER PRIMARY KEY,
    plan_id    TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,         -- stable key e.g. first_steps.0, phases.1.tasks.2, decisions.0, questions.3
    status     TEXT NOT NULL DEFAULT 'not_started',
    note       TEXT,
    updated_at REAL NOT NULL,
    UNIQUE(plan_id, key)
);

CREATE TABLE IF NOT EXISTS plan_updates (
    id         INTEGER PRIMARY KEY,
    plan_id    TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    section    TEXT NOT NULL,
    previous   TEXT,
    proposed   TEXT NOT NULL,
    reason     TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',   -- pending | accepted | rejected
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discoveries (
    id         INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    kind       TEXT,
    url        TEXT,
    known_for  TEXT,
    why        TEXT,
    angle      TEXT,
    start_with TEXT,                  -- JSON list of {title, url}
    fit        INTEGER,
    depth      TEXT,
    note       TEXT,                  -- run-level note from the librarian
    refine     TEXT,                  -- the refinement text that produced this run, if any
    status     TEXT NOT NULL DEFAULT 'new',   -- new | added | dismissed
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_discoveries_project ON discoveries(project_id, status);

CREATE TABLE IF NOT EXISTS usage (
    id            INTEGER PRIMARY KEY,
    ts            REAL NOT NULL,
    kind          TEXT NOT NULL,     -- answer | findings | plan | discover | synthesis | embed | whisper
    model         TEXT,
    input_tokens  INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    seconds       REAL DEFAULT 0,
    cost          REAL NOT NULL,
    project_id    TEXT,
    source_id     TEXT
);
CREATE INDEX IF NOT EXISTS ix_usage_ts ON usage(ts);

CREATE TABLE IF NOT EXISTS invocations (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT,
    run_id              TEXT,
    task                TEXT,
    provider            TEXT NOT NULL,
    model               TEXT,
    input_hash          TEXT,
    state               TEXT NOT NULL,     -- intent | in_flight | completed | outcome_unknown | failed
    requested_at        REAL NOT NULL,
    completed_at        REAL,
    provider_request_id TEXT,
    error               TEXT
);
CREATE INDEX IF NOT EXISTS ix_invocations_state ON invocations(state, requested_at);

CREATE TABLE IF NOT EXISTS job_events (
    id         INTEGER PRIMARY KEY,
    ts         REAL NOT NULL,
    job_id     TEXT NOT NULL,
    run_id     TEXT,
    event_type TEXT NOT NULL,     -- queued | claimed | stage | heartbeat | retry_wait | budget_wait | rate_limit_wait | lease_expired | recovered
                                  -- | external_submitting | external_submitted | external_reattached | external_result | cancel_requested | cancelled | done | failed | deduplicated
    stage      TEXT,
    payload    TEXT               -- JSON
);
CREATE INDEX IF NOT EXISTS ix_job_events_job ON job_events(job_id, id);

CREATE TABLE IF NOT EXISTS project_source_analysis (
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id       TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    analysis_kind   TEXT NOT NULL,      -- relevance | summary   (one artifact per AI task, each with its own provenance)
    summary         TEXT,
    substance       INTEGER,
    relevance       INTEGER,
    relevance_why   TEXT,
    model           TEXT,
    provider        TEXT,
    prompt_version  TEXT,
    schema_version  TEXT,
    input_hash      TEXT,               -- hash of the exact inputs this task saw (what staleness compares)
    source_revision TEXT,
    brief_revision  TEXT,
    facts_revision  TEXT,
    r6_wave         TEXT,               -- fast | warm; scheduling provenance, not a quality verdict
    r6_provisional  INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'current',   -- current | legacy_unverified
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    PRIMARY KEY (project_id, source_id, analysis_kind)
);

CREATE TABLE IF NOT EXISTS batch_items (
    id            INTEGER PRIMARY KEY,
    job_id        TEXT NOT NULL,             -- the suggest_findings_batch job that owns the cohort
    cohort_no     INTEGER NOT NULL DEFAULT 1,-- resubmission round (failed items only move to the next cohort)
    custom_id     TEXT NOT NULL,             -- stable per logical work item (source window + input hash)
    task          TEXT NOT NULL,
    project_id    TEXT,
    source_id     TEXT,
    window_index  INTEGER,
    windows       INTEGER,
    params        TEXT NOT NULL,             -- the exact request params submitted (frozen at plan time)
    batch_id      TEXT,                      -- provider handle once submitted
    invocation_id TEXT,                      -- ledger row
    status        TEXT NOT NULL,             -- planned | submitted | succeeded | errored | expired | canceled | materialized
    raw           TEXT,                      -- the provider result, persisted locally the moment the batch ends (no reliance on provider retention)
    error         TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    UNIQUE(job_id, cohort_no, custom_id)
);
CREATE INDEX IF NOT EXISTS ix_batch_items_job ON batch_items(job_id, cohort_no);
CREATE INDEX IF NOT EXISTS ix_batch_items_batch ON batch_items(batch_id);

-- Foundation R4: provider responses are durable at the smallest independently retryable unit. The unit key is
-- derived from the exact request plus its inference contract and semantic revisions, so a compatible result can be
-- reused across a recovered parent job while a changed prompt/model/brief/source cannot materialise as current.
CREATE TABLE IF NOT EXISTS work_units (
    unit_key        TEXT PRIMARY KEY,
    task            TEXT NOT NULL,
    project_id      TEXT,
    source_id       TEXT,
    parent_hash     TEXT NOT NULL,
    unit_index      INTEGER NOT NULL,
    unit_count      INTEGER NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    schema_version  TEXT,
    source_revision TEXT,
    brief_revision  TEXT,
    facts_revision  TEXT,
    depth           TEXT,
    result          TEXT NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_work_units_parent ON work_units(task, project_id, source_id, parent_hash, unit_index);

-- G1 (0.25.0): source lineage seam. No behaviour yet — populated by later rungs (derived-from / cites / same-work) so
-- corroboration can tell twenty derivative repeats from one underlying piece of evidence. Additive, empty until then.
CREATE TABLE IF NOT EXISTS source_relations (
    from_source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    to_source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    relation       TEXT NOT NULL,            -- derived_from | cites | same_work | excerpt_of | reprint_of
    evidence       TEXT,                     -- JSON: how the relation was established
    created_at     REAL NOT NULL,
    PRIMARY KEY (from_source_id, to_source_id, relation)
);

-- G3 (0.27.0): the Discovery Candidate Index — what we have SEEN but not acquired. Cheap metadata only; never evidence.
-- One global candidate per (platform, external_id); the project relationship (state, relevance, reason, origin) is separate.
CREATE TABLE IF NOT EXISTS candidates (
    id               TEXT PRIMARY KEY,
    platform         TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    canonical_url    TEXT,
    url              TEXT NOT NULL,
    title            TEXT,
    description      TEXT,
    creator          TEXT,
    published_at     TEXT,
    duration         REAL,
    view_count       INTEGER,
    content_type     TEXT,                 -- video | podcast | page | document | post
    language         TEXT,
    first_seen_at    REAL NOT NULL,
    last_seen_at     REAL NOT NULL,
    last_verified_at REAL,
    availability     TEXT NOT NULL DEFAULT 'available',   -- available | unavailable | stale_metadata
    metadata_revision INTEGER NOT NULL DEFAULT 1,
    metadata_json    TEXT,                               -- bounded provider observation; never a thread payload
    source_id        TEXT REFERENCES sources(id) ON DELETE SET NULL,   -- set once acquired: the candidate RESOLVES to the global source
    UNIQUE (platform, external_id)
);
CREATE INDEX IF NOT EXISTS ix_candidates_source ON candidates(source_id);
CREATE TABLE IF NOT EXISTS collection_candidates (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    candidate_id  TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    first_seen_at REAL NOT NULL,
    last_seen_at  REAL NOT NULL,
    PRIMARY KEY (collection_id, candidate_id)
);
CREATE INDEX IF NOT EXISTS ix_collection_candidates_candidate ON collection_candidates(candidate_id, collection_id);
CREATE VIRTUAL TABLE IF NOT EXISTS candidates_fts USING fts5(title, description, creator, content='candidates', content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS candidates_ai AFTER INSERT ON candidates BEGIN
    INSERT INTO candidates_fts(rowid, title, description, creator) VALUES (new.rowid, new.title, new.description, new.creator);
END;
CREATE TRIGGER IF NOT EXISTS candidates_ad AFTER DELETE ON candidates BEGIN
    INSERT INTO candidates_fts(candidates_fts, rowid, title, description, creator) VALUES ('delete', old.rowid, old.title, old.description, old.creator);
END;
CREATE TRIGGER IF NOT EXISTS candidates_au AFTER UPDATE ON candidates BEGIN
    INSERT INTO candidates_fts(candidates_fts, rowid, title, description, creator) VALUES ('delete', old.rowid, old.title, old.description, old.creator);
    INSERT INTO candidates_fts(rowid, title, description, creator) VALUES (new.rowid, new.title, new.description, new.creator);
END;
CREATE TABLE IF NOT EXISTS candidate_projects (
    candidate_id   TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    state          TEXT NOT NULL DEFAULT 'available',   -- available | skipped_low_relevance | skipped_limit | skipped_cost | user_dismissed | duplicate | acquired
    relevance      INTEGER,
    relevance_why  TEXT,
    reason         TEXT,                                -- skip / dismiss reason in the user's words or the system's
    origin         TEXT,                                -- JSON: how this project encountered it (collection, kind, mission, discovery)
    first_seen_at  REAL NOT NULL,
    updated_at     REAL NOT NULL,
    PRIMARY KEY (candidate_id, project_id)
);
CREATE INDEX IF NOT EXISTS ix_candidate_projects_project ON candidate_projects(project_id, state);

-- G4 (0.28.0): Global Source Profiles — strictly project-NEUTRAL. baseline = $0, from stored metadata/chunks/embeddings;
-- enriched = one lazy model call (library.profile), cached globally, versioned by source revision + prompt/schema version.
-- Never built from project findings/summaries/relevance. Never a prerequisite for library recall.
CREATE TABLE IF NOT EXISTS source_profiles (
    source_id          TEXT PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    source_revision    TEXT,
    baseline           TEXT,                 -- JSON (see library.baseline)
    baseline_version   TEXT,
    baseline_at        REAL,
    centroid           BLOB,                 -- mean chunk vector: COARSE signal only
    topic_vectors      BLOB,                 -- k representative chunk vectors (farthest-point) so minority topics survive
    topic_chunk_ids    TEXT,                 -- JSON: the chunk ids behind topic_vectors (locatable)
    enriched           TEXT,                 -- JSON (schema source-profile-v1) or NULL
    enriched_status    TEXT NOT NULL DEFAULT 'none',   -- none | wanted | queued | current | stale | failed
    enriched_at        REAL,
    enriched_model     TEXT,
    enriched_prompt_version TEXT,
    enriched_schema_version TEXT,
    enriched_input_hash TEXT,
    enriched_routing   TEXT,
    enriched_transport TEXT,
    enriched_error     TEXT,
    wanted_at          REAL,
    wanted_by          TEXT,                 -- JSON: why it became a plausible candidate (query/gap/project) — provenance of the spend
    updated_at         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_profiles_status ON source_profiles(enriched_status);

-- G5 (0.29.0): Knowledge Map, Claim graph, Evidence Targets, Research Tensions. Project-scoped research STATE (never library
-- state). A Claim is a proposition the project currently believes / questions; evidence rows freeze the exact source
-- revision + locator so a revision can stale precisely the Claims it touched. Everything model-generated is proposed.
CREATE TABLE IF NOT EXISTS project_claims (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    text            TEXT NOT NULL,                       -- proposition WITH its qualifiers (never "lenders allow X")
    claim_type      TEXT NOT NULL DEFAULT 'other',       -- governing | historical | expert_interpretation | practice | experiential | market | causal | novel_tactic | other
    qualifiers      TEXT,                                -- JSON: jurisdiction, product, population, conditions, timeframe, source_language, specific_instance
    topic           TEXT,                                -- Knowledge Map node key
    freshness_class TEXT NOT NULL DEFAULT 'slow_changing', -- static | slow_changing | periodic | fast_changing (domain-sensitive)
    status          TEXT NOT NULL DEFAULT 'proposed',    -- proposed | accepted | rejected | superseded   (user/system state, never rewritten by the model)
    normalized      INTEGER NOT NULL DEFAULT 0,          -- 0 = $0 candidate awaiting claims.extract; 1 = normalized by the contract
    strength        TEXT NOT NULL DEFAULT 'unsupported', -- strong | developing | weak | unsupported | stale   (computed, deterministic)
    strength_why    TEXT,
    application     TEXT NOT NULL DEFAULT 'unknown',     -- established | developing | unknown   (does it apply to THIS project?)
    readiness       TEXT NOT NULL DEFAULT 'not_ready',   -- ready | not_ready
    readiness_why   TEXT,
    freshness_status TEXT NOT NULL DEFAULT 'uncertain', -- current | needs_refresh | stale | uncertain | age_insensitive   (G5.1: separate from strength)
    freshness_why   TEXT,
    origin          TEXT NOT NULL DEFAULT 'finding',     -- finding | finding_suggested | chat | user | model
    origin_note_id  INTEGER,
    extraction_hash TEXT,                                -- revision(s)+contract+text: same inputs → no second spend
    model           TEXT, prompt_version TEXT, schema_version TEXT, routing TEXT, transport TEXT,
    superseded_by   TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_claims_project ON project_claims(project_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS ix_claims_origin_note ON project_claims(project_id, origin_note_id) WHERE origin_note_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS claim_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        TEXT NOT NULL REFERENCES project_claims(id) ON DELETE CASCADE,
    source_id       TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_revision TEXT,
    locator         TEXT,                                -- "12:34" | "p. 4" | "§ 3" | "sheet!A1"
    start           REAL,
    link            TEXT,
    relation        TEXT NOT NULL DEFAULT 'SUPPORTS',    -- SUPPORTS | CONTRADICTS | QUALIFIES | INTERPRETS | EXPERIENTIAL
    excerpt         TEXT,
    evidence_class  TEXT,                                -- authoritative | expert | experiential | market | historical | derivative
    independent     INTEGER NOT NULL DEFAULT 1,          -- 0 when this passage repeats another source (derivative_of)
    derivative_of   TEXT,
    stale           INTEGER NOT NULL DEFAULT 0,          -- 1 once the source revision moved past source_revision
    task            TEXT, model TEXT,
    created_at      REAL NOT NULL,
    lineage_id      TEXT                                 -- G6: the Work this evidence's source belongs to (one Work = one lineage)
);
CREATE INDEX IF NOT EXISTS ix_claim_evidence_claim ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS ix_claim_evidence_source ON claim_evidence(source_id);
CREATE TABLE IF NOT EXISTS claim_evidence_notes (          -- findings folded into an existing Claim as evidence (harvest idempotency)
    claim_id TEXT NOT NULL REFERENCES project_claims(id) ON DELETE CASCADE,
    note_id  INTEGER NOT NULL,
    PRIMARY KEY (claim_id, note_id)
);
CREATE TABLE IF NOT EXISTS project_evidence_targets (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    question        TEXT NOT NULL,
    topic           TEXT,
    claim_id        TEXT REFERENCES project_claims(id) ON DELETE SET NULL,
    sufficiency     TEXT NOT NULL DEFAULT 'corroborative', -- governing | corroborative
    preferred_classes TEXT,                              -- JSON list, in order
    closure         TEXT,                                -- human-readable "enough" criterion
    closure_rule    TEXT,                                -- JSON {min_independent, primary_required, characterize_disagreement}
    status          TEXT NOT NULL DEFAULT 'open',        -- open | satisfied | closed_by_user
    origin          TEXT NOT NULL DEFAULT 'system',      -- system | model | user | tension
    current_evidence TEXT,                               -- JSON summary at last assessment
    gap             TEXT,
    last_escalation TEXT,                                -- JSON: the project → library → candidates → external steps and counts
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_targets_project ON project_evidence_targets(project_id, status);
CREATE TABLE IF NOT EXISTS project_knowledge_nodes (
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    topic           TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'missing',     -- strong | developing | weak | missing
    why             TEXT,                                -- the explanation (never a source count)
    claims_total    INTEGER NOT NULL DEFAULT 0,
    claims_strong   INTEGER NOT NULL DEFAULT 0,
    targets_open    INTEGER NOT NULL DEFAULT 0,
    tensions_open   INTEGER NOT NULL DEFAULT 0,
    evidence_classes TEXT,                               -- JSON: classes present
    missing_perspectives TEXT,                           -- JSON
    updated_at      REAL NOT NULL,
    PRIMARY KEY (project_id, topic)
);
CREATE TABLE IF NOT EXISTS research_tensions (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,                       -- NOVEL | CONTRADICTION | WEAK_CONSENSUS | STALE | MISSING_PERSPECTIVE
    claim_id        TEXT REFERENCES project_claims(id) ON DELETE CASCADE,
    related_claim_id TEXT,
    target_id       TEXT,
    description     TEXT NOT NULL,
    evidence        TEXT,                                -- JSON
    impact          TEXT NOT NULL DEFAULT 'medium',      -- high | medium | low
    status          TEXT NOT NULL DEFAULT 'open',        -- open | resolved | dismissed
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tensions_project ON research_tensions(project_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS ix_tensions_identity ON research_tensions(project_id, kind, claim_id, COALESCE(related_claim_id, ''));

-- G6 (0.31.0): Canonical Works. GLOBAL identity (work family) → GLOBAL version/edition (first-class when it changes what is
-- authoritative) → GLOBAL manifestation (an obtainable representation, possessed or not) → PROJECT relevance (project_works —
-- never on the Work row). Independence of Claim evidence is computed by lineage (work_id), not source count.
CREATE TABLE IF NOT EXISTS works (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL DEFAULT 'other',    -- book | paper | statute | regulation | sop | publication | standard | report | course | series | dataset | other
    title         TEXT NOT NULL,
    title_norm    TEXT NOT NULL,
    creators      TEXT,                             -- JSON list
    publisher     TEXT,
    identifiers   TEXT,                             -- JSON list of {scheme, value}
    resolution    TEXT NOT NULL DEFAULT 'stub',     -- stub (named by a citation) | resolved (identity confirmed by an identifier or exact metadata)
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_works_title ON works(title_norm);
CREATE TABLE IF NOT EXISTS work_identifiers (
    scheme   TEXT NOT NULL,                         -- isbn | doi | issn | docnum | sop | citation | pub | url
    value    TEXT NOT NULL,                         -- normalized
    work_id  TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    version_id TEXT,                                -- when the identifier names a specific version (SOP 50 10 8, ISBN of an edition)
    PRIMARY KEY (scheme, value)
);
CREATE TABLE IF NOT EXISTS work_versions (
    id             TEXT PRIMARY KEY,
    work_id        TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    label          TEXT NOT NULL,                   -- "SOP 50 10 8", "2nd edition", "tax year 2026"
    edition        TEXT,
    year           TEXT,
    effective_date TEXT,
    supersedes_id  TEXT,                            -- the version this one replaces (revision_of)
    change_kind    TEXT NOT NULL DEFAULT 'unknown', -- relative to supersedes_id: unknown | supersedes | material | rehost | formatting
    change_note    TEXT,                            -- which provisions changed (when known)
    status         TEXT NOT NULL DEFAULT 'unknown', -- current | superseded | unknown
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_work_versions_work ON work_versions(work_id);
CREATE TABLE IF NOT EXISTS work_manifestations (
    id            TEXT PRIMARY KEY,
    work_id       TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    version_id    TEXT REFERENCES work_versions(id) ON DELETE SET NULL,
    source_id     TEXT REFERENCES sources(id) ON DELETE CASCADE,          -- possessed representation (global source)
    candidate_id  TEXT REFERENCES candidates(id) ON DELETE SET NULL,      -- seen, not acquired
    relation      TEXT NOT NULL DEFAULT 'manifestation_of',               -- manifestation_of | reprint_of | translation_of | revision_of | excerpt_of | summary_of | quotes | derivative_of | cites | implements | interprets | possible_manifestation_of
    form          TEXT,                                                   -- official | mirror | html | excerpt | ocr | scan | reprint | translation | summary | derivative
    access        TEXT NOT NULL DEFAULT 'unknown',                        -- owned | candidate | unavailable | unknown
    url           TEXT,
    confidence    TEXT NOT NULL DEFAULT 'identifier',                     -- identifier | exact_metadata | publisher_metadata | model | possible
    basis         TEXT,                                                   -- JSON: how the link was established
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_work_manifestations_work ON work_manifestations(work_id);
CREATE INDEX IF NOT EXISTS ix_work_manifestations_source ON work_manifestations(source_id);
-- G7 (0.32.0): community threads are ONE source each (platform 'community'); posts/comments are evidence locators with
-- retrieval/edit/deletion state, corrections attached to what they correct, self-described context never verified.
CREATE TABLE IF NOT EXISTS candidate_links (                              -- B3: why a known-but-not-captured source matters to a project
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,                 -- evidence_target | claim | tension | mission | discovery
    ref_id       TEXT NOT NULL,
    relevance    INTEGER,
    why          TEXT,
    state        TEXT NOT NULL DEFAULT 'open',  -- open | satisfied (acquired) | dismissed (user: not important)
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    PRIMARY KEY (candidate_id, project_id, kind, ref_id)
);
CREATE INDEX IF NOT EXISTS ix_candidate_links_ref ON candidate_links(project_id, kind, ref_id, state);
CREATE TABLE IF NOT EXISTS book_sections (                                -- G6P1: an EPUB's structure; ordinal = the segment locator
    source_id    TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,
    spine_index  INTEGER NOT NULL,
    href         TEXT,
    fragment     TEXT,                          -- the anchor inside the content document (deep link without re-ingestion)
    chapter      TEXT,
    chapter_no   INTEGER,
    section      TEXT,
    role         TEXT,                          -- title_page | copyright | preface | introduction | part | chapter | appendix | notes | bibliography | index | body | back_matter …
    depth        INTEGER NOT NULL DEFAULT 0,
    label        TEXT NOT NULL,                 -- the human citation: "Ch. 3 → Disruptive Technological Change · Section"
    chars        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source_id, ordinal)
);
CREATE TABLE IF NOT EXISTS community_posts (
    source_id       TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    post_id         TEXT NOT NULL,                  -- platform id
    parent_id       TEXT,
    ordinal         INTEGER NOT NULL,               -- locator ('post N'), stable per revision
    depth           INTEGER NOT NULL DEFAULT 0,
    kind            TEXT NOT NULL DEFAULT 'comment', -- post | comment
    author          TEXT,
    claimed_context TEXT,                           -- JSON {context, basis: 'self-described in the post', verified: false}
    score           INTEGER,
    created         REAL,
    edited          INTEGER NOT NULL DEFAULT 0,
    deleted         INTEGER NOT NULL DEFAULT 0,
    availability    TEXT NOT NULL DEFAULT 'available', -- available | unavailable (previously retrieved, now gone)
    text            TEXT,
    permalink       TEXT,
    corrected_by    TEXT,                           -- post_id of the reply that corrects this one
    acknowledged    INTEGER NOT NULL DEFAULT 0,     -- the author accepted the correction
    firsthand       INTEGER NOT NULL DEFAULT 0,
    disagreement    INTEGER NOT NULL DEFAULT 0,
    quantitative    INTEGER NOT NULL DEFAULT 0,
    evidence_links  TEXT,                           -- JSON list of URLs the post cites
    injection       INTEGER NOT NULL DEFAULT 0,     -- instruction-like text detected: quoted as data, never followed
    in_chunks       INTEGER NOT NULL DEFAULT 0,     -- survived pruning → became retrievable evidence
    retrieved_at    REAL NOT NULL,
    last_seen_revision TEXT,
    PRIMARY KEY (source_id, post_id)
);
CREATE INDEX IF NOT EXISTS ix_community_posts_ordinal ON community_posts(source_id, ordinal);
CREATE TABLE IF NOT EXISTS community_syntheses (                          -- derived cross-thread states; never primary evidence
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,                  -- FREQUENTLY_REPORTED | MIXED_EXPERIENCE | STRONG_DISAGREEMENT | RARE_BUT_SERIOUS | FIRSTHAND_EXAMPLES
    claim_id        TEXT,
    statement       TEXT NOT NULL,
    independent_lines INTEGER NOT NULL DEFAULT 0,
    supporting      INTEGER NOT NULL DEFAULT 0,
    contradicting   INTEGER NOT NULL DEFAULT 0,
    evidence        TEXT,                           -- JSON: exact evidence links (source, locator, permalink, relation, independent)
    created_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_works (                               -- project-relative relevance/use only
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    work_id     TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    relevance   TEXT NOT NULL DEFAULT 'relevant',   -- attached | relevant | targeted | dismissed
    reason      TEXT,
    target_id   TEXT,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (project_id, work_id)
);

CREATE TABLE IF NOT EXISTS circuit_breakers (
    operation       TEXT PRIMARY KEY,         -- provider:operation, e.g. anthropic:messages (never per model)
    state           TEXT NOT NULL DEFAULT 'closed',   -- closed | open | half_open
    failures        INTEGER NOT NULL DEFAULT 0,       -- consecutive transient failures (reset by any success)
    opened_at       REAL,
    next_probe_at   REAL,                     -- honours the provider's retry-after when it gave one
    last_error_type TEXT,
    last_error_at   REAL,
    last_success_at REAL,
    probe_owner     TEXT,                     -- the ONE worker allowed to probe while half_open
    probe_expires_at REAL,
    generation      INTEGER NOT NULL DEFAULT 0,       -- bumped on every open: a stale worker cannot close a newer circuit
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS window_decisions (
    id             INTEGER PRIMARY KEY,
    project_id     TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    window_index   INTEGER NOT NULL,
    windows        INTEGER NOT NULL,
    input_hash     TEXT NOT NULL,             -- window text + brief revision + prefilter prompt/schema/model: any change re-evaluates
    decision       TEXT NOT NULL,             -- keep | uncertain | drop
    reason         TEXT,
    fail_open      TEXT,                      -- NULL when the model decided; else why the decision fell open to 'uncertain'
    model          TEXT,                      -- model as returned (provenance)
    configured_model TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    window_chars   INTEGER,
    sample_chars   INTEGER,                   -- how much of the window the filter read
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cost           REAL,
    created_at     REAL NOT NULL,
    UNIQUE(project_id, source_id, window_index, input_hash)
);
CREATE INDEX IF NOT EXISTS ix_window_decisions_src ON window_decisions(project_id, source_id);

CREATE TABLE IF NOT EXISTS validation_events (
    id          INTEGER PRIMARY KEY,
    ts          REAL NOT NULL,
    kind        TEXT NOT NULL,      -- finding_validation_failed | citation_validation_failed | citation_repaired | plan_evidence_removed
    project_id  TEXT,
    source_id   TEXT,
    job_id      TEXT,
    model       TEXT,
    prompt_version TEXT,
    detail      TEXT                -- JSON: the rejected candidate / the offending markers / the removed ids
);
CREATE INDEX IF NOT EXISTS ix_validation_events_ts ON validation_events(ts);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    title      TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    citations       TEXT,   -- JSON
    created_at      REAL NOT NULL
);

-- Mission BOOTSTRAP (R2): what the library already holds that a NEW project could use. A suggestion row, never a
-- membership row: attaching is still `project_sources`, and this table records only that we proposed it, why, and
-- what the user decided. Follows the established relationship-row pattern (project_source_analysis,
-- candidate_projects, project_works): global object identity on one side, project-specific state on the other.
-- object_kind is 'source' today; findings and claims are later rungs and deliberately absent (see
-- BOOTSTRAP-MISSION.md §B2 — a finding is an interpretation and does not cross a project boundary).
CREATE TABLE IF NOT EXISTS project_reuse (
    project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    object_kind    TEXT NOT NULL,                        -- source
    object_id      TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'suggested',    -- suggested | attached | dismissed | retired (0.61.0: a re-scan no longer makes it)
    band           TEXT,                                 -- strong | possible
    score          REAL,
    why            TEXT,                                 -- JSON {passages, terms, coverage} — the matched passages, never an adjective
    origin         TEXT,                                 -- JSON {queries}
    brief_revision TEXT,                                 -- which goal/brief this judgement was made against
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL,
    PRIMARY KEY (project_id, object_kind, object_id)
);
CREATE INDEX IF NOT EXISTS ix_project_reuse_state ON project_reuse(project_id, state, band);

-- P11 EA-1 (EXTERNAL-AI-ACCESS-MISSION.md §40–§43, docs/P11-EXECUTION-PLAN-2026-09-22.md §2): external principals.
-- An ACTOR is a person (or 'system'); a CLIENT is an LLM product/connection; a CREDENTIAL binds exactly one
-- (actor, client) pair, so "Gio using ChatGPT" and "Kyle using ChatGPT" are two credentials and never a header the
-- caller can forge. init_db seeds actor 'kyle' (the local owner: user-initiated actions behind the legacy app token)
-- and actor 'system' (background/derived work) -- automatic work is never attributed to a person (Kyle, 2026-09-22).
CREATE TABLE IF NOT EXISTS external_actors (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'person',     -- person | system
    created_at  REAL NOT NULL,
    disabled_at REAL
);
CREATE TABLE IF NOT EXISTS external_clients (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL,                     -- a free label ("Gio's ChatGPT"); never a vendor enum (§63)
    capabilities TEXT NOT NULL DEFAULT '{}',        -- JSON, external_schemas.CAPABILITIES, as last declared by the client
    transport    TEXT NOT NULL DEFAULT 'local',     -- local | lan | tunnel (§62)
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS external_credentials (
    id            TEXT PRIMARY KEY,
    actor_id      TEXT NOT NULL REFERENCES external_actors(id),
    client_id     TEXT NOT NULL REFERENCES external_clients(id),
    token_prefix  TEXT NOT NULL UNIQUE,             -- first 12 chars of the secret: the lookup key and the ONLY part ever logged
    token_hash    TEXT NOT NULL,                    -- sha256 of the secret; the secret is shown once at creation and never stored
    created_at    REAL NOT NULL,
    created_by    TEXT,
    expires_at    REAL,
    last_used_at  REAL,
    revoked_at    REAL,
    revoked_by    TEXT,
    revoke_reason TEXT,
    rotated_from  TEXT
);
-- ACL on the ACTOR (survives credential rotation). A new grant is ALWAYS standard-only; every further disclosure class
-- is a deliberate owner opt-in per grant (Kyle, 2026-09-22). Project access is never permission to disclose everything (§41).
CREATE TABLE IF NOT EXISTS external_project_grants (
    id                 INTEGER PRIMARY KEY,
    project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor_id           TEXT NOT NULL REFERENCES external_actors(id),
    role               TEXT NOT NULL,                        -- read | contribute | owner (§40 presets)
    disclosure_classes TEXT NOT NULL DEFAULT '["standard"]', -- JSON list
    extra_permissions  TEXT NOT NULL DEFAULT '[]',           -- JSON; explicit grants only
    granted_by         TEXT,
    granted_at         REAL NOT NULL,
    updated_at         REAL,
    revoked_at         REAL,
    revoked_by         TEXT,
    UNIQUE(project_id, actor_id)
);
-- Every owner change to an object's disclosure class (§41: lowering one is an owner-only, audited act).
CREATE TABLE IF NOT EXISTS disclosure_audit (
    id          INTEGER PRIMARY KEY,
    object_type TEXT NOT NULL,          -- source | fact
    object_id   TEXT NOT NULL,
    from_class  TEXT,
    to_class    TEXT NOT NULL,
    actor_id    TEXT,
    reason      TEXT,
    created_at  REAL NOT NULL
);
-- External request audit for Health (§64) and the revocation boundary (§61). Outcome codes only: no payloads, no
-- secrets. Pruned to EXTERNAL_REQUEST_RETENTION_S by access.record_request.
CREATE TABLE IF NOT EXISTS external_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_id TEXT,
    actor_id      TEXT,
    client_id     TEXT,
    operation     TEXT NOT NULL,
    project_id    TEXT,
    outcome       TEXT NOT NULL,        -- ok | auth_invalid | auth_revoked | project_unauthorized | forbidden | disclosure_denied | capability_missing | conflict | invalid | rate_limited | error
    detail        TEXT,
    duration_ms   INTEGER,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_external_requests_client ON external_requests(client_id, created_at);

-- P11 EA-2 (§44–§48, §60): the project change ledger. Append-only; the domain tables stay the current-state
-- authority (this is never read back to rebuild state). Written ONLY by ledger.record(), inside the writer's own
-- transaction, and only when a tracked field actually changed (or an explicit reaffirmation, §47). actor_id is never
-- NULL: 'system' for automatic work, with originating_* naming the person/request that caused it (Kyle, 2026-09-22).
CREATE TABLE IF NOT EXISTS project_change_events (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id             TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type             TEXT NOT NULL,
    object_type            TEXT NOT NULL,
    object_id              TEXT NOT NULL,
    actor_id               TEXT NOT NULL,
    external_client_id     TEXT,        -- the client that submitted it on the actor's behalf; NULL for local surfaces
    local_surface          TEXT,        -- ui | api | cli | mcp_legacy | job — how a local act arrived
    intake_id              TEXT,
    request_id             TEXT,
    originating_actor_id   TEXT,
    originating_request_id TEXT,
    before                 TEXT,        -- JSON: tracked fields only, bounded (ledger.MAX_PAYLOAD_BYTES)
    after                  TEXT,
    disclosure_floor       TEXT NOT NULL DEFAULT '["restricted"]',   -- JSON list: every class before/after exposes (§44)
    materiality            TEXT,        -- material | supporting | none — filled after commit (ledger.classify_pending)
    decision_impact        TEXT,        -- JSON or NULL — filled after commit
    created_at             REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pce_project_id ON project_change_events(project_id, id);
CREATE INDEX IF NOT EXISTS ix_pce_object ON project_change_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS ix_pce_unclassified ON project_change_events(materiality) WHERE materiality IS NULL;

-- P11 EA-4 (§52, §55): one external turn = one intake EVENT grouping several distinct items. Idempotent on the
-- client's own request id; an item and its processing job are created in one transaction (intake._new_item, the
-- create_or_get_capture_ingest_request idiom). The Project Inbox is a view over these two tables, not a queue.
CREATE TABLE IF NOT EXISTS external_intakes (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    actor_id            TEXT NOT NULL,
    client_id           TEXT NOT NULL,
    credential_id       TEXT NOT NULL,
    client_request_id   TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'received',   -- received | routing | queued | processing | ready | needs_review | failed
    needs_review_reason TEXT,
    error               TEXT,
    base_revision       TEXT,                               -- the ledger cursor the client reasoned against (§51)
    conversation_ref    TEXT,                               -- opaque client thread id; never parsed
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    finalized_at        REAL,
    UNIQUE(client_id, client_request_id)
);
CREATE INDEX IF NOT EXISTS ix_external_intakes_project ON external_intakes(project_id, created_at);
CREATE TABLE IF NOT EXISTS intake_items (
    id                TEXT PRIMARY KEY,
    intake_id         TEXT NOT NULL REFERENCES external_intakes(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,          -- raw_artifact | processed_material | user_state | interpretation
    material_type     TEXT,                   -- image | pdf | url | correspondence | spreadsheet | transcript | text (§54)
    artifact_ref      TEXT,                   -- JSON {kind: multipart | signed_url | …}
    sha256            TEXT,
    bytes             INTEGER,
    content_type      TEXT,
    producer          TEXT,                   -- who extracted it (§53): the client's label, never assumed to be Neuro
    extraction_method TEXT,
    confidence        REAL,
    payload           TEXT,                   -- JSON: processed material / interpretation text / retention path
    source_id         TEXT,                   -- the Neuro source it became (may be an EXISTING one: dedupe)
    ingest_job_id     TEXT,                   -- written in the SAME insert that creates the item
    fact_id           INTEGER,
    status            TEXT NOT NULL DEFAULT 'received',
    error             TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_intake_items_intake ON intake_items(intake_id);

-- P11 EA-7 (§40, plan §8): OAuth 2.1 for clients that cannot hold a static credential (ChatGPT authenticates custom
-- MCP servers only via OAuth, verified 2026-09-22). The PERSON is bound by an owner-issued, single-use connection
-- invite entered at consent time; each completed connection becomes one external_clients row + one credential, and
-- every OAuth token resolves to that credential — so revoking it in the Access card ends the connection.
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id     TEXT PRIMARY KEY,           -- ours for DCR; the metadata URL itself for CIMD
    client_name   TEXT,
    redirect_uris TEXT NOT NULL,              -- JSON list, exact-match only
    kind          TEXT NOT NULL,              -- dcr | cimd
    metadata      TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS external_invites (
    id          TEXT PRIMARY KEY,
    actor_id    TEXT NOT NULL REFERENCES external_actors(id),
    code_prefix TEXT NOT NULL UNIQUE,
    code_hash   TEXT NOT NULL,
    label       TEXT,
    created_by  TEXT,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    used_at     REAL,
    used_client_id TEXT,
    revoked_at  REAL
);
CREATE TABLE IF NOT EXISTS oauth_codes (
    code_hash      TEXT PRIMARY KEY,
    oauth_client_id TEXT NOT NULL,
    credential_id  TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    scope          TEXT,
    resource       TEXT,
    expires_at     REAL NOT NULL,
    used_at        REAL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id              TEXT PRIMARY KEY,
    token_prefix    TEXT NOT NULL UNIQUE,
    token_hash      TEXT NOT NULL,
    kind            TEXT NOT NULL,            -- access | refresh
    credential_id   TEXT NOT NULL,
    oauth_client_id TEXT NOT NULL,
    scope           TEXT,
    created_at      REAL NOT NULL,
    expires_at      REAL NOT NULL,
    revoked_at      REAL
);
CREATE INDEX IF NOT EXISTS ix_oauth_tokens_credential ON oauth_tokens(credential_id);
-- P11 EA-9 correction: an identity at an EXTERNAL identity provider (issuer + subject) bound to one Neuro credential.
-- Bound only by the person redeeming an owner-issued invite; an unbound identity can do nothing but link itself.
CREATE TABLE IF NOT EXISTS external_identities (
    issuer        TEXT NOT NULL,
    subject       TEXT NOT NULL,
    credential_id TEXT NOT NULL REFERENCES external_credentials(id),
    invite_id     TEXT,
    linked_at     REAL NOT NULL,
    PRIMARY KEY (issuer, subject)
);

-- A verified provider sign-in that no Neuro person has claimed yet (2026-09-22). ChatGPT's credential-safety
-- layer blocks `nsi_…` codes in chat before `link_account` is ever sent, so a code the user pastes cannot be the
-- link path for that client. The owner approves the sign-in in Neuro instead. Recording it costs nothing and
-- proves only what the provider already proved: that this (issuer, subject) presented a valid token.
CREATE TABLE IF NOT EXISTS external_pending_signins (
    issuer       TEXT NOT NULL,
    subject      TEXT NOT NULL,
    email        TEXT,
    client_hint  TEXT,
    first_seen   REAL NOT NULL,
    last_seen    REAL NOT NULL,
    seen_count   INTEGER NOT NULL DEFAULT 1,
    dismissed_at REAL,
    resolved_at  REAL,
    resolved_actor TEXT,
    PRIMARY KEY (issuer, subject)
);
"""

_local = threading.local()


BRIDGE_MOUNT_MARKERS = ("/sessions/", "/mnt/")   # a Cowork/Claude device-bridge sandbox sees the Mac's folder at /sessions/<id>/mnt/<folder>/


def refuse_bridge_mount(path: str | os.PathLike[str]) -> None:
    """CLAUDE.md standing rule #1, made mechanical (2026-09-14). A SQLite WAL database opened through a bridge mount
    from another VM does not see the server's POSIX locks, believes it is the only connection, and truncates the
    -shm index underneath the running app on close -- the server's next shm page read is past EOF and macOS kills it
    with SIGBUS. That crashed the live server twice on 2026-09-11 and THREE times on 2026-09-14 (every crash blamed
    on the machine at the time), then corrupted the database. Reading is enough to do it; `mode=ro` does not help.
    Refuse here, where every connection starts, instead of relying on the next session having read the rule.
    NEUROSEARCH_ALLOW_BRIDGE_DB=1 is the escape hatch for someone who has read this and is opening a COPY."""
    if os.environ.get("NEUROSEARCH_ALLOW_BRIDGE_DB") == "1":
        return
    resolved = os.path.realpath(str(path))
    if all(m in resolved for m in BRIDGE_MOUNT_MARKERS):
        raise RuntimeError(
            f"refusing to open {resolved}: this is the live database reached through a sandbox bridge mount. "
            "Opening it from here (even read-only) crashes the running app and can corrupt the file -- CLAUDE.md, "
            "standing rule #1. Use the app's API, the neurosearch CLI on the Mac, or cp a data/backups/ snapshot "
            "into the session's own workspace and open the copy. NEUROSEARCH_ALLOW_BRIDGE_DB=1 overrides, on purpose.")


def connect() -> sqlite3.Connection:
    """Thread-local connection, self-healing against a mid-process data_dir change.

    S51-c (2026-09-16): a THREAD other than the one a test's own fixture teardown runs on can hold the stale
    connection -- proven live: FastAPI sync route handlers run via Starlette's anyio threadpool, a pool of
    worker threads reused across requests/tests. A test file's autouse fixture that swaps settings.data_dir for
    the duration of one test (e.g. tests/test_r2_bootstrap.py's `_fresh`) resets db._local.conn on the MAIN
    thread only -- it has no way to reach whichever anyio worker thread actually served that test's client.*()
    calls and opened ITS OWN connection to the swapped dir. That worker thread is later reused by an unrelated
    test's client.*() call and still returns the swapped-away database. Reproduced outside pytest and bisected
    to this exact mechanism (see HANDOFF.md, 2026-09-16) before this fix landed.
    In production settings.data_dir never changes after startup, so `bound_db_path` and the freshly resolved
    `db_path` always agree there -- this is a no-op in production and only self-heals the test-only path swap,
    on whichever thread happens to notice, not just the one that performed the swap."""
    conn = getattr(_local, "conn", None)
    db_path = str(getattr(_local, "db_path", settings.db_path))
    if conn is not None and getattr(_local, "bound_db_path", None) != db_path:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        conn = None
        _local.conn = None
    if conn is None:
        refuse_bridge_mount(db_path)
        conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA cache_size=-{SQLITE_CACHE_KIB}")
        conn.execute(f"PRAGMA mmap_size={SQLITE_MMAP_BYTES}")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute(f"PRAGMA journal_size_limit={WAL_LIMIT_BYTES}")   # 0.61.2: give the log file back after a checkpoint
        _local.conn = conn
        _local.bound_db_path = db_path
    return conn


def close_thread_connection() -> None:
    """Close only the current thread's connection; never open a DB during cleanup."""
    conn = getattr(_local, "conn", None)
    try:
        if conn is not None:
            conn.close()
    finally:
        _local.conn = None
        _local.__dict__.pop("bound_db_path", None)


MIGRATIONS = [
    ("projects", "context", "ALTER TABLE projects ADD COLUMN context TEXT"),
    ("source_captures", "capture_partial_reason", "ALTER TABLE source_captures ADD COLUMN capture_partial_reason TEXT"),
    ("source_captures", "client_capture_id", "ALTER TABLE source_captures ADD COLUMN client_capture_id TEXT"),
    ("source_captures", "ingest_job_id", "ALTER TABLE source_captures ADD COLUMN ingest_job_id TEXT"),
    ("project_notes", "status", "ALTER TABLE project_notes ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'"),
    ("project_notes", "source_id", "ALTER TABLE project_notes ADD COLUMN source_id TEXT"),
    ("project_notes", "importance", "ALTER TABLE project_notes ADD COLUMN importance INTEGER"),
    ("project_notes", "title", "ALTER TABLE project_notes ADD COLUMN title TEXT"),
    # 2026-09-21: when a status was last set DELIBERATELY. Nothing recorded this, so "approved" could not be
    # told apart from "defaulted to approved" -- the column itself arrived with DEFAULT 'approved', and Kyle
    # bulk-approved most of the rest. 17,193 approved findings was therefore not 17,193 judgements, and a
    # second-look pass had no way to know where it had already been. NULL means exactly that: never explicitly
    # ruled on. Every existing row starts NULL, which is the truthful answer for all of them.
    ("project_notes", "reviewed_at", "ALTER TABLE project_notes ADD COLUMN reviewed_at REAL"),
    ("sources", "summary", "ALTER TABLE sources ADD COLUMN summary TEXT"),
    ("sources", "substance", "ALTER TABLE sources ADD COLUMN substance INTEGER"),
    ("project_sources", "suggested_at", "ALTER TABLE project_sources ADD COLUMN suggested_at REAL"),
    ("jobs", "not_before", "ALTER TABLE jobs ADD COLUMN not_before REAL"),
    ("projects", "mode", "ALTER TABLE projects ADD COLUMN mode TEXT NOT NULL DEFAULT 'research'"),
    ("projects", "goal", "ALTER TABLE projects ADD COLUMN goal TEXT"),
    ("projects", "audience", "ALTER TABLE projects ADD COLUMN audience TEXT"),
    ("projects", "output_pref", "ALTER TABLE projects ADD COLUMN output_pref TEXT"),
    ("projects", "source_prefs", "ALTER TABLE projects ADD COLUMN source_prefs TEXT"),
    ("projects", "questions", "ALTER TABLE projects ADD COLUMN questions TEXT"),
    ("project_claims", "freshness_status", "ALTER TABLE project_claims ADD COLUMN freshness_status TEXT NOT NULL DEFAULT 'uncertain'"),
    ("project_claims", "freshness_why", "ALTER TABLE project_claims ADD COLUMN freshness_why TEXT"),
    ("claim_evidence", "lineage_id", "ALTER TABLE claim_evidence ADD COLUMN lineage_id TEXT"),
    ("sources", "view_count", "ALTER TABLE sources ADD COLUMN view_count INTEGER"),
    ("sources", "relevance", "ALTER TABLE sources ADD COLUMN relevance INTEGER"),
    ("sources", "relevance_why", "ALTER TABLE sources ADD COLUMN relevance_why TEXT"),
    ("jobs", "updated_at", "ALTER TABLE jobs ADD COLUMN updated_at REAL"),
    ("usage", "cache_read", "ALTER TABLE usage ADD COLUMN cache_read INTEGER DEFAULT 0"),
    ("usage", "cache_write", "ALTER TABLE usage ADD COLUMN cache_write INTEGER DEFAULT 0"),
    ("usage", "saved", "ALTER TABLE usage ADD COLUMN saved REAL DEFAULT 0"),
    ("messages", "meta", "ALTER TABLE messages ADD COLUMN meta TEXT"),
    ("sources", "revision", "ALTER TABLE sources ADD COLUMN revision TEXT"),
    ("project_notes", "model", "ALTER TABLE project_notes ADD COLUMN model TEXT"),
    ("project_notes", "prompt_version", "ALTER TABLE project_notes ADD COLUMN prompt_version TEXT"),
    ("project_notes", "source_revision", "ALTER TABLE project_notes ADD COLUMN source_revision TEXT"),
    ("project_notes", "brief_revision", "ALTER TABLE project_notes ADD COLUMN brief_revision TEXT"),
    ("plans", "model", "ALTER TABLE plans ADD COLUMN model TEXT"),
    ("plans", "prompt_version", "ALTER TABLE plans ADD COLUMN prompt_version TEXT"),
    ("plans", "brief_revision", "ALTER TABLE plans ADD COLUMN brief_revision TEXT"),
    ("plans", "facts_revision", "ALTER TABLE plans ADD COLUMN facts_revision TEXT"),
    ("plans", "source_set_revision", "ALTER TABLE plans ADD COLUMN source_set_revision TEXT"),
    ("discoveries", "model", "ALTER TABLE discoveries ADD COLUMN model TEXT"),
    ("discoveries", "prompt_version", "ALTER TABLE discoveries ADD COLUMN prompt_version TEXT"),
    ("discoveries", "brief_revision", "ALTER TABLE discoveries ADD COLUMN brief_revision TEXT"),
    ("project_notes", "input_hash", "ALTER TABLE project_notes ADD COLUMN input_hash TEXT"),
    ("jobs", "blocked_by", "ALTER TABLE jobs ADD COLUMN blocked_by TEXT"),
    ("jobs", "run_id", "ALTER TABLE jobs ADD COLUMN run_id TEXT"),
    ("jobs", "worker_id", "ALTER TABLE jobs ADD COLUMN worker_id TEXT"),
    ("jobs", "claimed_at", "ALTER TABLE jobs ADD COLUMN claimed_at REAL"),
    ("jobs", "heartbeat_at", "ALTER TABLE jobs ADD COLUMN heartbeat_at REAL"),
    ("jobs", "lease_until", "ALTER TABLE jobs ADD COLUMN lease_until REAL"),
    ("jobs", "cancel_requested_at", "ALTER TABLE jobs ADD COLUMN cancel_requested_at REAL"),
    ("jobs", "pause_requested_at", "ALTER TABLE jobs ADD COLUMN pause_requested_at REAL"),     # S86: per-job pause
    ("jobs", "wait_reason", "ALTER TABLE jobs ADD COLUMN wait_reason TEXT"),
    # L1 Local-First AI: intent (execution_policy: local_preferred | local_only | api_requested | api_only) and outcome (executed_by,
    # fallback_reason) are separate columns — a job that meant local and ran on the API says so
    ("jobs", "execution_policy", "ALTER TABLE jobs ADD COLUMN execution_policy TEXT NOT NULL DEFAULT 'local_preferred'"),
    ("jobs", "executed_by", "ALTER TABLE jobs ADD COLUMN executed_by TEXT"),
    ("jobs", "fallback_reason", "ALTER TABLE jobs ADD COLUMN fallback_reason TEXT"),
    ("jobs", "lane", "ALTER TABLE jobs ADD COLUMN lane TEXT NOT NULL DEFAULT 'normal'"),   # 0.42.1: 'slow' = long-running local work (Read deeper) that must not hog the pool; 0.45.9: 'priority' = claimed ahead of 'normal', for short jobs a user is actively waiting on (e.g. ranking a review card); 0.45.10: 'low' = claimed only once nothing priority/normal/slow is waiting, for speculative work on content not yet known to matter (e.g. backfilling metadata for skipped sources) — never changes cost/provider, only queue order
    ("jobs", "bumped_at", "ALTER TABLE jobs ADD COLUMN bumped_at REAL"),   # 0.45.12: a user's explicit "run this next" — outranks every lane, FIFO among bumps, cleared once claimed (one-shot, never a permanent pin)
    ("jobs", "wait_operation", "ALTER TABLE jobs ADD COLUMN wait_operation TEXT"),
    ("jobs", "attempts", "ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"),
    ("jobs", "dedupe_key", "ALTER TABLE jobs ADD COLUMN dedupe_key TEXT"),
    ("jobs", "dependency_policy", "ALTER TABLE jobs ADD COLUMN dependency_policy TEXT"),
    ("jobs", "external_provider", "ALTER TABLE jobs ADD COLUMN external_provider TEXT"),
    ("jobs", "external_kind", "ALTER TABLE jobs ADD COLUMN external_kind TEXT"),
    ("jobs", "external_handle", "ALTER TABLE jobs ADD COLUMN external_handle TEXT"),
    ("jobs", "external_submitted_at", "ALTER TABLE jobs ADD COLUMN external_submitted_at REAL"),
    ("jobs", "external_last_checked_at", "ALTER TABLE jobs ADD COLUMN external_last_checked_at REAL"),
    ("jobs", "external_deadline", "ALTER TABLE jobs ADD COLUMN external_deadline REAL"),
    ("sources", "stage", "ALTER TABLE sources ADD COLUMN stage TEXT"),
    ("sources", "audio_path", "ALTER TABLE sources ADD COLUMN audio_path TEXT"),
    ("invocations", "logical_id", "ALTER TABLE invocations ADD COLUMN logical_id TEXT"),
    ("invocations", "attempt_no", "ALTER TABLE invocations ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 1"),
    ("invocations", "error_type", "ALTER TABLE invocations ADD COLUMN error_type TEXT"),
    ("invocations", "returned_model", "ALTER TABLE invocations ADD COLUMN returned_model TEXT"),
    # Rung J3: the routing decision is audited on every invocation and every AI artifact (JSON: requested_model, actual_model, fallback_used, fallback_reason, fallback_policy_version)
    ("invocations", "fallback_used", "ALTER TABLE invocations ADD COLUMN fallback_used INTEGER NOT NULL DEFAULT 0"),
    ("invocations", "fallback_policy_version", "ALTER TABLE invocations ADD COLUMN fallback_policy_version TEXT"),
    ("project_source_analysis", "routing", "ALTER TABLE project_source_analysis ADD COLUMN routing TEXT"),
    ("project_notes", "routing", "ALTER TABLE project_notes ADD COLUMN routing TEXT"),
    ("plans", "routing", "ALTER TABLE plans ADD COLUMN routing TEXT"),
    ("discoveries", "routing", "ALTER TABLE discoveries ADD COLUMN routing TEXT"),
    # Rung G: transport-specific provenance (interactive | batch) — explicit, never hidden
    ("project_notes", "transport", "ALTER TABLE project_notes ADD COLUMN transport TEXT"),
    # 0.24.1: a project-relative "priority source" flag (the user's authority statement as structured state, not chat history);
    # retrieval reserves excerpt slots for priority sources. Sources that are in the project through a collection or tag
    # rather than a direct row are given a row when flagged (priority is a project relationship).
    ("project_sources", "priority", "ALTER TABLE project_sources ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"),
    ("project_sources", "excluded", "ALTER TABLE project_sources ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0"),   # 0.34.2: removed from THIS project — collections/tags/retries can no longer bring it back
    # G1 (0.25.0): stronger identity than (platform, external_id) alone — canonical URL and content fingerprint (see identity.py)
    ("sources", "canonical_url", "ALTER TABLE sources ADD COLUMN canonical_url TEXT"),
    ("sources", "content_fingerprint", "ALTER TABLE sources ADD COLUMN content_fingerprint TEXT"),
    ("sources", "error_class", "ALTER TABLE sources ADD COLUMN error_class TEXT"),           # B1: classified acquisition failure (browser_solvable:<cls> | <cls>)
    ("sources", "completeness", "ALTER TABLE sources ADD COLUMN completeness TEXT"),
    # 0.63.16: JSON list of the video players a captured page embeds. Recorded, never auto-fetched — a download
    # plus transcription costs money, so the page says what it holds and the user decides.
    ("sources", "video_embeds", "ALTER TABLE sources ADD COLUMN video_embeds TEXT"),
    ("community_syntheses", "coverage", "ALTER TABLE community_syntheses ADD COLUMN coverage TEXT"),   # B2: JSON — partial/unknown threads behind the state         # B2: JSON — captured vs expected, never "complete" by default
    ("project_notes", "batch_id", "ALTER TABLE project_notes ADD COLUMN batch_id TEXT"),
    ("project_source_analysis", "depth", "ALTER TABLE project_source_analysis ADD COLUMN depth TEXT"),   # D2: NULL = ordinary reading, 'deep' = Read deeper
    ("project_source_analysis", "accepted_hash", "ALTER TABLE project_source_analysis ADD COLUMN accepted_hash TEXT"),   # S1: the input hash the user accepted as still usable
    ("project_source_analysis", "accepted_at", "ALTER TABLE project_source_analysis ADD COLUMN accepted_at REAL"),
    ("project_source_analysis", "transport", "ALTER TABLE project_source_analysis ADD COLUMN transport TEXT"),
    ("project_source_analysis", "batch_id", "ALTER TABLE project_source_analysis ADD COLUMN batch_id TEXT"),
    ("usage", "transport", "ALTER TABLE usage ADD COLUMN transport TEXT"),
    ("project_source_analysis", "prefilter", "ALTER TABLE project_source_analysis ADD COLUMN prefilter TEXT"),
    ("project_source_analysis", "r6_wave", "ALTER TABLE project_source_analysis ADD COLUMN r6_wave TEXT"),
    ("project_source_analysis", "r6_provisional", "ALTER TABLE project_source_analysis ADD COLUMN r6_provisional INTEGER NOT NULL DEFAULT 0"),
    # 0.59.3: WHICH MODEL'S RATES PRODUCED THIS ROW'S DOLLARS. Normally the same as `model`, but never for a local
    # call: `usage.record_anthropic` writes the model the CLI returned into `model` while pricing the tokens at the
    # CONTRACT's API model (the avoided-spend figure is only meaningful against the model that would have run). Rows
    # written before this column therefore attribute Sonnet-priced dollars to a Haiku row, which is exactly the
    # shape of a wrong per-model verdict — so `cost_value.by_model` refuses to divide where the basis is unknown.
    ("usage", "price_model", "ALTER TABLE usage ADD COLUMN price_model TEXT"),
    # 0.62.3: when the provider's result arrived, which is the honest date for the spend it carries. `updated_at`
    # cannot serve — it moves again when the item becomes `materialized`, so by the time the ledger row is written
    # the collection moment has been overwritten.
    ("batch_items", "result_at", "ALTER TABLE batch_items ADD COLUMN result_at REAL"),
    # 0.60.2: whether a suggested URL actually resolves. Discover proposes sources from a model's memory, and a
    # remembered address goes stale — Kyle: "discover is routinely suggesting content that has 404 issues".
    ("discoveries", "link_check", "ALTER TABLE discoveries ADD COLUMN link_check TEXT"),
    # Schema compatibility: 0.61.0 added derived-object embedding columns. Its dormant semantic-scoring prototype
    # was removed in 0.63.36 because it had no product/API path and contradicted current active-only, multi-signal
    # research policy. Keep the additive columns so existing databases and downgrade paths remain compatible.
    ("project_notes", "embedding", "ALTER TABLE project_notes ADD COLUMN embedding BLOB"),
    ("project_claims", "embedding", "ALTER TABLE project_claims ADD COLUMN embedding BLOB"),
    # P0.3 (docs/SPEED-AUDIT-2026-09-17.md): how many characters the source's transcript holds — the SAME number
    # `ingest.caption_recovery_candidates` used to recompute per source on every Sources poll by loading every
    # segment of ~770 sources (601k rows / 22 MB, p50 186 s under load). Maintained by `replace_transcript`, the
    # one place segments are written; backfilled once at startup for rows written before the column existed.
    ("sources", "spoken_chars", "ALTER TABLE sources ADD COLUMN spoken_chars INTEGER"),
    # 2026-09-18 (Kyle): "youtube members-only videos are not ranked above other videos." Who may watch: NULL for a
    # public video; members_only / premium / needs_auth from the listing's own `availability`, or from the ingest
    # error when the listing did not say. A gated video sorts LAST in a review, is never auto-ticked and is never
    # sent to the ranker — it cannot be downloaded without the person's own membership, so it must never take a
    # slot from a video that can.
    ("sources", "access_gate", "ALTER TABLE sources ADD COLUMN access_gate TEXT"),
    # T1: versioned derived vectors. Legacy bare blobs remain unreadable for similarity until these fields are set.
    ("project_notes", "embedding_provider", "ALTER TABLE project_notes ADD COLUMN embedding_provider TEXT"),
    ("project_notes", "embedding_model", "ALTER TABLE project_notes ADD COLUMN embedding_model TEXT"),
    ("project_notes", "embedding_dimensions", "ALTER TABLE project_notes ADD COLUMN embedding_dimensions INTEGER"),
    ("project_notes", "embedding_input_hash", "ALTER TABLE project_notes ADD COLUMN embedding_input_hash TEXT"),
    ("project_notes", "embedding_version", "ALTER TABLE project_notes ADD COLUMN embedding_version TEXT"),
    ("project_claims", "embedding_provider", "ALTER TABLE project_claims ADD COLUMN embedding_provider TEXT"),
    ("project_claims", "embedding_model", "ALTER TABLE project_claims ADD COLUMN embedding_model TEXT"),
    ("project_claims", "embedding_dimensions", "ALTER TABLE project_claims ADD COLUMN embedding_dimensions INTEGER"),
    ("project_claims", "embedding_input_hash", "ALTER TABLE project_claims ADD COLUMN embedding_input_hash TEXT"),
    ("project_claims", "embedding_version", "ALTER TABLE project_claims ADD COLUMN embedding_version TEXT"),
    # 0.60.5: which MATCHER produced this suggestion. 0.60.2 changed how library recall decides relevance, and the
    # rows already stored were produced by the old one — so Kyle's screen still offered an Airbnb video as a strong
    # match for AI UI/UX work after the fix shipped. A stored judgement has to know what made it.
    ("project_reuse", "scan_version", "ALTER TABLE project_reuse ADD COLUMN scan_version TEXT"),
    # LP3 (mission §12): which path proposed this plan_updates row -- NULL/'planner' = the existing LLM-based
    # suggest_updates(); 'lp3' = plan_narrative.propose_updates(), the $0 deterministic path over a stale/weak
    # Claim. Lets add_plan_updates scope its pending-row cleanup by origin so the two paths never clobber each
    # other's pending queue on the same plan.
    ("plan_updates", "origin", "ALTER TABLE plan_updates ADD COLUMN origin TEXT"),
    # LP5 (EXECUTION-LADDER.md, Kyle's overnight-mission correction 6): provenance for an accepted/rejected
    # plan-patch, verified genuinely missing (not assumed) against this table's live columns before adding them.
    # claim_id/tension_id: which Claim or tension this row's proposal traces back to (explain()/propose_updates()
    # already resolve this internally today but discard it before persisting -- LP0's stored-id lesson applies
    # here too: re-deriving it later from `reason` text would be lossy the same way decision_impact's fallback is).
    # decided_at/decided_by: when a pending row was accepted or rejected, and by whom (single-user app today, so
    # always 'user' -- kept as a column, not a constant, so a future multi-user mode never needs a schema change).
    # applied_plan_id: which regenerated plan (planner.apply_accepted_updates's build_plan() call) actually folded
    # this accepted row in -- without it, a row shows "accepted" with no way to point at the plan that resulted.
    ("plan_updates", "claim_id", "ALTER TABLE plan_updates ADD COLUMN claim_id TEXT"),
    ("plan_updates", "tension_id", "ALTER TABLE plan_updates ADD COLUMN tension_id TEXT"),
    ("plan_updates", "decided_at", "ALTER TABLE plan_updates ADD COLUMN decided_at REAL"),
    ("plan_updates", "decided_by", "ALTER TABLE plan_updates ADD COLUMN decided_by TEXT"),
    ("plan_updates", "applied_plan_id", "ALTER TABLE plan_updates ADD COLUMN applied_plan_id TEXT"),
    # CR8 product decision (Kyle, 2026-09-16): "primary for this project" is a property of the project<->
    # collection RELATIONSHIP, never the global collection -- the same reservoir can be primary for one
    # project's research question and merely secondary/contextual for another. Lives on project_collections,
    # not `collections`. Conservative defaults on every existing row: source_role='unspecified',
    # monitor_policy='auto' -- see reservoir.effective_monitor_active for the derivation (unspecified+auto is
    # OFF, so no pre-existing attachment silently starts being monitored the moment this migration runs).
    ("project_collections", "source_role", "ALTER TABLE project_collections ADD COLUMN source_role TEXT NOT NULL DEFAULT 'unspecified'"),
    ("project_collections", "monitor_policy", "ALTER TABLE project_collections ADD COLUMN monitor_policy TEXT NOT NULL DEFAULT 'auto'"),
    # SUB4: catalog providers can refresh small, explicitly observed metadata without overwriting user decisions.
    ("candidates", "metadata_json", "ALTER TABLE candidates ADD COLUMN metadata_json TEXT"),
    # P11 EA-1 (§41–§43): disclosure state lives on the ORIGINAL material; everything derived computes its floor from
    # provenance at assembly (access.py). NULL disclosure_class = unclassified = restricted for external disclosure,
    # except where access.EFFECTIVE_CLASS_SQL can prove public acquisition. acquisition_provenance is written by the
    # ingest paths that know it (anonymous | browser_private | user_private | external_processed); NULL on legacy rows.
    ("sources", "disclosure_class", "ALTER TABLE sources ADD COLUMN disclosure_class TEXT"),
    ("sources", "disclosure_origin", "ALTER TABLE sources ADD COLUMN disclosure_origin TEXT"),
    ("sources", "acquisition_provenance", "ALTER TABLE sources ADD COLUMN acquisition_provenance TEXT"),
    ("project_facts", "disclosure_class", "ALTER TABLE project_facts ADD COLUMN disclosure_class TEXT"),
    # P11 EA-2 (§49): durable user state that can evolve — who said it, through which client, how explicitly, whether
    # it is still the current position, what it replaced. Every pre-P11 row stays valid through the defaults:
    # explicit, active, project-scoped, author unknown (rendered "Kyle (local, unattributed)").
    ("project_facts", "actor_id", "ALTER TABLE project_facts ADD COLUMN actor_id TEXT"),
    ("project_facts", "external_client_id", "ALTER TABLE project_facts ADD COLUMN external_client_id TEXT"),
    ("project_facts", "explicitness", "ALTER TABLE project_facts ADD COLUMN explicitness TEXT NOT NULL DEFAULT 'explicit'"),
    ("project_facts", "status", "ALTER TABLE project_facts ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
    ("project_facts", "scope", "ALTER TABLE project_facts ADD COLUMN scope TEXT NOT NULL DEFAULT 'project'"),
    ("project_facts", "rationale", "ALTER TABLE project_facts ADD COLUMN rationale TEXT"),
    ("project_facts", "effective_at", "ALTER TABLE project_facts ADD COLUMN effective_at REAL"),
    ("project_facts", "supersedes_fact_id", "ALTER TABLE project_facts ADD COLUMN supersedes_fact_id INTEGER"),
    ("project_facts", "client_request_id", "ALTER TABLE project_facts ADD COLUMN client_request_id TEXT"),
    ("project_facts", "updated_at", "ALTER TABLE project_facts ADD COLUMN updated_at REAL"),
    # P11 EA-2: the person/request that caused a job, so the job's automatic writes can say so without claiming to
    # BE that person's act. Columns, not payload keys: the payload feeds dedupe keys and content-addressed work units.
    ("jobs", "origin_actor_id", "ALTER TABLE jobs ADD COLUMN origin_actor_id TEXT"),
    ("jobs", "origin_request_id", "ALTER TABLE jobs ADD COLUMN origin_request_id TEXT"),
    # P11 EA-9: the receipt a conversation sync returned, so a retried sync answers with the same receipt.
    ("external_intakes", "receipt", "ALTER TABLE external_intakes ADD COLUMN receipt TEXT"),
    # P11 EA-9 (Kyle's review): the user's own words that support a committed fact — the trace that separates "ChatGPT
    # extracted a decision" from "ChatGPT invented one". A client-labelled 'explicit' with no wording is only proposed.
    ("project_facts", "user_text", "ALTER TABLE project_facts ADD COLUMN user_text TEXT"),
    # P11 EA-9 (Kyle's second review): WHY a late sync went to this project — the selection basis and the user's words.
    ("external_intakes", "project_selection", "ALTER TABLE external_intakes ADD COLUMN project_selection TEXT"),
    # P11 EA-9 (Kyle, 2026-09-22): why a collaborator's commit was held for the OWNER. Internal: never on an external
    # response or on a ledger event a collaborator can read. `explicitness` keeps what the person actually did.
    ("project_facts", "review_reason", "ALTER TABLE project_facts ADD COLUMN review_reason TEXT"),
]


def _rekey_source_analysis(conn: sqlite3.Connection) -> None:
    """0.16.0 keyed project_source_analysis by (project, source) with ONE provenance set for two different AI tasks.
    0.16.1 keys it by (project, source, analysis_kind). Rebuild the table once, splitting old rows into their kinds."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(project_source_analysis)").fetchall()}
    if not cols or "analysis_kind" in cols:
        return
    conn.execute("ALTER TABLE project_source_analysis RENAME TO project_source_analysis_v0")
    conn.executescript(SCHEMA)
    for r in conn.execute("SELECT * FROM project_source_analysis_v0").fetchall():
        d = dict(r)
        status = "legacy_unverified" if d.get("provider") == "migrated" else "current"
        base = (d["project_id"], d["source_id"], d.get("model"), d.get("provider"), d.get("prompt_version"), d.get("schema_version"),
                d.get("source_revision"), d.get("brief_revision"), d.get("facts_revision"), status, d["created_at"], d["updated_at"])
        if d.get("relevance") is not None or d.get("relevance_why"):
            conn.execute("""INSERT OR IGNORE INTO project_source_analysis (project_id, source_id, analysis_kind, relevance, relevance_why, model, provider,
                            prompt_version, schema_version, source_revision, brief_revision, facts_revision, status, created_at, updated_at)
                            VALUES (?,?,'relevance',?,?,?,?,?,?,?,?,?,?,?,?)""", (base[0], base[1], d["relevance"], d.get("relevance_why"), *base[2:]))
        if d.get("summary") is not None or d.get("substance") is not None:
            conn.execute("""INSERT OR IGNORE INTO project_source_analysis (project_id, source_id, analysis_kind, summary, substance, model, provider,
                            prompt_version, schema_version, source_revision, brief_revision, facts_revision, status, created_at, updated_at)
                            VALUES (?,?,'summary',?,?,?,?,?,?,?,?,?,?,?,?)""", (base[0], base[1], d["summary"], d.get("substance"), *base[2:]))
    conn.execute("DROP TABLE project_source_analysis_v0")
    conn.commit()


def init_db() -> None:
    conn = connect()
    _rekey_source_analysis(conn)
    conn.executescript(SCHEMA)
    for table, col, sql in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            conn.execute(sql)
    # indexes on migrated columns (must follow the column adds)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sources_fingerprint ON sources(platform, content_fingerprint)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_sources_canonical ON sources(platform, canonical_url)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_source_captures_client_capture_id "
                 "ON source_captures(client_capture_id) WHERE client_capture_id IS NOT NULL")
    # R8: exact production predicates, measured on a copied verified backup before admission. The broad Findings
    # list still chooses a scan because one project owns 80% of the table; the source-specific path moved from a
    # table scan (7.87 ms median) to an indexed lookup (0.43 ms). The other indexes remove full scans or temp
    # grouping from message history, cost attribution and kind-specific queue operations.
    conn.execute("CREATE INDEX IF NOT EXISTS ix_project_notes_project_status_source ON project_notes(project_id, status, source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_messages_conversation ON messages(conversation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_usage_kind_source ON usage(kind, source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_kind_status ON jobs(kind, status)")
    # P11 EA-1: the two actors every chronology needs from the first write (docs/P11-EXECUTION-PLAN-2026-09-22.md §12)
    conn.execute("INSERT OR IGNORE INTO external_actors (id, name, kind, created_at) VALUES ('kyle', 'Kyle', 'person', ?)", (now(),))
    conn.execute("INSERT OR IGNORE INTO external_actors (id, name, kind, created_at) VALUES ('system', 'Neuro (automatic)', 'system', ?)", (now(),))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_facts_request ON project_facts(external_client_id, client_request_id) "
                 "WHERE client_request_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_facts_project_status ON project_facts(project_id, status)")
    # P11 EA-2: a source turning ready is ledgered for every project holding it; that lookup is by source_id, which
    # the (project_id, source_id) primary keys cannot serve. Additive, read inside the write that flips the status.
    conn.execute("CREATE INDEX IF NOT EXISTS ix_project_sources_source ON project_sources(source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_project_collections_collection ON project_collections(collection_id)")
    conn.commit()
    _add_job_payload_columns(conn)
    _migrate_source_analysis(conn)
    _backfill_spoken_chars(conn)
    _reclassify_members_only(conn)
    _backfill_job_lanes(conn)
    _dedupe_claim_evidence(conn)
    _resolve_orphan_invocations(conn)
    try:
        backfill_failure_classes()           # 0.61.0: the failures already on the books become distinguishable too
    except Exception as e:  # noqa: BLE001 — never let a cosmetic backfill stop the app from starting
        logging.getLogger(__name__).warning("failure-class backfill skipped: %s", e)
    try:
        sweep_orphaned_pending()             # 0.63.11: a source nothing is running says so instead of waiting
        snapshot_pre_fix_mismatches()        # 0.63.29: separate the mis-read substitutions from any real ones
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("orphan sweep skipped: %s", e)


def _add_job_payload_columns(conn: sqlite3.Connection) -> None:
    """R8 (narrow, 2026-09-17): `jobs.project_id` / `jobs.source_id` as VIRTUAL generated columns over the payload
    JSON, plus the indexes `api_project_jobs` needs. Generated (not copied), so they can never drift from the payload
    — every existing `UPDATE jobs SET payload=?` keeps them right for free — and VIRTUAL, so `ALTER TABLE ADD COLUMN`
    is legal on an existing database (SQLite allows adding VIRTUAL, never STORED, generated columns). Additive: no
    rewrite, no backfill, ~2 MB of index on the 79k-row live table. `PRAGMA table_info` hides generated columns, so
    the presence check uses `table_xinfo`, and MIGRATIONS' plain loop is not used for these."""
    have = {r[1] for r in conn.execute("PRAGMA table_xinfo(jobs)").fetchall()}
    if "project_id" not in have:
        conn.execute("ALTER TABLE jobs ADD COLUMN project_id TEXT GENERATED ALWAYS AS (json_extract(payload, '$.project_id')) VIRTUAL")
    if "source_id" not in have:
        conn.execute("ALTER TABLE jobs ADD COLUMN source_id TEXT GENERATED ALWAYS AS (json_extract(payload, '$.source_id')) VIRTUAL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_project_created ON jobs(project_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_kind_source_created ON jobs(kind, source_id, created_at)")
    conn.commit()


def _reclassify_members_only(conn: sqlite3.Connection) -> None:
    """2026-09-18: 22 failed sources on Kyle's library said 'available to this channel's members on level …' — a
    members-only wording the classifier did not know, filed as retryable `login_wall`. Same rule as `set_source_status`,
    applied once to rows already on the books: permanent class + the access gate."""
    try:
        n = conn.execute("UPDATE sources SET error_class='members_only', access_gate=COALESCE(access_gate, 'members_only') "
                         "WHERE status='failed' AND (error_class IS NULL OR error_class='login_wall' OR error_class='other') "
                         "AND (lower(error) LIKE '%members-only%' OR lower(error) LIKE '%members only%' OR lower(error) LIKE '%join this channel%' "
                         "OR lower(error) LIKE \"%available to this channel's members%\")").rowcount
        conn.commit()
        if n:
            logging.getLogger(__name__).info("reclassified %d failed source(s) as members_only", n)
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logging.getLogger(__name__).warning("members_only reclassification skipped: %s", e)


def _backfill_spoken_chars(conn: sqlite3.Connection) -> None:
    """P0.3: one SQL statement, once, for every source written before `sources.spoken_chars` existed. Exact
    same arithmetic as the old per-request walk (`sum(len(seg.text))`): SQLite's length() counts characters."""
    try:
        n = conn.execute(
            "UPDATE sources SET spoken_chars=(SELECT COALESCE(SUM(length(text)), 0) FROM segments WHERE segments.source_id=sources.id) "
            "WHERE spoken_chars IS NULL AND status='ready'").rowcount
        conn.commit()
        if n:
            logging.getLogger(__name__).info("backfilled spoken_chars for %d ready source(s)", n)
    except Exception as e:  # noqa: BLE001 — a derived number must never stop the app from starting
        conn.rollback()
        logging.getLogger(__name__).warning("spoken_chars backfill skipped: %s", e)


def _backfill_job_lanes(conn: sqlite3.Connection) -> None:
    """0.45.11: Kyle, live — "the active queue needs to be re-prioritized." The 0.45.9/0.45.10 lane tagging only
    applies to jobs CREATED from then on; anything already sitting in the queue (e.g. rank_proposed or
    refresh_skipped_metadata jobs queued before the update landed) kept the old 'normal' lane and wouldn't jump
    ahead or get deprioritized until it was re-queued for some other reason. Runs once per app start, touches only
    currently-queued jobs (never running/done/failed/cancelled ones), and is a no-op once everything already
    matches — safe to run on every startup."""
    conn.execute("UPDATE jobs SET lane='priority', updated_at=? WHERE status='queued' AND kind='rank_proposed' AND lane!='priority'", (now(),))
    conn.execute("UPDATE jobs SET lane='low', updated_at=? WHERE status='queued' AND kind='refresh_skipped_metadata' AND lane!='low'", (now(),))
    conn.commit()


def _dedupe_claim_evidence(conn: sqlite3.Connection) -> None:
    """Cleanup for the duplicate-citation guard gap fixed in claims.add_evidence on 2026-09-14 (see
    integrity_check's docstring): the guard now stops any NEW duplicate (claim_id, source_id, source_revision,
    locator, relation) row from being created, but whatever duplicate rows existed before that fix landed were
    never actually removed -- integrity_check has been reporting duplicate_claim_evidence > 0 ever since, with
    nothing in the codebase actually clearing it. Runs once per app start, keeps the OLDEST row (lowest id) in
    each duplicate group -- preserving whichever evidence was cited/used first -- and deletes the rest. Nothing
    else references claim_evidence.id as a foreign key, so this is safe: no orphaned rows anywhere else. A no-op
    once the table is clean, safe to run on every startup, same pattern as _backfill_job_lanes/_backfill_spoken_chars."""
    try:
        cur = conn.execute("""
            DELETE FROM claim_evidence WHERE id IN (
              SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                  PARTITION BY claim_id, source_id, source_revision, locator, relation
                  ORDER BY id ASC
                ) AS rn
                FROM claim_evidence
              ) WHERE rn > 1
            )""")
        conn.commit()
        if cur.rowcount:
            logging.getLogger(__name__).info("removed %d duplicate claim_evidence row(s) (pre-2026-09-14 guard gap)", cur.rowcount)
    except Exception as e:  # noqa: BLE001 — a cleanup pass must never stop the app from starting
        conn.rollback()
        logging.getLogger(__name__).warning("claim_evidence dedupe skipped: %s", e)


def _migrate_source_analysis(conn: sqlite3.Connection) -> None:
    """0.16: summary/substance/relevance used to live on the global source row although they were generated against
    one project's brief. Copy what is there into project_source_analysis for every project the source belongs to
    (marked provider='migrated' so nothing pretends to know which model wrote it), once."""
    if kv_get("migrated:project_source_analysis") == "1":
        return
    t = now()
    rows = conn.execute("SELECT id, summary, substance, relevance, relevance_why FROM sources WHERE summary IS NOT NULL OR substance IS NOT NULL OR relevance IS NOT NULL").fetchall()
    n = 0
    for s in rows:
        pids = {r["project_id"] for r in conn.execute("SELECT project_id FROM project_sources WHERE source_id=? AND excluded=0", (s["id"],)).fetchall()}
        pids |= {r["project_id"] for r in conn.execute(
            "SELECT pc.project_id FROM project_collections pc JOIN source_collections sc ON sc.collection_id=pc.collection_id WHERE sc.source_id=?", (s["id"],)).fetchall()}
        for pid in pids:
            # preserved, but NOT current: the old global value may have been written against another project's brief
            if s["summary"] is not None or s["substance"] is not None:
                conn.execute("""INSERT OR IGNORE INTO project_source_analysis (project_id, source_id, analysis_kind, summary, substance, provider, status, created_at, updated_at)
                                VALUES (?,?,'summary',?,?,'migrated','legacy_unverified',?,?)""", (pid, s["id"], s["summary"], s["substance"], t, t))
            if s["relevance"] is not None:
                conn.execute("""INSERT OR IGNORE INTO project_source_analysis (project_id, source_id, analysis_kind, relevance, relevance_why, provider, status, created_at, updated_at)
                                VALUES (?,?,'relevance',?,?,'migrated','legacy_unverified',?,?)""", (pid, s["id"], s["relevance"], s["relevance_why"], t, t))
            n += 1
    conn.execute("INSERT INTO kv (key, value) VALUES ('migrated:project_source_analysis','1') ON CONFLICT(key) DO UPDATE SET value='1'")
    conn.commit()
    if n:
        import logging
        logging.getLogger(__name__).info("migrated %d source analyses into project_source_analysis", n)


# P0 instrumentation (docs/SPEED-AUDIT-2026-09-17.md): how long each write transaction held SQLite's single writer.
# The audit could see the CONSEQUENCES of long holds (`database is locked`, heartbeats failing, "New chat" hanging)
# but had no number for the hold itself; every rung that claims to shorten it needs one. Recorded on the R0 ledger
# as `db:write_hold` (seconds) and logged, with the caller, when a hold exceeds WRITE_HOLD_WARN_S.
WRITE_HOLD_WARN_S = 2.0


def _note_write_hold(conn: sqlite3.Connection, t0: float, what: str) -> None:
    if not conn.in_transaction:          # a read-only tx()/batch() never took the writer
        return
    dt = time.perf_counter() - t0
    try:
        from . import perf
        perf.record("db:write_hold", dt)
    except Exception:  # noqa: BLE001
        pass
    if dt >= WRITE_HOLD_WARN_S:
        import traceback
        frames = [f for f in traceback.extract_stack(limit=12) if not f.filename.endswith("db.py") and "contextlib" not in f.filename]
        where = f"{Path(frames[-1].filename).name}:{frames[-1].lineno} {frames[-1].name}" if frames else "?"
        logging.getLogger(__name__).warning("write lock held %.1fs by %s (%s)", dt, where, what)


def after_commit(fn: Any) -> None:
    """P11 EA-2 (§45): run `fn` once the OUTERMOST tx()/batch() on this thread has committed — for derived work
    (ledger materiality) that must never run under the writer's lock. Deduplicated per commit; dropped on rollback."""
    pending = getattr(_local, "after_commit", None)
    if pending is None:
        pending = _local.after_commit = []
    if fn not in pending:
        pending.append(fn)


def _run_after_commit() -> None:
    pending = getattr(_local, "after_commit", None)
    if not pending:
        return
    _local.after_commit = []
    for fn in pending:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a derived follow-up never fails the write it follows
            logging.getLogger(__name__).warning("after-commit hook %s failed: %s", getattr(fn, "__name__", fn), e)


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    if getattr(_local, "batch", 0):      # inside batch(): the batch commits, not each tx
        yield conn
        return
    depth = getattr(_local, "tx_depth", 0)
    _local.tx_depth = depth + 1
    t0 = time.perf_counter()
    try:
        yield conn
        _note_write_hold(conn, t0, "tx")
        conn.commit()
    except Exception:
        conn.rollback()
        if depth == 0:
            _local.after_commit = []
        raise
    finally:
        _local.tx_depth = depth
    if depth == 0:
        _run_after_commit()


@contextmanager
def batch() -> Iterator[None]:
    """Group many small writes into one transaction (bulk listings). Keeps the write lock briefly held
    once instead of hundreds of times, so API requests and other workers aren't starved."""
    _local.batch = getattr(_local, "batch", 0) + 1
    t0 = time.perf_counter()
    outermost = False
    try:
        yield
        if _local.batch == 1:
            conn = connect()
            _note_write_hold(conn, t0, "batch")
            conn.commit()
            outermost = True
    except Exception:
        if _local.batch == 1:
            connect().rollback()
            _local.after_commit = []
        raise
    finally:
        _local.batch -= 1
    if outermost and not getattr(_local, "tx_depth", 0):
        _run_after_commit()


def now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("tags", "payload", "result", "citations", "questions", "meta", "blocked_by"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    d.pop("embedding", None)
    return d


# ---------------------------------------------------------------- sources

def _record_source_ready(conn: sqlite3.Connection, source_id: str) -> None:
    """P11 EA-2: new evidence became available in every project that holds this source (direct or via collection)."""
    pids = {r[0] for r in conn.execute(
        "SELECT project_id FROM project_sources WHERE source_id=? AND excluded=0 UNION "
        "SELECT pc.project_id FROM project_collections pc JOIN source_collections sc ON sc.collection_id=pc.collection_id "
        "WHERE sc.source_id=? AND NOT EXISTS (SELECT 1 FROM project_sources ps WHERE ps.project_id=pc.project_id "
        "AND ps.source_id=sc.source_id AND ps.excluded=1)", (source_id, source_id)).fetchall()}
    if not pids:
        return
    from . import access, ledger
    floor = {access.source_classes([source_id])[source_id]}
    for pid in sorted(pids):
        ledger.record(conn, pid, event_type="source_ready", object_type="source", object_id=source_id,
                      before={"ready": False}, after={"ready": True}, floor=floor)


def set_acquisition_provenance(source_id: str, provenance: str) -> None:
    """P11 EA-1 (§43): how a source's content was obtained, the fact the disclosure rule is built on. More private
    always wins: a page first fetched anonymously and later SENT from the user's browser becomes browser_private,
    never the reverse. `anonymous` is only ever written onto a row that has no provenance yet."""
    assert provenance in ("anonymous", "browser_private", "user_private", "external_processed")
    with tx() as conn:
        if provenance == "anonymous":
            conn.execute("UPDATE sources SET acquisition_provenance='anonymous' WHERE id=? AND acquisition_provenance IS NULL", (source_id,))
        else:
            conn.execute("UPDATE sources SET acquisition_provenance=? WHERE id=? AND (acquisition_provenance IS NULL OR acquisition_provenance='anonymous')",
                         (provenance, source_id))


def upsert_source(**fields: Any) -> dict[str, Any]:
    """Insert or update a source keyed on (platform, external_id). Returns the row."""
    platform, external_id = fields["platform"], fields.get("external_id")
    if not external_id and not fields.get("id"):
        # G1: a source without identity would be a new row on every add — identity.resolve_or_create_source derives one first
        raise ValueError(f"upsert_source needs an external_id (platform {platform!r}, url {fields.get('url')!r})")
    if "tags" in fields and not isinstance(fields["tags"], str):
        fields["tags"] = json.dumps(fields["tags"] or [])
    with tx() as conn:
        existing = None
        if external_id:
            existing = conn.execute(
                "SELECT * FROM sources WHERE platform=? AND external_id=?", (platform, external_id)
            ).fetchone()
        t = now()
        if existing:
            fields = {k: v for k, v in fields.items() if v is not None or k in ("error", "error_class")}   # an explicit error=None CLEARS it (B1: a placeholder's browser-needed state ends on success)
            fields["updated_at"] = t
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE sources SET {sets} WHERE id=?", (*fields.values(), existing["id"]))
            sid = existing["id"]
            if fields.get("status") == "ready" and existing["status"] != "ready":
                _record_source_ready(conn, sid)
        else:
            sid = fields.get("id") or new_id()
            fields.update(id=sid, created_at=t, updated_at=t)
            cols = ", ".join(fields)
            qs = ", ".join("?" for _ in fields)
            conn.execute(f"INSERT INTO sources ({cols}) VALUES ({qs})", tuple(fields.values()))
        return row_to_dict(conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())  # type: ignore[return-value]


def sources_for_urls(urls: list[str]) -> dict[str, str]:
    """Which of these addresses the library already holds, as {url: source_id}.

    Derived, never a flag. 0.63.17: the page that offered its Loom video went on saying "not added yet" after Kyle
    added it, because a stored "added" marker is a second copy of a truth the `sources` table already holds. The
    library is asked instead, so the answer cannot drift — and it is right even when the video arrived by another
    route entirely."""
    out: dict[str, str] = {}
    want = [u for u in dict.fromkeys(urls) if u]
    if not want:
        return out
    conn = connect()
    for u in want:
        r = conn.execute("SELECT id FROM sources WHERE url=? OR canonical_url=? LIMIT 1", (u, u)).fetchone()
        if r:
            out[u] = r["id"]
    return out


def set_video_embeds(source_id: str, urls: list[str]) -> None:
    """The players found in a captured page. Additive and idempotent; an empty list clears the column."""
    with tx() as conn:
        conn.execute("UPDATE sources SET video_embeds=?, updated_at=? WHERE id=?",
                     (json.dumps(list(urls)) if urls else None, now(), source_id))


def video_embeds_of(source_id: str) -> list[str]:
    r = connect().execute("SELECT video_embeds FROM sources WHERE id=?", (source_id,)).fetchone()
    if not r or not r["video_embeds"]:
        return []
    try:
        v = json.loads(r["video_embeds"])
    except ValueError:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def get_source(source_id: str) -> dict[str, Any] | None:
    return row_to_dict(connect().execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


def create_pending_capture_event(*, capture_url: str, capture_mode: str, project_id: str | None = None,
                                 capture_page_title: str | None = None, captured_at: float | None = None,
                                 capture_partial_reason: str | None = None,
                                 capture_page_width: int | None = None, capture_page_height: int | None = None,
                                 capture_viewport_width: int | None = None, capture_viewport_height: int | None = None,
                                 capture_dpr: float | None = None, capture_note: str | None = None) -> str:
    """Send-screenshot: written by the API BEFORE the ingest job is enqueued, source_id NULL. Returns the new
    capture_event id, which travels in the job payload instead of the raw provenance fields (see source_captures'
    own comment in SCHEMA for why)."""
    cid = new_id()
    ts = now()
    with tx() as conn:
        conn.execute(
            """INSERT INTO source_captures (id, source_id, project_id, capture_url, capture_page_title, captured_at,
               capture_mode, capture_partial_reason, capture_page_width, capture_page_height, capture_viewport_width,
               capture_viewport_height, capture_dpr, capture_note, created_at, updated_at)
               VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, project_id, capture_url, capture_page_title, captured_at if captured_at is not None else ts,
             capture_mode, capture_partial_reason, capture_page_width, capture_page_height, capture_viewport_width,
             capture_viewport_height, capture_dpr, capture_note, ts, ts),
        )
    return cid


def materialize_capture_event(capture_event_id: str, source_id: str) -> None:
    """Fills in the source_id once ingestion resolves one, closing the gap across the job-queue boundary. A no-op
    (not an error) if the capture_event_id is unknown or already materialized to a DIFFERENT source, so a retried
    or duplicate-triggered ingest job can never clobber a capture event's real link — first write wins."""
    with tx() as conn:
        row = conn.execute("SELECT source_id FROM source_captures WHERE id=?", (capture_event_id,)).fetchone()
        if row is None or row["source_id"] is not None:
            return
        conn.execute("UPDATE source_captures SET source_id=?, updated_at=? WHERE id=?", (source_id, now(), capture_event_id))


def get_capture_events_for_source(source_id: str, *, project_id: str | None = None) -> list[dict[str, Any]]:
    """project_id: scope to captures made while working in that project (sources_value.digest() needs the
    project-relative view -- a capture taken from Project A must never surface as evidence on Project B's copy
    of the same source, so this is a strict filter, never a fallback to the global most-recent capture)."""
    if project_id is not None:
        return [row_to_dict(r) for r in connect().execute(
            "SELECT * FROM source_captures WHERE source_id=? AND project_id=? ORDER BY captured_at DESC",
            (source_id, project_id)).fetchall()]
    return [row_to_dict(r) for r in connect().execute(
        "SELECT * FROM source_captures WHERE source_id=? ORDER BY captured_at DESC", (source_id,)).fetchall()]


def get_capture_event_by_client_id(client_capture_id: str) -> dict[str, Any] | None:
    """Look up a capture event by the extension's own stable capture_id (idempotency key)."""
    return row_to_dict(connect().execute(
        "SELECT * FROM source_captures WHERE client_capture_id=?", (client_capture_id,)).fetchone())


def create_or_get_capture_ingest_request(*, client_capture_id: str, capture_url: str, capture_mode: str,
                                          job_kind: str, job_payload: dict,
                                          project_id: str | None = None, capture_page_title: str | None = None,
                                          captured_at: float | None = None, capture_partial_reason: str | None = None,
                                          capture_page_width: int | None = None, capture_page_height: int | None = None,
                                          capture_viewport_width: int | None = None, capture_viewport_height: int | None = None,
                                          capture_dpr: float | None = None, capture_note: str | None = None,
                                          job_dependency_policy: str = "ALL_SUCCESS",
                                          job_execution_policy: str = "local_preferred",
                                          job_lane: str = "normal") -> dict[str, Any]:
    """Atomically create-or-fetch the (capture_event, ingest job) pair for one extension `client_capture_id`.

    Send-screenshot's end-to-end idempotency key. The extension generates client_capture_id once per "Send
    screenshot" press (crypto.randomUUID()) and resends the SAME id on every retry of that same press -- so two
    concurrent or retried requests for one press must converge on exactly one capture_events row and exactly one
    ingest job, never two, and a row must never end up committed without its job (or vice versa).

    Both ids are pre-generated before either write so there is no ordering dependency between them. The
    source_captures INSERT sets client_capture_id AND ingest_job_id in that SAME statement -- never a later
    UPDATE -- so a row that lands can never be missing its job link. The insert is attempted directly (no
    SELECT-then-INSERT: that has a TOCTOU race); on the partial-unique-index violation (see SCHEMA), this request
    is the "loser" and re-reads the winner's already-committed row instead.

    Whole thing runs inside one db.batch(): create_job()'s own internal tx() becomes a no-op-commit nested inside
    it (see batch()'s docstring), so the capture row and its job commit together in one transaction on the winner
    path, or nothing commits at all on the loser path -- SQLite's single-writer serialization means that by the
    time a loser's INSERT can even be attempted, any winner's whole batch (row + job) is already fully committed,
    so re-selecting after losing is guaranteed to find a complete row, every time.

    Returns {"capture_event": {...}, "job": {...} | None, "created": bool}. `created` tells the caller (api.py)
    whether IT is the one that just made the row -- needed so a losing request can delete its own just-written
    temp upload file rather than leaving an orphan."""
    capture_event_id = new_id()
    job_id = new_id()
    ts = now()
    created = False
    with batch():
        try:
            with tx() as conn:
                conn.execute(
                    """INSERT INTO source_captures (id, source_id, project_id, capture_url, capture_page_title,
                       captured_at, capture_mode, capture_partial_reason, capture_page_width, capture_page_height,
                       capture_viewport_width, capture_viewport_height, capture_dpr, capture_note,
                       client_capture_id, ingest_job_id, created_at, updated_at)
                       VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (capture_event_id, project_id, capture_url, capture_page_title,
                     captured_at if captured_at is not None else ts, capture_mode, capture_partial_reason,
                     capture_page_width, capture_page_height, capture_viewport_width, capture_viewport_height,
                     capture_dpr, capture_note, client_capture_id, job_id, ts, ts),
                )
            created = True
        except sqlite3.IntegrityError:
            pass                                    # lost the race: another request with this client_capture_id already landed

        if created:
            job = create_job(job_kind, {**job_payload, "capture_event_id": capture_event_id}, job_id=job_id,
                              dedupe_key=f"capture:{client_capture_id}", dependency_policy=job_dependency_policy,
                              execution_policy=job_execution_policy, lane=job_lane)
            capture_event = get_capture_event_by_client_id(client_capture_id)
            return {"capture_event": capture_event, "job": job, "created": True}

    capture_event = get_capture_event_by_client_id(client_capture_id)
    if capture_event is None:                        # cannot happen unless the unique key differs from ours
        raise RuntimeError(f"capture identity conflict for client_capture_id={client_capture_id}")
    job = get_job(capture_event["ingest_job_id"]) if capture_event.get("ingest_job_id") else None
    return {"capture_event": capture_event, "job": job, "created": False}


def find_source(platform: str, external_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        connect().execute("SELECT * FROM sources WHERE platform=? AND external_id=?", (platform, external_id)).fetchone()
    )


def list_sources(
    *, status: str | None = None, collection_id: str | None = None, query: str | None = None,
    limit: int = 500, offset: int = 0, ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """`ids` (P0.4, docs/SPEED-AUDIT-2026-09-17.md): restrict to these source ids IN THE QUERY. `/api/sources` used to
    list the whole global library (`limit=10000`) and keep the project's rows in Python; the project-scoped set is
    now the query's own predicate. An empty `ids` returns nothing, as the Python filter did."""
    sql = "SELECT s.* FROM sources s"
    where, args = [], []
    if ids is not None:
        idl = list(dict.fromkeys(ids))
        if not idl:
            return []
        sql += " JOIN (SELECT value AS id FROM json_each(?)) want ON want.id = s.id"
        args.append(json.dumps(idl))
    if collection_id:
        sql += " JOIN source_collections sc ON sc.source_id = s.id"
        where.append("sc.collection_id=?"); args.append(collection_id)
    if status:
        where.append("s.status=?"); args.append(status)
    if query:
        where.append("(s.title LIKE ? OR s.channel LIKE ?)"); args += [f"%{query}%", f"%{query}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Most recently ADDED first (0.63.93). This listing is capped (2,000 for a project's page, 500 for the library
    # picker, 20 for the CLI's failed list), and the cap used to fall on publish-date order: a course lesson or a
    # document carries no publish date, so the rows Kyle had just added were the first ones a full project would
    # have cut. What entered the library last is what a capped list must never drop; the page re-sorts client-side.
    sql += " ORDER BY s.created_at DESC, COALESCE(s.published_at, '') DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    return [row_to_dict(r) for r in connect().execute(sql, args).fetchall()]  # type: ignore[misc]


STAGES = ("listed", "metadata", "transcript", "chunks", "embeddings", "ready")


def set_stage(source_id: str, stage: str, conn: sqlite3.Connection | None = None) -> None:
    """A stage is set only AFTER all of its durable data is committed (callers do the writes and this call inside
    one batch()/tx so the two are atomic)."""
    assert stage in STAGES, stage
    if conn is not None:
        conn.execute("UPDATE sources SET stage=?, updated_at=? WHERE id=?", (stage, now(), source_id))
        return
    with tx() as c:
        c.execute("UPDATE sources SET stage=?, updated_at=? WHERE id=?", (stage, now(), source_id))


def stage_index(stage: str | None) -> int:
    return STAGES.index(stage) if stage in STAGES else 0


def set_audio_path(source_id: str, path: str | None) -> None:
    with tx() as conn:
        conn.execute("UPDATE sources SET audio_path=?, updated_at=? WHERE id=?", (path, now(), source_id))


def replace_chunks(source_id: str, chunks: list[dict]) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        conn.executemany(
            "INSERT INTO chunks (source_id, idx, start, end, text, embedding) VALUES (?,?,?,?,?,?)",
            [(source_id, i, c["start"], c["end"], c["text"], _pack(c.get("embedding"))) for i, c in enumerate(chunks)])


def set_source_status(source_id: str, status: str, error: str | None = None) -> None:
    """0.61.0: a failure is CLASSIFIED as it is recorded.

    Kyle's project holds 14 failed sources and every one of them had `error_class` NULL, so a deleted video, an
    Instagram carousel with no video track, a Reddit 403 and a network timeout were all indistinguishable — which
    means the ones that will never work could not be told apart from the ones worth retrying, and none of them
    could be filtered or retired. The classification is derived from the error text (deterministic, no model), and
    `browser_solvable:*` — set deliberately by `acquire` — is never overwritten."""
    cls = failure_class(error) if status == "failed" else None
    with tx() as conn:
        # a listing that did not carry `availability` learns the gate from the download's own refusal
        if status == "failed" and error and re.search(r"members[- ]only|join this channel|available to this channel's members", str(error), re.I):
            conn.execute("UPDATE sources SET access_gate=COALESCE(access_gate, 'members_only') WHERE id=?", (source_id,))
        if cls:
            conn.execute("UPDATE sources SET status=?, error=?, error_class=CASE WHEN error_class LIKE 'browser_solvable:%' "
                         "THEN error_class ELSE ? END, updated_at=? WHERE id=?", (status, error, cls, now(), source_id))
        else:
            conn.execute("UPDATE sources SET status=?, error=?, updated_at=? WHERE id=?", (status, error, now(), source_id))


# Deterministic, ordered most-specific first. `permanent` says a retry cannot help — that is the distinction the
# Sources view needs in order to offer "retire these" rather than "retry all".
FAILURE_CLASSES: tuple[tuple[str, str, bool], ...] = (
    ("no_media", r"has no video|images/carousel|nothing to transcribe|no audio", True),
    ("unavailable", r"not available|video unavailable|has been removed|private video|deleted", True),
    # 404 before 403/401: "HTTP 404 — nothing at that address" is gone for good, where a 403 may not be.
    ("not_found", r"http (error )?404|404: not found|no longer exists|nothing at that address", True),
    # 2026-09-18: a members-only refusal is permanent for this app — it never holds the person's membership cookie
    # for bulk YouTube downloads (CLAUDE.md), so a retry cannot succeed. Ordered before the retryable sign-in walls.
    ("members_only", r"members[- ]only|join this channel|available to this channel's members", True),
    ("login_wall", r"sign in to confirm|login required|requires authentication", False),
    ("blocked", r"http (error )?40[13]|refused the listing|forbidden|blocked", False),
    ("empty_transcript", r"transcript came back empty|no transcript|captions? (are )?disabled", False),
    ("timed_out", r"timed out|timeout|connection stalled", False),
    ("extractor", r"Unable to extract|Unable to download webpage|unsupported url", False),
    ("cancelled", r"^cancelled", False),
    ("uploaded_file", r"uploaded file, not a link", True),
    # 0.63.11 — a source left `pending` with nothing running it. Retryable by construction: the URL is still
    # there, so a retry re-enters the ordinary path, which is why this is not a permanent class.
    ("orphaned", r"queued by an earlier version|no job is running it", False),
)


ORPHAN_PENDING_AFTER_S = 6 * 3600     # a real ingest never takes six hours; anything still pending has no runner


def sweep_orphaned_pending(older_than_s: float = ORPHAN_PENDING_AFTER_S) -> list[str]:
    """A source stuck `pending` with no job to run it is told so, instead of waiting for ever.

    Found on Kyle's database (0.63.11): two YouTube **search** URLs — `youtube.com/results?search_query=mark+kohler…`
    — sitting `pending` since 2026-09-04 with no title, no `external_id`, no error and **no job anywhere referencing
    them**. Every current path handles a search link correctly (`media.classify_url` → `youtube_search` →
    `enumerate_search` → a review list), so these are orphans of an older version; the app's own UI offered
    "pending (no job — use Retry)", and a retry had nothing to retry.

    Marked `failed` with the retryable class `orphaned`, which is what the Sources view already knows how to offer
    a retry for — and a retry now goes down the correct path. Nothing is deleted and no URL is re-fetched here."""
    cutoff = now() - max(60.0, float(older_than_s))
    rows = connect().execute("SELECT id FROM sources WHERE status='pending' AND updated_at < ?", (cutoff,)).fetchall()
    if not rows:
        return []
    stuck: list[str] = []
    for r in rows:
        live = connect().execute(
            "SELECT 1 FROM jobs WHERE status IN ('queued','running','external_pending','blocked') AND payload LIKE ? LIMIT 1",
            (f'%{r["id"]}%',)).fetchone()
        if not live:
            stuck.append(r["id"])
    for sid in stuck:
        set_source_status(sid, "failed",
                          "this was queued by an earlier version and no job is running it — Retry to add it again")
    if stuck:
        logging.getLogger(__name__).info("swept %d orphaned pending source(s)", len(stuck))
    return stuck


def failure_class(error: str | None) -> str | None:
    if not error:
        return None
    low = str(error).lower()
    for name, pattern, _permanent in FAILURE_CLASSES:
        if re.search(pattern.lower(), low):
            return name
    return "other"


def failure_is_permanent(cls: str | None) -> bool:
    return any(name == cls and permanent for name, _p, permanent in FAILURE_CLASSES)


def failure_summary() -> dict[str, Any]:
    """What failed and whether a retry could ever help — for the Sources view and Health."""
    rows = connect().execute("SELECT COALESCE(error_class,'(unclassified)') c, COUNT(*) n, "
                             "MAX(substr(COALESCE(error,''),1,120)) example FROM sources WHERE status='failed' "
                             "GROUP BY c ORDER BY n DESC").fetchall()
    out = [{"class": r["c"], "count": int(r["n"]), "example": r["example"],
            "permanent": failure_is_permanent(r["c"])} for r in rows]
    return {"classes": out, "failed": sum(r["count"] for r in out),
            "permanent": sum(r["count"] for r in out if r["permanent"]),
            "note": ("`permanent` means a retry cannot help — a deleted video, a carousel with no video track, an "
                     "address that no longer exists. Those are worth retiring; the rest are worth retrying.")}


def delete_source(source_id: str) -> dict[str, int]:
    """Delete a source and make everything that cited it say so. Findings, plan evidence and chat citations that
    pointed at it are marked removed (title kept, link dropped) — visible, never dangling. Segments, chunks,
    project analyses and collection links cascade."""
    touched = {"notes": 0, "plans": 0, "messages": 0}
    t = now()
    with tx() as conn:
        for r in conn.execute("SELECT id, citations FROM project_notes WHERE citations LIKE ?", (f'%{source_id}%',)).fetchall():
            cites = json.loads(r["citations"] or "[]")
            hit = False
            for c in cites:
                if c.get("source_id") == source_id and not c.get("removed"):
                    c.update({"removed": True, "removed_at": t, "link": None})
                    hit = True
            if hit:
                conn.execute("UPDATE project_notes SET citations=? WHERE id=?", (json.dumps(cites), r["id"]))
                touched["notes"] += 1
        for r in conn.execute("SELECT id, plan FROM plans WHERE plan LIKE ?", (f'%{source_id}%',)).fetchall():
            plan = json.loads(r["plan"] or "{}")
            emap = plan.get("_evidence") or {}
            hit = False
            for eid, e in emap.items():
                if e.get("source_id") == source_id and not e.get("removed"):
                    e.update({"removed": True, "removed_at": t, "link": None})
                    hit = True
            if hit:
                conn.execute("UPDATE plans SET plan=? WHERE id=?", (json.dumps(plan), r["id"]))
                touched["plans"] += 1
        for r in conn.execute("SELECT id, citations FROM messages WHERE citations LIKE ?", (f'%{source_id}%',)).fetchall():
            cites = json.loads(r["citations"] or "[]")
            hit = False
            for c in cites:
                if c.get("source_id") == source_id and not c.get("removed"):
                    c.update({"removed": True, "removed_at": t, "link": None})
                    hit = True
            if hit:
                conn.execute("UPDATE messages SET citations=? WHERE id=?", (json.dumps(cites), r["id"]))
                touched["messages"] += 1
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    return touched


def fun_stats(project_id: str | None = None) -> dict[str, Any]:
    """Numbers for the 'your research in numbers' card: hours of media, words, spend, comparisons."""
    conn = connect()
    if project_id:
        ids = set(project_source_ids(project_id))
        rows = [r for r in conn.execute("SELECT id, platform, duration, title FROM sources WHERE status='ready'").fetchall() if r["id"] in ids]
    else:
        rows = conn.execute("SELECT id, platform, duration, title FROM sources WHERE status='ready'").fetchall()
    ids_sql = ",".join("?" for _ in rows) or "''"
    chars = conn.execute(f"SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id IN ({ids_sql})", tuple(r["id"] for r in rows)).fetchone()[0] if rows else 0
    secs = sum(r["duration"] or 0 for r in rows)
    media = [r for r in rows if r["duration"]]
    longest = max(media, key=lambda r: r["duration"], default=None)
    by_platform: dict[str, int] = {}
    for r in rows:
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
    try:
        q = "SELECT COALESCE(SUM(cost),0) FROM usage" + (" WHERE project_id=?" if project_id else "")
        spend = float(conn.execute(q, (project_id,) if project_id else ()).fetchone()[0])
        q = "SELECT COALESCE(SUM(saved),0) FROM usage" + (" WHERE project_id=?" if project_id else "")
        saved = float(conn.execute(q, (project_id,) if project_id else ()).fetchone()[0])
    except sqlite3.OperationalError:
        spend, saved = 0.0, 0.0
    findings = conn.execute("SELECT COUNT(*) FROM project_notes WHERE status='approved'" + (" AND project_id=?" if project_id else ""),
                            (project_id,) if project_id else ()).fetchone()[0]
    return {"sources": len(rows), "with_duration": len(media), "seconds": int(secs), "hours": round(secs / 3600, 1),
            "words": int(chars / 5.2), "by_platform": by_platform, "spend": round(spend, 2), "saved": round(saved, 2), "findings": findings,
            "longest": {"title": longest["title"], "hours": round(longest["duration"] / 3600, 1)} if longest else None}


def source_stats() -> dict[str, Any]:
    conn = connect()
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(duration),0) dur, SUM(status='ready') ready, SUM(status='failed') failed, "
        "SUM(status='pending') pending FROM sources"
    ).fetchone()
    c = conn.execute("SELECT COUNT(*) n, SUM(embedding IS NOT NULL) emb FROM chunks").fetchone()
    return {
        "sources": r["n"], "ready": r["ready"] or 0, "failed": r["failed"] or 0, "pending": r["pending"] or 0,
        "total_hours": round((r["dur"] or 0) / 3600, 1), "chunks": c["n"], "chunks_embedded": c["emb"] or 0,
    }


# ------------------------------------------------------- segments / chunks

def replace_transcript(source_id: str, segments: list[dict], chunks: list[dict]) -> None:
    """Replace all segments and chunks for a source. Embeddings may be None (filled later)."""
    with tx() as conn:
        conn.execute("DELETE FROM segments WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        conn.executemany(
            "INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
            [(source_id, i, s["start"], s["end"], s["text"]) for i, s in enumerate(segments)],
        )
        conn.executemany(
            "INSERT INTO chunks (source_id, idx, start, end, text, embedding) VALUES (?,?,?,?,?,?)",
            [
                (source_id, i, c["start"], c["end"], c["text"], _pack(c.get("embedding")))
                for i, c in enumerate(chunks)
            ],
        )
        conn.execute("UPDATE sources SET revision=?, stage=CASE WHEN ? THEN 'chunks' ELSE 'transcript' END, spoken_chars=? WHERE id=?",
                     (segments_revision(segments), bool(chunks), sum(len(s_["text"]) for s_ in segments), source_id))
    # G5: a moved revision stales exactly the Claim evidence rows frozen on the old one (no-op for sources without Claims)
    try:
        if connect().execute("SELECT 1 FROM claim_evidence WHERE source_id=? LIMIT 1", (source_id,)).fetchone():
            from . import claims
            claims.stale_by_source(source_id)
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("claim staleness hook skipped: %s", e)


def segments_revision(segments: list[dict[str, Any]]) -> str:
    """SHA-256 of the normalised transcript text: the source's revision. Same words → same revision."""
    import hashlib
    h = hashlib.sha256()
    for s in segments:
        h.update(" ".join(str(s.get("text") or "").split()).lower().encode())
        h.update(b"\n")
    return h.hexdigest()[:16]


def source_revision(source_id: str) -> str | None:
    row = connect().execute("SELECT revision FROM sources WHERE id=?", (source_id,)).fetchone()
    if row and row["revision"]:
        return row["revision"]
    segs = get_segments(source_id)
    if not segs:
        return None
    rev = segments_revision(segs)
    with tx() as conn:
        conn.execute("UPDATE sources SET revision=? WHERE id=?", (rev, source_id))
    return rev


def get_segments(source_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT idx, start, end, text FROM segments WHERE source_id=? ORDER BY idx", (source_id,)
    ).fetchall()]


def get_chunks(source_id: str) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in connect().execute(  # type: ignore[misc]
        "SELECT id, source_id, idx, start, end, text FROM chunks WHERE source_id=? ORDER BY idx", (source_id,)
    ).fetchall()]


def chunks_missing_embeddings(limit: int = 500, source_id: str | None = None) -> list[dict[str, Any]]:
    """Granular embedding checkpoint: a chunk either has its vector or it doesn't — resuming means embedding the rest."""
    if source_id:
        return [dict(r) for r in connect().execute("SELECT id, text FROM chunks WHERE embedding IS NULL AND source_id=? LIMIT ?", (source_id, limit)).fetchall()]
    return [dict(r) for r in connect().execute(
        "SELECT id, text FROM chunks WHERE embedding IS NULL LIMIT ?", (limit,)
    ).fetchall()]


def set_embeddings(pairs: list[tuple[int, np.ndarray]]) -> None:
    if not pairs:
        return
    with tx() as conn:
        conn.executemany("UPDATE chunks SET embedding=? WHERE id=?", [(_pack(e), cid) for cid, e in pairs])
        row = conn.execute("SELECT value FROM kv WHERE key=?", (CHUNK_EMBEDDING_REVISION_KEY,)).fetchone()
        try:
            revision = int(row["value"] if row else 0) + 1
        except (TypeError, ValueError):
            revision = 1
        conn.execute("""INSERT INTO kv (key, value) VALUES (?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                     (CHUNK_EMBEDDING_REVISION_KEY, str(revision)))


def chunk_embedding_revision() -> int:
    try:
        return int(kv_get(CHUNK_EMBEDDING_REVISION_KEY) or 0)
    except (TypeError, ValueError):
        return 0


_T1_DERIVED_TABLES = {
    "project_notes": ("approved", "suggested"),
    "project_claims": ("proposed", "accepted"),
}


def set_derived_embedding(table: str, object_id: str, vector: np.ndarray, *, provider: str, model: str,
                          version: str, input_hash: str) -> None:
    """Write one versioned T1 vector; callers cannot accidentally write an unlabelled space."""
    if table not in _T1_DERIVED_TABLES:
        raise ValueError("unsupported derived-vector table")
    v = np.asarray(vector, dtype=np.float32).reshape(-1)
    if not len(v) or not np.isfinite(v).all():
        raise ValueError("derived vector must be finite and non-empty")
    with tx() as conn:
        conn.execute(f"""UPDATE {table} SET embedding=?, embedding_provider=?, embedding_model=?,
                       embedding_dimensions=?, embedding_input_hash=?, embedding_version=? WHERE id=?""",
                     (_pack(v), provider, model, int(v.size), input_hash, version, object_id))


def invalidate_derived_embedding(table: str, object_id: str) -> None:
    """Clear a derived vector and all identity fields when its source content changes."""
    if table not in _T1_DERIVED_TABLES:
        raise ValueError("unsupported derived-vector table")
    with tx() as conn:
        conn.execute(f"""UPDATE {table} SET embedding=NULL, embedding_provider=NULL, embedding_model=NULL,
                       embedding_dimensions=NULL, embedding_input_hash=NULL, embedding_version=NULL WHERE id=?""", (object_id,))


def load_versioned_derived_embeddings(table: str, project_id: str, *, provider: str, model: str,
                                      version: str, dimensions: int) -> list[dict[str, Any]]:
    """Return only canonical vectors from the requested space; legacy or corrupt rows fail open."""
    if table not in _T1_DERIVED_TABLES:
        raise ValueError("unsupported derived-vector table")
    statuses = _T1_DERIVED_TABLES[table]
    qs = ",".join("?" for _ in statuses)
    rows = connect().execute(f"""SELECT id, project_id, embedding, embedding_input_hash, embedding_dimensions
        FROM {table} WHERE project_id=? AND status IN ({qs}) AND embedding IS NOT NULL
          AND embedding_provider=? AND embedding_model=? AND embedding_version=? AND embedding_dimensions=?""",
        (project_id, *statuses, provider, model, version, dimensions)).fetchall()
    out = []
    for row in rows:
        try:
            vec = _unpack(row["embedding"])
            if vec.size != dimensions or not np.isfinite(vec).all():
                continue
        except (TypeError, ValueError):
            continue
        out.append({"id": row["id"], "project_id": row["project_id"], "embedding": vec,
                    "input_hash": row["embedding_input_hash"], "dimensions": row["embedding_dimensions"]})
    return out


def _pack(vec: Any) -> bytes | None:
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def _unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def load_embedding_matrix(source_ids: list[str] | None = None) -> tuple[np.ndarray, list[int]]:
    """Return (matrix [n, d], chunk_ids). Fine for tens of thousands of chunks."""
    conn = connect()
    if source_ids:
        qs = ",".join("?" for _ in source_ids)
        rows = conn.execute(
            f"SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL AND source_id IN ({qs})", source_ids
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL").fetchall()
    if not rows:
        return np.zeros((0, 0), dtype=np.float32), []
    ids = [r["id"] for r in rows]
    mat = np.vstack([_unpack(r["embedding"]) for r in rows])
    return mat, ids


def get_chunks_by_ids(ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    qs = ",".join("?" for _ in ids)
    rows = connect().execute(
        f"""SELECT c.id, c.source_id, c.idx, c.start, c.end, c.text,
                   s.title, s.url, s.platform, s.channel, s.published_at, s.external_id
            FROM chunks c JOIN sources s ON s.id = c.source_id WHERE c.id IN ({qs})""", ids
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def fts_search(query: str, limit: int = 40, source_ids: list[str] | None = None) -> list[tuple[int, float]]:
    """Full-text search. Returns [(chunk_id, bm25_score)] with lower = better (SQLite convention), converted to positive."""
    conn = connect()
    q = _fts_query(query)
    if not q:
        return []
    sql = "SELECT c.id, bm25(chunks_fts) AS score FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ?"
    args: list[Any] = [q]
    if source_ids:
        sql += " AND c.source_id IN (" + ",".join("?" for _ in source_ids) + ")"
        args += source_ids
    sql += " ORDER BY score LIMIT ?"
    args.append(limit)
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(r["id"], -float(r["score"])) for r in rows]


def _fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 query: quoted terms OR'd together (each term prefix-matched)."""
    import re
    terms = [t for t in re.findall(r"[\w']+", query.lower()) if len(t) > 1]
    if not terms:
        return ""
    stop = {"the", "and", "or", "of", "to", "in", "is", "it", "a", "an", "what", "how", "does", "do", "did",
            "about", "for", "on", "with", "that", "this", "are", "was", "were", "be", "they", "he", "she", "say",
            "said", "talk", "mention", "anyone", "who", "when", "where", "why", "which", "there", "any", "can"}
    terms = [t for t in terms if t not in stop] or terms
    return " OR ".join(f'"{t}"' for t in terms[:12])


# ----------------------------------------------------------- collections

def upsert_collection(kind: str, external_id: str | None, url: str | None, title: str | None) -> dict[str, Any]:
    with tx() as conn:
        row = None
        if external_id:
            row = conn.execute("SELECT * FROM collections WHERE kind=? AND external_id=?", (kind, external_id)).fetchone()
        if row:
            if title:
                conn.execute("UPDATE collections SET title=?, url=COALESCE(?, url) WHERE id=?", (title, url, row["id"]))
            cid = row["id"]
        else:
            cid = new_id()
            conn.execute(
                "INSERT INTO collections (id, kind, url, title, external_id, created_at) VALUES (?,?,?,?,?,?)",
                (cid, kind, url, title, external_id, now()),
            )
        return dict(conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone())


def link_source_collection(source_id: str, collection_id: str) -> None:
    with tx() as conn:
        conn.execute("INSERT OR IGNORE INTO source_collections VALUES (?,?)", (source_id, collection_id))


def link_collection_candidates(collection_id: str, candidate_ids: Iterable[str]) -> int:
    """Record durable catalog membership without turning candidates into Sources.

    `source_collections` has deliberately different semantics: every attached project receives those Sources.
    A catalog is only a set of possible captures, so its membership lives here and is reconciled into each
    project's Candidate Index without affecting project_sources.
    """
    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return 0
    t = now()
    with tx() as conn:
        if not conn.execute("SELECT 1 FROM collections WHERE id=?", (collection_id,)).fetchone():
            raise KeyError(collection_id)
        conn.executemany(
            "INSERT INTO collection_candidates (collection_id, candidate_id, first_seen_at, last_seen_at) VALUES (?,?,?,?) "
            "ON CONFLICT(collection_id, candidate_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            [(collection_id, cid, t, t) for cid in ids],
        )
        # A newly remembered catalog row becomes known to every project that explicitly attached this catalog.
        # INSERT OR IGNORE preserves each project's state, relevance, reason and first-seen timestamp.
        conn.execute(
            "INSERT OR IGNORE INTO candidate_projects (candidate_id, project_id, state, origin, first_seen_at, updated_at) "
            "SELECT cc.candidate_id, pc.project_id, 'available', ?, ?, ? "
            "FROM collection_candidates cc JOIN project_collections pc ON pc.collection_id=cc.collection_id "
            "WHERE cc.collection_id=?",
            (json.dumps({"kind": "catalog", "collection_id": collection_id}), t, t, collection_id),
        )
    return len(ids)


def collection_candidate_ids(collection_id: str) -> list[str]:
    """Candidate membership for a durable catalog. This never implies Source ownership."""
    return [r["candidate_id"] for r in connect().execute(
        "SELECT candidate_id FROM collection_candidates WHERE collection_id=? ORDER BY first_seen_at, candidate_id",
        (collection_id,),
    ).fetchall()]


def list_collections() -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        """SELECT c.*, COUNT(sc.source_id) AS n_sources FROM collections c
           LEFT JOIN source_collections sc ON sc.collection_id = c.id
           GROUP BY c.id ORDER BY c.created_at DESC"""
    ).fetchall()]


def get_collection(collection_id: str) -> dict[str, Any] | None:
    row = connect().execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
    return dict(row) if row else None


def project_collection_ids(project_id: str) -> list[str]:
    """Every collection this project is attached to, via project_collections. CR3/CR4 (reservoir.py) use this
    to enumerate what a project's own on-demand rescan covers -- never automatic, never scheduled."""
    return [r["collection_id"] for r in connect().execute(
        "SELECT collection_id FROM project_collections WHERE project_id=?", (project_id,)).fetchall()]


def project_has_collection(project_id: str, collection_id: str) -> bool:
    """Whether this project explicitly attached this collection.

    Catalog membership is global, while every review, refresh, and capture
    decision is project-relative.  Callers must establish this relationship
    before touching catalog state so a guessed collection id cannot create a
    candidate decision or a queue job in another project's scope.
    """
    return bool(connect().execute(
        "SELECT 1 FROM project_collections WHERE project_id=? AND collection_id=?",
        (project_id, collection_id),
    ).fetchone())


# ------------------------------------------------------------------ jobs

JOB_ACTIVE = ("queued", "running", "external_pending")
JOB_TERMINAL = ("done", "failed", "cancelled")
DEP_POLICIES = ("ALL_SUCCESS", "ALL_TERMINAL", "ANY_SUCCESS")
LEASE_SECONDS = 120.0


# ---- provider invocation ledger: exactly-once is only guaranteed for database effects; a synchronous API call whose
# response was lost is an *ambiguous* execution (the provider may have charged us). We record intent before the
# request and mark in-flight calls of a dead run OUTCOME_UNKNOWN on recovery, so no preventable duplicate is made and
# every ambiguous one is visible and accounted for.

def invocation_start(provider: str, task: str | None, model: str | None, input_hash: str | None, job_id: str | None, run_id: str | None,
                     logical_id: str | None = None, attempt_no: int = 1) -> str:
    """One row per TRANSPORT ATTEMPT; attempts of the same logical invocation (task → one request the caller wanted
    made) share logical_id. SDK-level retries are disabled so every network execution is a row here."""
    iid = new_id()
    t = now()
    with tx() as conn:
        conn.execute("INSERT INTO invocations (id, job_id, run_id, task, provider, model, input_hash, state, requested_at, logical_id, attempt_no, fallback_used, fallback_policy_version) VALUES (?,?,?,?,?,?,?,'intent',?,?,?,0,?)",
                     (iid, job_id, run_id, task, provider, model, input_hash, t, logical_id or iid, attempt_no, FALLBACK_POLICY_VERSION))
        conn.execute("UPDATE invocations SET state='in_flight' WHERE id=?", (iid,))
    return iid


def invocation_finish(iid: str, state: str, provider_request_id: str | None = None, error: str | None = None, error_type: str | None = None,
                      returned_model: str | None = None) -> None:
    with tx() as conn:
        conn.execute("UPDATE invocations SET state=?, completed_at=?, provider_request_id=?, error=?, error_type=?, returned_model=? WHERE id=?",
                     (state, now(), provider_request_id, (error or None) and error[:500], error_type, returned_model, iid))


def get_invocation_state(iid: str) -> str | None:
    r = connect().execute("SELECT state FROM invocations WHERE id=?", (iid,)).fetchone()
    return r["state"] if r else None


def invocation_attempts(logical_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute("SELECT * FROM invocations WHERE logical_id=? ORDER BY attempt_no", (logical_id,)).fetchall()]


def mark_ambiguous_invocations(job_id: str, run_id: str | None, conn: sqlite3.Connection | None = None) -> int:
    """A run died: every call it had in flight is now OUTCOME_UNKNOWN."""
    c = conn or connect()
    rows = c.execute("SELECT id, task, model FROM invocations WHERE job_id=? AND state='in_flight'" + (" AND run_id=?" if run_id else ""),
                     (job_id, *([run_id] if run_id else []))).fetchall()
    for r in rows:
        c.execute("UPDATE invocations SET state='outcome_unknown', completed_at=? WHERE id=?", (now(), r["id"]))
        job_event(job_id, "ambiguous_external_execution", run_id=run_id, conn=c, invocation=r["id"], task=r["task"], model=r["model"])
    if conn is None:
        c.commit()
    return len(rows)


def ambiguous_invocations(limit: int = 100) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute("SELECT * FROM invocations WHERE state='outcome_unknown' ORDER BY requested_at DESC LIMIT ?", (limit,)).fetchall()]


def _resolve_job_inflight(conn: sqlite3.Connection, job_id: str) -> int:
    """The job is over; anything it left in flight is OUTCOME_UNKNOWN — never silently 'completed'. Whether the
    provider actually executed the call is genuinely unknown once the run that owned it is gone, and the ledger
    has a state for exactly that. `mark_ambiguous_invocations` covered only the lease-expiry path; cancelling or
    failing a job took a different route and leaked (432 rows on Kyle's live database, every one of them a batch
    findings call whose job had been cancelled)."""
    cur = conn.execute("UPDATE invocations SET state='outcome_unknown', completed_at=COALESCE(completed_at, ?) "
                       "WHERE job_id=? AND state='in_flight'", (now(), job_id))
    return cur.rowcount or 0


def _resolve_orphan_invocations(conn: sqlite3.Connection) -> int:
    """Startup safety net for the above: any call still in flight whose job already reached a terminal state.
    Runs unconditionally on every start (like `_backfill_job_lanes`, and for the same reason) so a path nobody
    thought of still self-heals rather than accumulating silently."""
    cur = conn.execute("UPDATE invocations SET state='outcome_unknown', completed_at=COALESCE(completed_at, ?) "
                       "WHERE state='in_flight' AND job_id IN (SELECT id FROM jobs WHERE status IN ('done','failed','cancelled'))",
                       (now(),))
    conn.commit()
    return cur.rowcount or 0


def project_research_revision(project_id: str) -> str:
    """A cheap fingerprint of everything a project's $0 research derivations depend on — Claims, knowledge nodes,
    tensions, per-source analyses and the project row itself. COUNT as well as MAX(updated_at) so a deletion moves
    it too, not just an edit. Measured at ~5 ms warm on Kyle's live database against the 1.5 s of research
    computation it guards (SPEED-MISSION.md R2), which is the whole reason the caches key on this rather than a
    clock: a revision cannot go stale, a TTL can."""
    r = connect().execute(
        "SELECT (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_claims WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_knowledge_nodes WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM research_tensions WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_source_analysis WHERE project_id=?),"
        # 0.63.19 — evidence TARGETS were missing from this fingerprint, and the open questions are exactly what
        # `candidates._gap_terms` turns into "fits an open question". So the pool's fit reasons and every skipped
        # row's potential score went stale the moment a question was added, satisfied or dropped — silently, since
        # 0.46.1, because the cache key could not see the change. Found by a test of a NEW cache on the same key
        # (S34) rather than by anything going visibly wrong.
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_evidence_targets WHERE project_id=?),"
        "       (SELECT COALESCE(updated_at,0) FROM projects WHERE id=?)",
        (project_id,) * 6).fetchone()
    return "|".join(str(x) for x in r)


ACCOUNT_GATES = ("providers:billing_until", "providers:spend_cap_until")


def account_gate_active() -> tuple[str, float] | None:
    """(gate, until) when the ACCOUNT itself is walled and the wall has not expired, else None. Read by `claim_job`
    (0.59.0) so a capped account stops the queue instead of being discovered one job at a time."""
    for g in ACCOUNT_GATES:
        try:
            until = float(kv_get(g) or 0)
        except (TypeError, ValueError):
            continue
        if until > now():
            return (g, until)
    return None


def clear_account_gates() -> list[str]:
    """Drop the ACCOUNT-level blocks the app is holding. Returns the ones that were actually set.

    `providers:billing_until` always cleared itself on a successful call. `providers:spend_cap_until` did not — it
    was set on SPEND_CAP and cleared nowhere, so a usage limit RAISED in the Anthropic Console could never unblock
    the app: the stored date (up to a month out) kept gating `usage.check()`, and because that same date parks every
    job's `not_before`, nothing would ever attempt the call that would prove the block was gone. The banner outlived
    the condition — the same failure 0.45.13's "Check now" fixed per job, still live at the account level.

    A gate is a CACHED BELIEF about the account, and only two things may retire it: a call that works (providers
    calls this on success), or the user saying the situation changed (the Re-check button). Clearing optimistically
    is safe and cheap — if the block is still real the next attempt re-sets it immediately, and a request refused
    for a usage limit or credit balance fails before any generation, so it costs nothing."""
    cleared = [k for k in ACCOUNT_GATES if float(kv_get(k) or 0)]
    for k in cleared:
        kv_set(k, "0")
    return cleared


def release_budget_waits() -> int:
    """Wake every job parked on an ACCOUNT gate (`wait_reason='budget'`), so clearing the gate actually lets work
    resume instead of leaving jobs sitting on a `not_before` that was derived from the same stale belief. Only
    timer-parked queued jobs are touched; dependency-blocked and running jobs are left exactly alone."""
    with tx() as conn:
        cur = conn.execute("UPDATE jobs SET not_before=NULL, wait_reason=NULL, updated_at=? "
                           "WHERE status='queued' AND wait_reason='budget' AND not_before IS NOT NULL", (now(),))
        return cur.rowcount or 0


def count_active_jobs() -> int:
    return connect().execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','external_pending')").fetchone()[0]


def project_notes_revision(project_id: str) -> str:
    """The fingerprint of a project's findings ALONE — count, newest, and a count per status (0.61.5).

    `project_view_revision` is the Sources fingerprint and its `sources`/`jobs` components are global on purpose,
    which makes it wrong as a key for anything expensive: during an ingest run it moves whenever any job anywhere
    moves. The findings list depends on `project_notes` and nothing else. `project_notes` has no `updated_at`, so
    the per-status counts stand in for one — approving, dismissing or reserving a finding moves this string, and a
    job heartbeat does not.

    Every status is counted, not just approved and suggested: a finding moving between two statuses the caller is
    not currently showing still changes the page it belongs on."""
    c = connect()
    parts = c.execute(
        "SELECT COUNT(*), COALESCE(MAX(created_at),0) FROM project_notes WHERE project_id=?", (project_id,)).fetchone()
    by_status = c.execute(
        "SELECT status, COUNT(*) FROM project_notes WHERE project_id=? GROUP BY status ORDER BY status", (project_id,)).fetchall()
    tail = ",".join(f"{r[0]}={r[1]}" for r in by_status)
    return f"{parts[0]}:{parts[1]}:{tail}"


def project_usage_revision(project_id: str) -> str:
    """Fingerprint only the inputs read by ``findings_view.usage_map``.

    The old cache used ``project_view_revision``, whose global jobs component changes on every heartbeat. That made
    a queue update retire a full notes/plan/chat/Claims walk even though no usage fact had changed. Keep this key
    deliberately narrow: findings, the latest plan body, assistant citations, Claims, and finding-to-Claim links.
    Counts sit beside timestamps because deletions and link-table changes have no timestamp of their own.
    """
    c = connect()
    r = c.execute(
        "SELECT (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM plans WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(m.created_at),0) FROM messages m "
        "          JOIN conversations c ON c.id=m.conversation_id WHERE c.project_id=? AND m.role='assistant'),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_claims WHERE project_id=?),"
        "       (SELECT COUNT(*) FROM claim_evidence_notes e JOIN project_claims c ON c.id=e.claim_id "
        "          WHERE c.project_id=?)",
        (project_id,) * 4).fetchone()
    return project_notes_revision(project_id) + "|" + "|".join(str(x) for x in r)


def project_pool_revision(project_id: str) -> str:
    """The fingerprint of the known-but-uncaptured pool ALONE (0.63.20).

    Deliberately NOT `project_view_revision`: that one's `jobs` component is global, so during an ingest run it
    moves whenever any job anywhere heartbeats, and a 2.3 s assembly keyed on it would be retired before it could
    ever be reused — the failure 0.62.0 already paid for once with the findings rows. What the pool actually reads
    is the Candidate Index, the skipped sources, this project's membership and priorities, and the research state
    its "fits an open question" term comes from. A job moving does not change any of those.

    `project_sources` has no `updated_at`, so COUNTS stand in for one. Starring a source changes every row's
    `same_creator_as_priority` without touching a timestamp, and **removing a source from the project sets
    `excluded=1` rather than deleting the row** (0.34.2's durable "removed from this project" marker), so the
    plain count does not move either — the frozen S5 gate caught that one, which is the right place for it to
    be caught: a cache that outlives the user's own removal is wrong, not stale (0.62.8). `candidates` is global for the same reason
    `project_view_revision`'s `sources` is — a candidate's title can be rewritten by an exploration pass that knows
    nothing about this project, and over-invalidating costs a recompute while under-invalidating costs a wrong
    screen."""
    r = connect().execute(
        "SELECT (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM candidate_projects WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(last_seen_at),0) FROM candidates),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM candidate_links WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM sources WHERE status='skipped'),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(suggested_at),0)||':'"
        "               ||COALESCE(SUM(CASE WHEN priority THEN 1 ELSE 0 END),0)||':'"
        "               ||COALESCE(SUM(CASE WHEN excluded THEN 1 ELSE 0 END),0) FROM project_sources WHERE project_id=?),"
        "       (SELECT COUNT(*) FROM project_notes WHERE project_id=?)",
        (project_id, project_id, project_id, project_id)).fetchone()
    return "|".join(str(x) for x in r) + "|" + project_research_revision(project_id)


def conversation_delta_revision(project_id: str) -> str:
    """CHR1 (docs/CHAT-REFRESH-PLAN.md §11): the narrow fingerprint of ONLY what Conversation Delta reads. Deliberately
    NOT project_view_revision — SPEED-AUDIT-2026-09-17.md §9 measured that key invalidating on every job heartbeat
    anywhere in the project, which would retire a delta computation before it could ever be reused (the same failure
    project_pool_revision and project_usage_revision were built to avoid). Nothing here is global and nothing here is
    a job or a heartbeat.

    Source membership is fingerprinted by resolving the REAL membership set (project_source_ids, ready_only=False —
    direct + collections + tags, minus exclusions) rather than approximating it from project_sources/collections
    counts: a source attached from the global library keeps its own old created_at, so only a hash of the actual id
    set (not a count or a max-timestamp) is guaranteed to move when membership changes. This is the same call
    ask() already makes every turn, so its cost is not new to the app — only new to this cache key.

    Moves for: membership/exclusion changes, a scoped source's status or revision changing (pending→ready, a
    re-transcription), Findings additions/status changes, Claim additions/updates, new claim_evidence, tensions,
    evidence targets, and the current plan's identity (plan-impact annotations depend on it). Does NOT move for:
    unrelated jobs, other projects, or usage/UI state — none of those are read here."""
    import hashlib
    conn = connect()
    ids = project_source_ids(project_id, ready_only=False)
    id_hash = hashlib.sha1(",".join(ids).encode()).hexdigest()[:12] if ids else "0"
    src = "0:0"
    if ids:
        placeholders = ",".join("?" * len(ids))
        r = conn.execute(f"SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM sources WHERE id IN ({placeholders})", ids).fetchone()
        src = str(r[0])
    r = conn.execute(
        "SELECT (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_claims WHERE project_id=?),"
        "       (SELECT COALESCE(MAX(ce.id),0) FROM claim_evidence ce JOIN project_claims c ON c.id=ce.claim_id WHERE c.project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM research_tensions WHERE project_id=?),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM project_evidence_targets WHERE project_id=?),"
        "       (SELECT id||':'||COALESCE(updated_at,0) FROM plans WHERE project_id=? ORDER BY version DESC LIMIT 1)",
        (project_id,) * 5).fetchone()
    return "|".join([f"src={id_hash}:{src}", project_notes_revision(project_id), f"claims={r[0]}", f"ce={r[1]}",
                     f"tensions={r[2]}", f"targets={r[3]}", f"plan={r[4] or 'none'}"])


def conversation_message_revision(conversation_id: str) -> str:
    """CHR2: append-only fingerprint for this conversation's own messages.

    The project revision does not move when a conversation gains another turn without a project-level change,
    so the delta cache also needs this conversation-scoped fingerprint. COUNT paired with MAX(id) catches the
    delete-then-reinsert case as well as ordinary appends.
    """
    r = connect().execute(
        "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM messages WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()
    return f"{r[0]}:{r[1]}"


def project_view_revision(project_id: str) -> dict[str, str]:
    """R2: the cheap fingerprint of everything the Sources view renders — measured at ~6 ms against the 440 ms the
    view itself costs, which is what lets a 3 s poll ask "did anything change?" instead of rebuilding the answer.

    `sources` and `jobs` are deliberately GLOBAL rather than project-scoped. Project membership also comes through
    collections and tags, so a project-scoped source fingerprint would miss a source joining that way and the view
    would silently go stale — over-invalidating across projects costs a recompute, under-invalidating costs a wrong
    screen, and only one of those is acceptable. COUNT sits beside MAX(updated_at) everywhere so deletions move the
    revision too."""
    c = connect()
    r = c.execute(
        "SELECT (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM sources),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),0) FROM jobs),"
        "       (SELECT COUNT(*)||':'||COALESCE(MAX(created_at),0)||':'"
        "               ||SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END)||':'"
        "               ||SUM(CASE WHEN status='suggested' THEN 1 ELSE 0 END) FROM project_notes WHERE project_id=?)",
        (project_id,)).fetchone()
    # project_notes has no updated_at, so the status counts stand in for it: approving a finding changes what the
    # Sources rows show (their suggested/approved badges) without touching any timestamp.
    return {"sources": str(r[0]), "jobs": str(r[1]), "notes": str(r[2]), "research": project_research_revision(project_id)}


def _pctile(vals: list[float], p: float) -> float:
    return round(sorted(vals)[min(len(vals) - 1, int(len(vals) * p))], 2) if vals else 0.0


def job_timing(since: float) -> list[dict[str, Any]]:
    """R0: per job kind, how long the work took versus how long it WAITED to start — SPEED-MISSION.md §A's
    central finding (findings jobs: 8.6 s of work behind 479 s of waiting) regenerating itself from live data."""
    work: dict[str, list[float]] = {}
    wait: dict[str, list[float]] = {}
    for r in connect().execute("SELECT kind, finished_at-started_at d, started_at-created_at w FROM jobs "
                               "WHERE status='done' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND created_at>=?",
                               (since,)).fetchall():
        if r["d"] is not None and r["d"] >= 0:
            work.setdefault(r["kind"], []).append(r["d"])
        if r["w"] is not None and r["w"] >= 0:
            wait.setdefault(r["kind"], []).append(r["w"])
    out = [{"kind": k, "n": len(v), "work_p50": _pctile(v, 0.5), "work_p90": _pctile(v, 0.9),
            "wait_p50": _pctile(wait.get(k, []), 0.5), "wait_p90": _pctile(wait.get(k, []), 0.9)} for k, v in work.items()]
    for row in out:
        row["waiting_share"] = round(row["wait_p50"] / (row["wait_p50"] + row["work_p50"]), 3) if (row["wait_p50"] + row["work_p50"]) else 0.0
    return sorted(out, key=lambda r: -r["wait_p50"])


def model_timing(since: float) -> list[dict[str, Any]]:
    """R0: per task × provider model latency — the local-vs-API ratio the routing decisions rest on."""
    g: dict[tuple[str, str], list[float]] = {}
    for r in connect().execute("SELECT task, provider, completed_at-requested_at d FROM invocations "
                               "WHERE state='completed' AND completed_at IS NOT NULL AND requested_at>=?", (since,)).fetchall():
        if r["d"] is not None and r["d"] >= 0:
            g.setdefault((r["task"] or "?", r["provider"]), []).append(r["d"])
    return sorted([{"task": t, "provider": p, "n": len(v), "p50": _pctile(v, 0.5), "p90": _pctile(v, 0.9)}
                   for (t, p), v in g.items()], key=lambda r: -r["p50"])


def invocation_counts(since: float | None = None) -> dict[str, int]:
    q = "SELECT state, COUNT(*) n FROM invocations" + (" WHERE requested_at>=?" if since else "") + " GROUP BY state"
    return {r["state"]: r["n"] for r in connect().execute(q, (since,) if since else ()).fetchall()}


def job_event(job_id: str, event_type: str, *, run_id: str | None = None, stage: str | None = None, conn: sqlite3.Connection | None = None, **payload: Any) -> None:
    """Append to the job's history (jobs = current state, job_events = what happened)."""
    row = (time.time(), job_id, run_id, event_type, stage, json.dumps(payload, default=str) if payload else None)
    if conn is not None:
        conn.execute("INSERT INTO job_events (ts, job_id, run_id, event_type, stage, payload) VALUES (?,?,?,?,?,?)", row)
        return
    with tx() as c:
        c.execute("INSERT INTO job_events (ts, job_id, run_id, event_type, stage, payload) VALUES (?,?,?,?,?,?)", row)


def job_events(job_id: str, limit: int = 500) -> list[dict[str, Any]]:
    out = []
    for r in connect().execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id LIMIT ?", (job_id, limit)).fetchall():
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
        except ValueError:
            pass
        out.append(d)
    return out


def dedupe_key_for(kind: str, payload: dict[str, Any]) -> str | None:
    """Natural identity of a unit of work, so the same request twice is one job while it is active."""
    if kind == "ingest_url":
        return f"ingest:{payload.get('url')}"
    if kind == "explore":
        return f"explore:{payload.get('project_id')}:{payload.get('url')}"
    if kind == "enrich_profiles_batch":
        return "profiles:batch"
    if kind == "ingest_source":
        return f"ingest_source:{payload.get('source_id')}"
    if kind == "recover_captions":
        return f"recover_captions:{payload.get('project_id')}:{payload.get('source_id')}"
    if kind == "refresh_skipped_metadata":
        return f"refresh_skipped_metadata:{payload.get('project_id')}:{payload.get('source_id')}"
    if kind == "suggest_findings" and len(payload.get("source_ids") or []) == 1:
        # D2: a deep read is its OWN unit of work — without the depth here, pressing "Read deeper" while an ordinary
        # findings job for that source is queued silently returns the shallow job (0.45.0 fix)
        return f"findings:{payload.get('project_id')}:{payload['source_ids'][0]}" + (":deep" if payload.get("depth") == "deep" else "")
    if kind == "bootstrap_scan":
        return f"bootstrap:{payload.get('project_id')}"
    if kind == "rank_proposed":
        return f"rank:{payload.get('collection_id')}"
    if kind == "build_plan":
        return f"plan:{payload.get('project_id')}"
    if kind == "discover":
        return f"discover:{payload.get('project_id')}:{payload.get('refine') or ''}"
    if kind == "extract_claims":
        # a fast pass over a named few is its OWN unit of work, exactly like a deep read above: without this the
        # bulk pass queued alongside it silently returns the fast job and the rest of the pile is never extracted.
        return f"claims:{payload.get('project_id')}" + (":fast" if payload.get("claim_ids") else "")
    return None


EXECUTION_POLICIES = ("local_preferred", "local_only", "api_requested", "api_only")


def set_job_policy(job_id: str, policy: str) -> dict[str, Any] | None:
    assert policy in EXECUTION_POLICIES, policy
    with tx() as conn:
        conn.execute("UPDATE jobs SET execution_policy=?, updated_at=? WHERE id=?", (policy, now(), job_id))
        job_event(job_id, "policy", conn=conn, policy=policy)
    return get_job(job_id)


def set_job_lane(job_id: str, lane: str) -> dict[str, Any] | None:
    assert lane in ("normal", "slow", "priority", "low"), lane
    with tx() as conn:
        conn.execute("UPDATE jobs SET lane=?, updated_at=? WHERE id=?", (lane, now(), job_id))
        job_event(job_id, "lane", conn=conn, lane=lane)
    return get_job(job_id)


def set_job_execution(job_id: str, executed_by: str | None, fallback_reason: str | None) -> None:
    with tx() as conn:
        conn.execute("UPDATE jobs SET executed_by=?, fallback_reason=? WHERE id=?", (executed_by, fallback_reason, job_id))


def create_job(kind: str, payload: dict, blocked_by: list[str] | None = None, dependency_policy: str = "ALL_SUCCESS",
               dedupe_key: str | None = None, execution_policy: str = "local_preferred", lane: str = "normal",
               not_before: float | None = None, job_id: str | None = None) -> dict[str, Any]:
    """blocked_by: job ids that must finish before this one can be claimed (see dependency_policy). dedupe_key (natural
    identity of the work; default from dedupe_key_for) makes a second identical request while the first is still
    active return the existing job instead of a duplicate.

    not_before (L-20, EXECUTION-LADDER.md P1A): a caller asking for the job to run no earlier than a future time
    (e.g. "rebuild stale sources tonight"). `not_before` and `wait_reason` are pre-existing columns/machinery,
    already correctly honored by claim_job()'s claiming query and cleared at claim time -- this is the first
    caller-facing entry point for them; every prior setter was internal (retry/budget/rate-limit waits). A
    caller-requested wait gets its own wait_reason ('scheduled') so the account-gate and budget-valve resume
    sweeps (db.release_budget_waits, api.py's /api/usage settings sweep) can tell "waiting because I asked for
    2am" apart from "waiting because the account is out of budget" and never wake a scheduled job early. The
    original request is ALSO kept in the payload as `_scheduled_for` (not_before) since claim_job() nulls the
    `not_before` column itself at claim time (by design, to clear the wait once satisfied) -- without a payload
    copy the "scheduled vs actual start" provenance ruling (missed-window policy) would have nothing to compare
    against once the job actually runs."""
    # job_id: caller-supplied id (create_or_get_capture_ingest_request is the only caller that ever passes this) --
    # lets that caller pre-generate the id so a capture_events row can embed ingest_job_id in the SAME insert that
    # creates it, rather than a later UPDATE. Falls back to a fresh id exactly as before when omitted.
    assert dependency_policy in DEP_POLICIES, dependency_policy
    key = dedupe_key or dedupe_key_for(kind, payload)
    blocked_by = list(dict.fromkeys(blocked_by)) if blocked_by else None      # de-duplicated, order kept
    if not_before is not None:
        payload = {**payload, "_scheduled_for": not_before}
    with tx() as conn:
        if blocked_by:
            _check_no_cycle(conn, None, blocked_by)
        if key:
            marks = ",".join("?" for _ in JOB_ACTIVE)
            ex = conn.execute(f"SELECT id FROM jobs WHERE dedupe_key=? AND status IN ({marks}) ORDER BY created_at LIMIT 1", (key, *JOB_ACTIVE)).fetchone()
            if ex:
                job_event(ex["id"], "deduplicated", conn=conn, kind=kind)
                return get_job(ex["id"])  # type: ignore[return-value]
        jid = job_id or new_id()
        assert execution_policy in EXECUTION_POLICIES, execution_policy
        from .ledger import origin_for_job
        o_actor, o_req = origin_for_job()
        conn.execute(
            "INSERT INTO jobs (id, kind, payload, created_at, blocked_by, message, dependency_policy, dedupe_key, execution_policy, lane, not_before, wait_reason, "
            "origin_actor_id, origin_request_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, kind, json.dumps(payload), now(), json.dumps(blocked_by) if blocked_by else None,
             f"waiting for {len(blocked_by)} upstream job{'s' if len(blocked_by) != 1 else ''}" if blocked_by else
             (f"scheduled — runs when the worker is next available, no earlier than the requested time" if not_before is not None else None),
             dependency_policy, key, execution_policy,
             lane if lane in ("normal", "slow", "priority", "low") else "normal",
             not_before, "scheduled" if not_before is not None else None, o_actor, o_req),
        )
        job_event(jid, "queued", conn=conn, kind=kind, blocked_by=blocked_by or None, dedupe_key=key, not_before=not_before)
    return get_job(jid)  # type: ignore[return-value]


class DependencyCycle(ValueError):
    pass


def _check_no_cycle(conn: sqlite3.Connection, job_id: str | None, deps: list[str]) -> None:
    """Reject self-dependency, duplicates, and any direct or transitive cycle through blocked_by. A brand-new job
    (job_id None) cannot close a cycle — nothing depends on it yet — so only its list is validated."""
    if job_id is None:
        return
    if job_id in deps:
        raise DependencyCycle("a job cannot depend on itself")
    seen: set[str] = set()
    frontier = list(deps)
    while frontier:
        cur = frontier.pop()
        if cur == job_id:
            raise DependencyCycle(f"dependency cycle: {job_id[:8]} would wait on itself through {cur[:8]}")
        if cur in seen:
            continue
        seen.add(cur)
        r = conn.execute("SELECT blocked_by FROM jobs WHERE id=?", (cur,)).fetchone()
        if r and r["blocked_by"]:
            try:
                frontier.extend(json.loads(r["blocked_by"]))
            except ValueError:
                pass


def set_dependencies(job_id: str, deps: list[str]) -> None:
    """Rewire a job's dependencies, refusing cycles."""
    with tx() as conn:
        _check_no_cycle(conn, job_id, deps)
        conn.execute("UPDATE jobs SET blocked_by=?, updated_at=? WHERE id=?", (json.dumps(deps) if deps else None, now(), job_id))
        job_event(job_id, "dependencies_set", conn=conn, blocked_by=deps)


def dependency_report(job: dict[str, Any], conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """{policy, total, done, failed: [..], cancelled: [..], pending, state} — what a blocked job is waiting for."""
    deps = job.get("blocked_by") or []
    if isinstance(deps, str):
        try:
            deps = json.loads(deps)
        except ValueError:
            deps = []
    policy = job.get("dependency_policy") or "ALL_SUCCESS"
    rep: dict[str, Any] = {"policy": policy, "total": len(deps), "done": 0, "failed": [], "cancelled": [], "pending": 0, "state": "ready"}
    if not deps:
        return rep
    c = conn or connect()
    marks = ",".join("?" for _ in deps)
    rows = {r["id"]: r for r in c.execute(f"SELECT id, kind, status, payload FROM jobs WHERE id IN ({marks})", deps).fetchall()}
    for d in deps:
        r = rows.get(d)
        st = r["status"] if r else "missing"
        label = None
        if r:
            try:
                pl = json.loads(r["payload"] or "{}")
                label = pl.get("title") or (pl.get("source_ids") or [None])[0] or pl.get("source_id") or r["kind"]
            except ValueError:
                label = r["kind"]
        if st == "done":
            rep["done"] += 1
        elif st in ("failed", "missing"):
            rep["failed"].append({"id": d, "label": label, "status": st})
        elif st == "cancelled":
            rep["cancelled"].append({"id": d, "label": label})
        else:
            rep["pending"] += 1
    bad = len(rep["failed"]) + len(rep["cancelled"])
    if policy == "ALL_SUCCESS":
        rep["state"] = "failed" if bad else ("waiting" if rep["pending"] else "ready")
    elif policy == "ALL_TERMINAL":
        rep["state"] = "waiting" if rep["pending"] else "ready"
    else:   # ANY_SUCCESS
        rep["state"] = "ready" if rep["done"] else ("waiting" if rep["pending"] else "failed")
    return rep


def _deps_state(conn: sqlite3.Connection, job_row: Any) -> str:
    rep = dependency_report({"blocked_by": job_row["blocked_by"], "dependency_policy": job_row["dependency_policy"]}, conn)
    if rep["state"] == "failed":
        who = rep["failed"] + rep["cancelled"]
        return "failed:" + (who[0]["id"] if who else "?")
    return rep["state"]


def get_job(job_id: str) -> dict[str, Any] | None:
    return row_to_dict(connect().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def source_titles(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    q = ",".join("?" for _ in ids)
    return {r["id"]: (r["title"] or r["url"]) for r in connect().execute(f"SELECT id, title, url FROM sources WHERE id IN ({q})", tuple(ids)).fetchall()}


def list_jobs(limit: int = 50, statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM jobs"
    args: list[Any] = []
    if statuses:
        q += f" WHERE status IN ({','.join('?' for _ in statuses)})"
        args += list(statuses)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [row_to_dict(r) for r in connect().execute(q, args).fetchall()]  # type: ignore[misc]


def list_project_jobs(project_id: str, source_ids: Iterable[str], *, limit: int, statuses: tuple[str, ...] | None = None,
                      exclude_statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """R8: a project's jobs — those whose payload names the project, plus `ingest_source` jobs for its sources —
    straight from the generated-column indexes, newest first. Replaces `api_project_jobs`'s scan of every active
    job app-wide plus the 400 most recent (payload JSON decoded per row, then filtered in Python)."""
    idl = list(dict.fromkeys(source_ids))
    cond, cargs = "", []
    if statuses:
        cond += f" AND status IN ({','.join('?' for _ in statuses)})"
        cargs += list(statuses)
    if exclude_statuses:
        cond += f" AND status NOT IN ({','.join('?' for _ in exclude_statuses)})"
        cargs += list(exclude_statuses)
    # Two queries, merged here, on purpose: as one `OR` SQLite must union both index scans and re-sort the whole
    # union (MULTI-INDEX OR + temp b-tree — measured 205 ms on a copy of the 79k-row live table, no better than the
    # scan it replaces). Each half on its own walks its index in created_at order and stops at LIMIT: 26 ms.
    conn = connect()
    rows = conn.execute(f"SELECT * FROM jobs WHERE project_id=?{cond} ORDER BY created_at DESC LIMIT ?", [project_id, *cargs, limit]).fetchall()
    if idl:
        rows += conn.execute(f"SELECT * FROM jobs WHERE kind='ingest_source' AND source_id IN (SELECT value FROM json_each(?)){cond} "
                             "ORDER BY created_at DESC LIMIT ?", [json.dumps(idl), *cargs, limit]).fetchall()
    seen: dict[str, Any] = {}
    for r in rows:
        seen.setdefault(r["id"], r)
    out = sorted(seen.values(), key=lambda r: -(r["created_at"] or 0))[:limit]
    return [row_to_dict(r) for r in out]  # type: ignore[misc]


BACKGROUND_LANES = ("slow", "low")
BACKGROUND_KINDS = ("extract_claims",)        # paused whatever lane they are on (0.51.0 — see claim_job)
RATE_HELD_POLICIES = ("api_requested", "api_only")   # held while the spend-rate ceiling is tripped     # speculative work: bulk claim passes, caption recovery, metadata backfill
# 0.59.0 — ADMISSION FOR THE ACCOUNT WALLS. Measured on Kyle's live database: 624 `BILLING` attempts on 2026-09-09
# and 48 `SPEND_CAP` attempts inside 13 minutes on 2026-09-10. Every one was refused by Anthropic in ~0.4 s and cost
# nothing, but `claim_job` never consulted the account gates, so a walled account did not stop the queue — it walked
# the queue THROUGH the wall, claiming each paid job in turn, parking it with a 30-day delay, and claiming the next.
#
# The damage is not money, it is three other things: worker slots that free/local work could have used; a Jobs panel
# that reads as a catastrophe when the truth is "the account is capped"; and hundreds of ledger rows that make real
# spend impossible to see — they are why the first read of this ledger looked like it was undercounting cost.
#
# `jobs.execute` already parks each job correctly with the right banner and the parsed return date. This is the
# missing half: while a gate is live, do not CLAIM work that can only run on the API. Local and free work continues,
# which matters because `NEUROSEARCH_AI_PROFILE=local` means most findings work has somewhere else to go.
ACCOUNT_HELD_POLICIES = ("api_requested", "api_only")


def background_paused() -> bool:
    return kv_get("background_paused") == "1"


def set_background_paused(paused: bool) -> dict[str, Any]:
    """Pause/resume ONLY the speculative lanes. Running background jobs are asked to stop at their next safe point;
    that is safe to do because they are idempotent by construction (a claims group whose extraction_hash is already
    stamped is skipped without spend, caption recovery refuses a source it already recovered), so resuming re-does
    no paid work — it picks up from the first unfinished unit."""
    kv_set("background_paused", "1" if paused else "0")
    stopped = 0
    if paused:
        rows = connect().execute(
            f"SELECT id FROM jobs WHERE status='running' AND (lane IN ({','.join('?' for _ in BACKGROUND_LANES)}) "
            f"OR kind IN ({','.join('?' for _ in BACKGROUND_KINDS)})) AND cancel_requested_at IS NULL",
            (*BACKGROUND_LANES, *BACKGROUND_KINDS)).fetchall()
        for r in rows:
            request_cancel(r["id"])
            stopped += 1
    waiting = connect().execute(
        f"SELECT COUNT(*) FROM jobs WHERE status='queued' AND (lane IN ({','.join('?' for _ in BACKGROUND_LANES)}) "
        f"OR kind IN ({','.join('?' for _ in BACKGROUND_KINDS)}))", (*BACKGROUND_LANES, *BACKGROUND_KINDS)).fetchone()[0]
    return {"paused": paused, "stopped": stopped, "waiting": waiting}


def claim_job(kinds: tuple[str, ...] | None = None, worker_id: str = "worker", lease_seconds: float = LEASE_SECONDS,
              exclude_kinds: tuple[str, ...] | None = None, policies: tuple[str, ...] | None = None, lanes: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest claimable queued job: not waiting (not_before), not blocked, not cancelled.
    Claiming takes a lease (worker_id, run_id, lease_until); exactly one worker can win the UPDATE.
    L1 pools: `exclude_kinds` keeps general workers off the AI kinds; `policies` restricts a pool to jobs whose execution_policy is listed."""
    with tx() as conn:
        # Cancellation is terminal for queued work even when a lane is paused or excluded from this worker pool.
        # Without this sweep, a cancelled background job could remain forever in user-facing `cancelling` state while
        # the very pause that protects it also kept claim_job from reaching the old per-candidate cleanup below.
        pending_cancel = conn.execute(
            "SELECT id, payload, kind FROM jobs WHERE status='queued' AND cancel_requested_at IS NOT NULL"
        ).fetchall()
        for cancelled in pending_cancel:
            conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, message='cancelled', updated_at=? WHERE id=? AND status='queued'",
                         (now(), now(), cancelled["id"]))
            job_event(cancelled["id"], "cancelled", conn=conn, was="queued")
            _release_source_after_cancel(conn, cancelled)
        q = "SELECT id, blocked_by, dependency_policy, cancel_requested_at FROM jobs WHERE status='queued' AND (not_before IS NULL OR not_before<=?)"
        args: list[Any] = [now()]
        if kinds:
            q += f" AND kind IN ({','.join('?' for _ in kinds)})"
            args += list(kinds)
        if exclude_kinds:
            q += f" AND kind NOT IN ({','.join('?' for _ in exclude_kinds)})"
            args += list(exclude_kinds)
        if policies:
            q += f" AND execution_policy IN ({','.join('?' for _ in policies)})"
            args += list(policies)
        if lanes:
            q += f" AND lane IN ({','.join('?' for _ in lanes)})"
            args += list(lanes)
        if BACKGROUND_LANES and kv_get("background_paused") == "1":
            # Kyle: "I need it to get out of the way of 'real' work when I start adding new sources or do something
            # on my own ... manual pause and resume would be good." The existing queue pause stops EVERYTHING,
            # including the ingest he just started, which is why it was not the control he wanted. This pauses only
            # the speculative lanes; his own work keeps running.
            #
            # 0.51.0: it must also pause BACKGROUND_KINDS regardless of lane. Claim extraction runs a paid pass on
            # the `priority` lane (0.48.0's fast lane), so the control built to stop background spend was skipping
            # the largest background spender — 32% of a month's bill. A control that exempts the thing it exists to
            # stop is worse than no control, because the user believes they have stopped it.
            q += f" AND lane NOT IN ({','.join('?' for _ in BACKGROUND_LANES)})"
            args += list(BACKGROUND_LANES)
            if BACKGROUND_KINDS:
                q += f" AND kind NOT IN ({','.join('?' for _ in BACKGROUND_KINDS)})"
                args += list(BACKGROUND_KINDS)
        if account_gate_active():
            # The ACCOUNT is walled (no credit, or the Console's own usage limit). Nothing that must use the API can
            # succeed, so nothing that must use the API is claimed. Unlike the rate ceiling this holds `api_only`
            # too: there is no cheaper way for that work to run, and claiming it only produces another 0.4 s refusal.
            q += f" AND execution_policy NOT IN ({','.join('?' for _ in ACCOUNT_HELD_POLICIES)})"
            args += list(ACCOUNT_HELD_POLICIES)
        if float(kv_get("usage:rate_blocked_until") or 0) > now():
            # The spend-RATE ceiling (usage.SPEND_RATE_CEILING). Holds paid background only: jobs whose execution
            # policy forces the API, and claim extraction. Chat, ingestion, transcription and every local job are
            # untouched — a spending spike must never take away what the user is sitting in front of.
            q += f" AND execution_policy NOT IN ({','.join('?' for _ in RATE_HELD_POLICIES)})"
            args += list(RATE_HELD_POLICIES)
            if BACKGROUND_KINDS:
                q += f" AND kind NOT IN ({','.join('?' for _ in BACKGROUND_KINDS)})"
                args += list(BACKGROUND_KINDS)
        row = None
        # claim order: a manually bumped job ("run this next") outranks everything, FIFO among bumps; then lane
        # order — 'priority' (the user is waiting, e.g. ranking a review card), then 'normal'/'slow' (ordinary
        # work — transcribing a newly added source, findings, claims), then 'low' last — speculative work on
        # content not yet known to matter (e.g. backfilling metadata for skipped/stale sources) never displaces
        # something the user actually asked for, is watching, or explicitly bumped
        for cand in conn.execute(q + " ORDER BY (bumped_at IS NULL), bumped_at, CASE lane WHEN 'priority' THEN 0 WHEN 'low' THEN 2 ELSE 1 END, created_at LIMIT 50", args).fetchall():
            if cand["cancel_requested_at"]:
                conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, message='cancelled' WHERE id=? AND status='queued'", (now(), cand["id"]))
                job_event(cand["id"], "cancelled", conn=conn)
                continue
            st = _deps_state(conn, cand)
            if st == "ready":
                row = cand
                break
            if st.startswith("failed:"):
                rep = dependency_report({"blocked_by": cand["blocked_by"], "dependency_policy": cand["dependency_policy"]}, conn)
                who = ", ".join(str(x.get("label") or x["id"][:8]) for x in rep["failed"] + rep["cancelled"])[:200]
                conn.execute("UPDATE jobs SET status='failed', finished_at=?, message=? WHERE id=? AND status='queued'",
                             (now(), f"error: not run — {rep['done']}/{rep['total']} upstream jobs succeeded; failed or cancelled: {who}. Retry those, then this runs.", cand["id"]))
                job_event(cand["id"], "failed", conn=conn, reason="upstream", report=rep)
        if not row:
            return None
        run_id = new_id()
        t = now()
        cur = conn.execute(
            "UPDATE jobs SET status='running', started_at=?, run_id=?, worker_id=?, claimed_at=?, heartbeat_at=?, lease_until=?, not_before=NULL, wait_reason=NULL, bumped_at=NULL, "
                     # Kyle, live: an extract_claims job showed "paused: the account's credit balance is too low" while it was
                     # actually RUNNING and making successful calls. Claiming cleared not_before/wait_reason but left the
                     # message from when it was parked, so the panel kept showing a resolved error as if it were current.
                     "message=CASE WHEN message LIKE 'paused:%' THEN NULL ELSE message END "
            "WHERE id=? AND status='queued'", (t, run_id, worker_id, t, t, t + lease_seconds, row["id"])
        )
        if cur.rowcount != 1:
            return None
        job_event(row["id"], "claimed", run_id=run_id, conn=conn, worker_id=worker_id, lease_seconds=lease_seconds)
        return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())


def heartbeat(job_id: str, run_id: str | None = None, lease_seconds: float = LEASE_SECONDS) -> bool:
    """Extend the lease of a running job this worker owns. False when the job is no longer ours (lease lost)."""
    with tx() as conn:
        t = now()
        cur = conn.execute("UPDATE jobs SET heartbeat_at=?, lease_until=? WHERE id=? AND status='running'" + (" AND run_id=?" if run_id else ""),
                           (t, t + lease_seconds, job_id, *( [run_id] if run_id else [] )))
        return cur.rowcount == 1


def recover_expired_leases(all_running: bool = False) -> list[str]:
    """Jobs whose worker stopped heartbeating (or every running job, at process start — no worker of this process can
    own one yet) go back to queued with their partial durable state intact; the stage machinery resumes them.
    External-pending jobs hold no lease and are untouched: another system owns that work."""
    t = now()
    out: list[str] = []
    with tx() as conn:
        q = "SELECT id, run_id, worker_id, kind FROM jobs WHERE status='running'" + ("" if all_running else " AND (lease_until IS NULL OR lease_until < ?)")
        for r in conn.execute(q, () if all_running else (t,)).fetchall():
            job_event(r["id"], "lease_expired", run_id=r["run_id"], conn=conn, worker_id=r["worker_id"], at_startup=all_running)
            mark_ambiguous_invocations(r["id"], r["run_id"], conn=conn)
            conn.execute("UPDATE jobs SET status='queued', started_at=NULL, run_id=NULL, worker_id=NULL, lease_until=NULL, "
                         "message=?, updated_at=? WHERE id=?", ("recovered: worker lease expired — resuming from the last completed stage", t, r["id"]))
            job_event(r["id"], "recovered", conn=conn)
            out.append(r["id"])
    return out


def derived_status(j: dict[str, Any]) -> str:
    """The user-facing state: queued jobs can be blocked / retry_wait / budget_wait / rate_limit_wait; running jobs
    can be cancelling; external_pending is its own state. Stored status stays one of queued|running|external_pending|done|failed|cancelled."""
    st = j.get("status")
    if st == "queued":
        if j.get("cancel_requested_at"):
            return "cancelling"
        if j.get("blocked_by"):
            rep = dependency_report(j)
            if rep["state"] == "waiting":
                return "blocked"
        if j.get("wait_reason") == "paused":
            return "paused"                                    # S86: held by the person until they press Resume
        if j.get("not_before") and j["not_before"] > now():
            return {"budget": "budget_wait", "retry": "retry_wait", "rate_limit": "rate_limit_wait", "provider": "provider_wait",
                    "scheduled": "scheduled"}.get(j.get("wait_reason") or "", "retry_wait")   # L-40: a caller's schedule is not a retry
        return "queued"
    if st == "running" and j.get("cancel_requested_at"):
        return "cancelling"
    if st == "running" and j.get("pause_requested_at"):
        return "pausing"
    if st == "external_pending" and str(j.get("external_handle") or "").startswith("tentative:"):
        # recovery found provider work that MAY be ours; identity is proven only by the returned custom_id set
        cands = kv_get("batch:candidates:" + j["external_handle"][len("tentative:"):])
        n = len(json.loads(cands)) if cands else 0
        return "external_handle_ambiguous" if n > 1 else "external_tentative"
    return st or "unknown"


def park_external(job_id: str, run_id: str | None, provider: str, kind: str, handle: str, deadline: float | None = None) -> None:
    """The work now belongs to another system: release the worker lease, remember the handle durably."""
    with tx() as conn:
        t = now()
        conn.execute("UPDATE jobs SET status='external_pending', external_provider=?, external_kind=?, external_handle=?, external_submitted_at=?, "
                     "external_last_checked_at=?, external_deadline=?, run_id=NULL, worker_id=NULL, lease_until=NULL, message=?, updated_at=? WHERE id=?",
                     (provider, kind, handle, t, t, deadline, f"waiting for {provider} ({kind}) — handle {handle[:24]}", t, job_id))
        job_event(job_id, "external_submitted", run_id=run_id, conn=conn, provider=provider, kind=kind, handle=handle, deadline=deadline)


def note_external_intent(job_id: str, run_id: str | None, provider: str, kind: str) -> None:
    """Before submitting to an external system: record that we are about to, so a crash between the provider
    accepting and us persisting the handle can be recovered by asking the provider for our reference."""
    with tx() as conn:
        conn.execute("UPDATE jobs SET external_provider=?, external_kind=?, updated_at=? WHERE id=?", (provider, kind, now(), job_id))
        job_event(job_id, "external_submitting", run_id=run_id, conn=conn, provider=provider, kind=kind)


def external_pending_jobs() -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in connect().execute("SELECT * FROM jobs WHERE status='external_pending' ORDER BY external_last_checked_at").fetchall()]  # type: ignore[misc]


def external_checked(job_id: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE jobs SET external_last_checked_at=? WHERE id=?", (now(), job_id))


def unpark_external(job_id: str, reason: str) -> None:
    """Recovery concluded that no external work exists for this job (every tentative candidate was rejected): hand it
    back to the queue WITHOUT a result so the job submits afresh. Never used for a handle that was actually persisted."""
    with tx() as conn:
        conn.execute("UPDATE jobs SET status='queued', external_handle=NULL, external_submitted_at=NULL, external_deadline=NULL, message=?, updated_at=? "
                     "WHERE id=? AND status='external_pending'", (f"external recovery: {reason} — resubmitting", now(), job_id))
        job_event(job_id, "external_recovery_resubmit", conn=conn, reason=reason)


def resume_external(job_id: str, result: Any) -> None:
    """The external system finished: hand the job back to the queue with the result in its payload."""
    with tx() as conn:
        r = conn.execute("SELECT payload FROM jobs WHERE id=? AND status='external_pending'", (job_id,)).fetchone()
        if not r:
            return
        pl = json.loads(r["payload"] or "{}")
        pl["_external_result"] = result
        conn.execute("UPDATE jobs SET status='queued', payload=?, message='external work finished — completing', updated_at=? WHERE id=?",
                     (json.dumps(pl, default=str), now(), job_id))
        job_event(job_id, "external_result", conn=conn)


def request_cancel(job_id: str) -> str:
    """Cancellation semantics by state: queued → cancelled now; running → cancel_requested (the worker stops at its
    next safe boundary, writes nothing after); external_pending → cancelled locally (the result is discarded if it
    ever arrives). Returns the resulting stored status."""
    with tx() as conn:
        r = conn.execute("SELECT status, payload, kind FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return "missing"
        t = now()
        if r["status"] == "queued":
            conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, message='cancelled', updated_at=? WHERE id=?", (t, t, job_id))
            job_event(job_id, "cancelled", conn=conn, was="queued")
            _release_source_after_cancel(conn, r)
            return "cancelled"
        if r["status"] == "running":
            conn.execute("UPDATE jobs SET cancel_requested_at=?, message='cancelling… (stops at the next safe point)', updated_at=? WHERE id=?", (t, t, job_id))
            job_event(job_id, "cancel_requested", conn=conn)
            return "running"
        if r["status"] == "external_pending":
            conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, cancel_requested_at=?, message='cancelled locally — the external result will be discarded', updated_at=? WHERE id=?", (t, t, t, job_id))
            job_event(job_id, "cancelled", conn=conn, was="external_pending")
            # the batch may still run at the provider — this is the exact path that leaked all 432 rows
            n = _resolve_job_inflight(conn, job_id)
            if n:
                job_event(job_id, "ambiguous_external_execution", conn=conn, resolved=n)
            return "cancelled"
        return r["status"]


# S86 (Kyle, 2026-09-23: "theres no pause button on the sources progress window. only cancel. we need a pause/resume
# option"). A pause is a HOLD, not a wait: the job stays queued with wait_reason='paused' and a not_before far in the
# future, so no worker claims it and no scheduler wakes it — only resume_job does. A running job is asked to pause and
# stops at its next safe boundary (the same hook cancel uses), keeping everything it has written; Resume continues from
# there. The queue-wide Resume never touches a job the person paused individually.
PAUSE_HOLD_UNTIL = 4102444800.0            # 2100-01-01: "not until you say so"


def request_pause(job_id: str) -> str:
    """queued → held now; running → pause_requested (stops at the next safe boundary, then held). Returns the stored status."""
    with tx() as conn:
        r = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return "missing"
        t = now()
        if r["status"] == "queued":
            conn.execute("UPDATE jobs SET wait_reason='paused', not_before=?, pause_requested_at=NULL, message='paused by you — press ▶ to continue', updated_at=? WHERE id=?",
                         (PAUSE_HOLD_UNTIL, t, job_id))
            job_event(job_id, "paused", conn=conn, was="queued")
            return "queued"
        if r["status"] == "running":
            conn.execute("UPDATE jobs SET pause_requested_at=?, message='pausing… (stops at the next safe point)', updated_at=? WHERE id=?", (t, t, job_id))
            job_event(job_id, "pause_requested", conn=conn)
            return "running"
        return r["status"]


def hold_paused(job_id: str, run_id: str | None = None) -> None:
    """The worker reached its safe boundary after a pause request: back to the queue, held."""
    with tx() as conn:
        t = now()
        conn.execute("UPDATE jobs SET status='queued', started_at=NULL, run_id=NULL, worker_id=NULL, lease_until=NULL, pause_requested_at=NULL, "
                     "wait_reason='paused', not_before=?, message='paused by you — press ▶ to continue', updated_at=? WHERE id=?", (PAUSE_HOLD_UNTIL, t, job_id))
        job_event(job_id, "paused", run_id=run_id, conn=conn, was="running")


def resume_job(job_id: str) -> str:
    """Lift a person's pause. A job that is only pause-REQUESTED (still running) simply keeps running."""
    with tx() as conn:
        r = conn.execute("SELECT status, wait_reason, pause_requested_at FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return "missing"
        t = now()
        if r["status"] == "queued" and r["wait_reason"] == "paused":
            conn.execute("UPDATE jobs SET wait_reason=NULL, not_before=NULL, pause_requested_at=NULL, message=NULL, updated_at=? WHERE id=?", (t, job_id))
            job_event(job_id, "resumed", conn=conn)
            return "queued"
        if r["status"] == "running" and r["pause_requested_at"]:
            conn.execute("UPDATE jobs SET pause_requested_at=NULL, message=NULL, updated_at=? WHERE id=?", (t, job_id))
            job_event(job_id, "resumed", conn=conn, was="pausing")
            return "running"
        return r["status"]


def pause_requested(job_id: str) -> bool:
    r = connect().execute("SELECT pause_requested_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(r and r["pause_requested_at"])


def cancel_requested(job_id: str) -> bool:
    r = connect().execute("SELECT cancel_requested_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(r and r["cancel_requested_at"])


def run_scheduled_now(job_id: str) -> str:
    """L-40: "run now instead" for a job the user scheduled (wait_reason='scheduled'). Clears ONLY that kind of
    wait -- a budget/provider/retry park is not the user's schedule and stays -- then bumps it to the front, so it
    behaves exactly like a fresh "Now". Returns the resulting derived state, or the reason it did nothing."""
    with tx() as conn:
        r = conn.execute("SELECT status, wait_reason FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return "missing"
        if r["status"] != "queued":
            return r["status"]
        if r["wait_reason"] != "scheduled":
            return "not_scheduled"
        conn.execute("UPDATE jobs SET not_before=NULL, wait_reason=NULL, updated_at=? WHERE id=? AND status='queued'", (now(), job_id))
        job_event(job_id, "scheduled_run_now", conn=conn)
    return bump_job(job_id)


def bump_job(job_id: str) -> str:
    """0.45.12: a user's explicit "run this next" — a manual override on top of the lane system, for the one
    specific thing they want to jump the whole queue right now (never a standing rule, unlike lane). Only a
    QUEUED job can be bumped (running is already underway; a terminal job has nothing left to jump ahead of).
    Bumps stack FIFO by when they were requested, and a bump is cleared the moment the job is actually claimed —
    one-shot, never a permanent pin that would silently reorder the queue forever."""
    with tx() as conn:
        r = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return "missing"
        if r["status"] != "queued":
            return r["status"]
        t = now()
        conn.execute("UPDATE jobs SET bumped_at=?, updated_at=? WHERE id=? AND status='queued'", (t, t, job_id))
        job_event(job_id, "bumped", conn=conn)
        return "queued"


def rank_within_collections(project_id: str, source_id: str) -> tuple[int | None, int]:
    """Where this source sits in the relevance ranking of the collection(s) it came from, for THIS project.

    The ranking is the one `rank_proposed` already produced at review time (project_source_analysis, kind
    'relevance'), so it exists before a single video is downloaded — which is what makes "the top 3 of a channel"
    decidable the moment each one becomes ready, without waiting for the rest.

    Returns (best 1-based position, collection size). Position is None when the source is in no collection —
    i.e. it was added on its own, not as part of a channel or playlist."""
    conn = connect()
    cols = [r["collection_id"] for r in conn.execute("SELECT collection_id FROM source_collections WHERE source_id=?", (source_id,)).fetchall()]
    if not cols:
        return None, 0
    best, size = None, 0
    for cid in cols:
        rows = conn.execute(
            "SELECT s.id, COALESCE(a.relevance, -1) r FROM sources s JOIN source_collections sc ON sc.source_id=s.id "
            "LEFT JOIN project_source_analysis a ON a.source_id=s.id AND a.project_id=? AND a.analysis_kind='relevance' "
            "WHERE sc.collection_id=? ORDER BY r DESC, s.created_at", (project_id, cid)).fetchall()
        size = max(size, len(rows))
        for i, r in enumerate(rows, start=1):
            if r["id"] == source_id:
                best = i if best is None else min(best, i)
                break
    return best, size


def promote_first_findings(project_id: str, limit: int = 6) -> dict[str, Any]:
    """Bump the oldest queued findings jobs of ONE project to the front of the whole queue.

    The retroactive half of jobs.first_wave_lane: a project whose sources were queued before that existed is still
    stuck behind an unrelated backlog, and the user should not have to press "Start next" 75 times. Bumping is the
    existing one-shot mechanism (cleared the moment a job is claimed) — this only chooses which jobs get it, and
    changes nothing about cost, provider or model."""
    rows = connect().execute(
        "SELECT id FROM jobs WHERE kind='suggest_findings' AND status='queued' AND bumped_at IS NULL "
        "AND json_extract(payload,'$.project_id')=? ORDER BY created_at LIMIT ?", (project_id, max(0, int(limit)))).fetchall()
    for r in rows:
        try:
            bump_job(r["id"])
        except Exception:  # noqa: BLE001
            pass
    waiting = connect().execute(
        "SELECT COUNT(*) FROM jobs WHERE kind='suggest_findings' AND status IN ('queued','running') "
        "AND json_extract(payload,'$.project_id')=?", (project_id,)).fetchone()[0]
    return {"promoted": len(rows), "waiting": int(waiting)}


def check_now(job_id: str) -> str:
    """Kyle: a parked job's stored message (e.g. a SPEND_CAP "access returns <date>") is exactly what the provider
    said the moment it was hit — never invented — but it's frozen text: nothing re-attempts the call before that
    date arrives, so if the real-world limit already lifted (credits added, limit raised in the Console), the
    banner just sits there looking stale for however long is left. "Check now" clears the wait (not_before) and
    bumps the job to the front, so the very next worker cycle makes a fresh call and either succeeds (clearing the
    block for everything parked behind it) or reports the CURRENT date/reason, replacing the stale one. Only a
    queued job with an active wait can be checked — nothing to check on one that's already running or waiting on
    unmet dependencies rather than a timer."""
    with tx() as conn:
        r = conn.execute("SELECT status, not_before, blocked_by FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            return "missing"
        if r["status"] != "queued":
            return r["status"]
        if not r["not_before"]:
            return "queued"   # not actually waiting on a timer — nothing to check early
        t = now()
        conn.execute("UPDATE jobs SET not_before=NULL, wait_reason=NULL, bumped_at=?, updated_at=? WHERE id=? AND status='queued'", (t, t, job_id))
        job_event(job_id, "checked_now", conn=conn)
        return "queued"


def _release_source_after_cancel(conn: sqlite3.Connection, r: Any) -> None:
    try:
        pl = json.loads(r["payload"] or "{}")
    except ValueError:
        return
    sid = pl.get("source_id")
    if sid and r["kind"] == "ingest_source":
        conn.execute("UPDATE sources SET status='proposed', updated_at=? WHERE id=? AND status='pending'", (now(), sid))
        cid = pl.get("collection_id")
        if cid:
            conn.execute("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO NOTHING",
                         (f"review:{cid}", json.dumps({"min_date": pl.get("min_date"), "newest_first": pl.get("newest_first"),
                                                    "ranked": True, "rank_note": "returned from the queue — sorted by their earlier relevance scores"})))


def finish_job(job_id: str, run_id: str | None, status: str, *, message: str | None = None, result: dict | None = None) -> bool:
    """Terminal transition guarded by run_id: a worker whose lease was taken over cannot finish someone else's run."""
    assert status in JOB_TERMINAL
    with tx() as conn:
        t = now()
        cur = conn.execute("UPDATE jobs SET status=?, finished_at=?, message=COALESCE(?, message), result=COALESCE(?, result), progress=CASE WHEN ?='done' THEN 1.0 ELSE progress END, "
                           "run_id=NULL, worker_id=NULL, lease_until=NULL, updated_at=? WHERE id=? AND status='running'" + (" AND run_id=?" if run_id else ""),
                           (status, t, message[:2000] if message else None, json.dumps(result) if result is not None else None, status, t, job_id, *([run_id] if run_id else [])))
        ok = cur.rowcount == 1
        if ok:
            job_event(job_id, status, run_id=run_id, conn=conn, message=(message or "")[:300])
            n = _resolve_job_inflight(conn, job_id)      # the run is over: nothing may stay 'in_flight' behind it
            if n:
                job_event(job_id, "ambiguous_external_execution", run_id=run_id, conn=conn, resolved=n)
        return ok


def update_job(job_id: str, *, progress: float | None = None, message: str | None = None,
               status: str | None = None, result: dict | None = None) -> None:
    """0.61.0: a progress update NEVER touches a job that has already finished.

    Four of Kyle's failed jobs showed `[download] Finished downloading playlist: Mark J Kohler` as their error.
    The real reason was in `job_events` all along — "metadata fetch timed out after 4 min" — and had been written
    correctly. What overwrote it was yt-dlp: the metadata fetch timed out, the job failed, and the download it had
    started went on running and called the progress hook afterwards, over the top of the terminal message. A
    diagnosis that a later callback can erase is not a diagnosis."""
    sets, args = [], []
    if progress is not None:
        sets.append("progress=?"); args.append(progress)
    if message is not None:
        sets.append("message=?"); args.append(message[:2000])
    if status is not None:
        sets.append("status=?"); args.append(status)
        if status in JOB_TERMINAL:
            sets.append("finished_at=?"); args.append(now())
            sets.append("run_id=NULL, worker_id=NULL, lease_until=NULL")
    else:
        sets.append("heartbeat_at=?"); args.append(now())          # any progress report is a heartbeat
        sets.append("lease_until=?"); args.append(now() + LEASE_SECONDS)
    if result is not None:
        sets.append("result=?"); args.append(json.dumps(result))
    if not sets:
        return
    sets.append("updated_at=?"); args.append(now())
    where = "id=?"
    args_tail: list[Any] = [job_id]
    if status is None:
        # not a deliberate status change: this is progress, and progress on a finished job is late news
        where += f" AND status NOT IN ({','.join('?' for _ in JOB_TERMINAL)})"
        args_tail += list(JOB_TERMINAL)
    with tx() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE {where}", (*args, *args_tail))


def skip_queued_siblings(collection_id: str, reason: str) -> int:
    """Cancel still-queued ingest_source jobs for a collection and mark their sources skipped."""
    n = 0
    with tx() as conn:
        rows = conn.execute("SELECT id, payload FROM jobs WHERE status='queued' AND kind='ingest_source'").fetchall()
        for r in rows:
            try:
                pl = json.loads(r["payload"])
            except ValueError:
                continue
            if pl.get("collection_id") != collection_id:
                continue
            conn.execute("UPDATE jobs SET status='done', finished_at=?, message=?, result=? WHERE id=?",
                         (now(), "skipped: " + reason, json.dumps({"skipped": True, "reason": reason}), r["id"]))
            conn.execute("UPDATE sources SET status='skipped', error=?, updated_at=? WHERE id=? AND status='pending'",
                         (reason, now(), pl.get("source_id")))
            n += 1
    return n


def proposed_sources(collection_id: str, project_id: str | None = None) -> list[dict[str, Any]]:
    """Proposed (unapproved) sources of a listing. Relevance is project-relative, so it comes from
    project_source_analysis for the given project (None → unranked order)."""
    if project_id is None:
        project_id = collection_project(collection_id)
    out = []
    for r in connect().execute(
            """SELECT s.*, a.relevance AS a_relevance, a.relevance_why AS a_relevance_why, a.updated_at AS a_relevance_at
               FROM sources s JOIN source_collections sc ON sc.source_id=s.id
               LEFT JOIN project_source_analysis a ON a.source_id=s.id AND a.project_id=? AND a.analysis_kind='relevance'
               WHERE sc.collection_id=? AND s.status='proposed'
               ORDER BY (s.access_gate IS NOT NULL), (a.relevance IS NULL), a.relevance DESC, s.created_at""", (project_id, collection_id)).fetchall():
        d = row_to_dict(r)
        d["relevance"], d["relevance_why"] = d.pop("a_relevance"), d.pop("a_relevance_why")     # the legacy global columns are ignored
        d["relevance_at"] = d.pop("a_relevance_at")
        out.append(d)
    return out


def collection_project(collection_id: str) -> str | None:
    row = connect().execute("SELECT project_id FROM project_collections WHERE collection_id=? ORDER BY rowid LIMIT 1", (collection_id,)).fetchone()
    return row["project_id"] if row else None


def set_relevance(source_id: str, score: int | None, why: str | None, project_id: str | None = None, **prov: Any) -> None:
    """Relevance of a source TO A PROJECT (there is no such thing as relevance in general)."""
    if project_id is None:
        return
    upsert_analysis(project_id, source_id, "relevance", relevance=score, relevance_why=why, **prov)


ANALYSIS_KINDS = ("relevance", "summary")


def analysis_writable(project_id: str, source_id: str) -> bool:
    """Do both parents still exist? (0.63.0)

    Kyle: *"we seem to be getting 'error: FOREIGN KEY constraint failed' a lot today."* Measured in his job history:
    every occurrence is a `rank_proposed` job — 9 of them, the newest at 23:01. That job reads a collection's
    proposed sources, spends minutes ranking them (p50 384 s), then writes a relevance artifact per source. If a
    source is deleted or replaced in between — which is precisely what approving a review, discarding one or
    retiring a direction does — the write lands on a dangling foreign key. And because the writes share one
    `db.batch()`, **one vanished source voided the entire ranking**, so minutes of paid work were thrown away with
    an error message that named nothing.

    A source that no longer exists has not failed; it has left. The artifact has nowhere to live and the honest
    thing is to skip it and say how many were skipped, which is what `relevance.rank_collection` now reports."""
    c = connect()
    if not c.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
        return False
    return bool(c.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone())


def upsert_analysis(project_id: str, source_id: str, analysis_kind: str, **fields: Any) -> None:
    """Write one project-relative analysis artifact (one per AI task) with ITS provenance. A fresh write is current."""
    assert analysis_kind in ANALYSIS_KINDS, analysis_kind
    if not analysis_writable(project_id, source_id):
        logging.getLogger(__name__).info("analysis skipped: %s/%s no longer exists",
                                         (project_id or "?")[:8], (source_id or "?")[:8])
        return
    allowed = {"summary", "substance", "relevance", "relevance_why", "model", "provider", "prompt_version", "schema_version",
               "input_hash", "source_revision", "brief_revision", "facts_revision", "status", "transport", "batch_id", "prefilter", "routing", "depth", "r6_wave", "r6_provisional"}
    f = {k: v for k, v in fields.items() if k in allowed}
    f.setdefault("status", "current")
    t = now()
    with tx() as conn:
        conn.execute("INSERT OR IGNORE INTO project_source_analysis (project_id, source_id, analysis_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (project_id, source_id, analysis_kind, t, t))
        sets = ", ".join(f"{k}=?" for k in f) + ", updated_at=?"
        conn.execute(f"UPDATE project_source_analysis SET {sets} WHERE project_id=? AND source_id=? AND analysis_kind=?", (*f.values(), t, project_id, source_id, analysis_kind))


def project_analysis(project_id: str, kind: str = "summary") -> dict[str, dict[str, Any]]:
    """source_id → analysis row of one kind for a project."""
    return {r["source_id"]: dict(r) for r in connect().execute(
        "SELECT * FROM project_source_analysis WHERE project_id=? AND analysis_kind=?", (project_id, kind)).fetchall()}


def project_analyses(project_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    """source_id → {kind → row}; what the source card combines."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in connect().execute("SELECT * FROM project_source_analysis WHERE project_id=?", (project_id,)).fetchall():
        out.setdefault(r["source_id"], {})[r["analysis_kind"]] = dict(r)
    return out


def get_analysis(project_id: str, source_id: str, kind: str = "summary") -> dict[str, Any] | None:
    row = connect().execute("SELECT * FROM project_source_analysis WHERE project_id=? AND source_id=? AND analysis_kind=?", (project_id, source_id, kind)).fetchone()
    return dict(row) if row else None


def review_meta(collection_id: str) -> dict[str, Any]:
    try:
        return json.loads(kv_get(f"review:{collection_id}") or "{}")
    except ValueError:
        return {}


def mark_review_ranked(collection_id: str, note: str | None = None) -> None:
    meta = review_meta(collection_id)
    meta["ranked"] = True
    if note:
        meta["rank_note"] = note
    kv_set(f"review:{collection_id}", json.dumps(meta))


def pending_reviews(project_id: str) -> list[dict[str, Any]]:
    """Collections linked to this project that still have proposed (unapproved) sources."""
    out = []
    for c in connect().execute(
        """SELECT c.* FROM collections c JOIN project_collections pc ON pc.collection_id=c.id WHERE pc.project_id=?""",
        (project_id,)).fetchall():
        # S89 (Kyle, 2026-09-23, screenshot): a channel he had added to an earlier project showed "Newest first" with
        # 380 of 380 ticked, though rank_proposed had scored all 380 for THIS project. proposed_sources() with no
        # project fell back to collection_project() — the FIRST project ever linked to the channel — so the card read
        # its relevance from the wrong project and found none. Relevance is project-relative; ask for this one.
        props = proposed_sources(c["id"], project_id)
        if props:
            from . import usage
            rate = usage.observed_rate_per_minute()
            for s in props:
                s["est"] = usage.estimate_video(s.get("duration"), rate)
            d = dict(c); d["proposed"] = props; d["meta"] = review_meta(c["id"])
            d["meta"]["rate_basis"] = "your usage so far" if rate is not None else "list prices"
            out.append(d)
    return out


def validation_event(kind: str, detail: dict[str, Any], *, project_id: str | None = None, source_id: str | None = None,
                     model: str | None = None, prompt_version: str | None = None) -> None:
    """Diagnostic record of a validator decision. Rejected findings are never shown to the user, but they are never
    lost either — "this video produced only two findings" can be answered."""
    from .logctx import get as _ctx
    ctx = _ctx()
    with tx() as conn:
        conn.execute("INSERT INTO validation_events (ts, kind, project_id, source_id, job_id, model, prompt_version, detail) VALUES (?,?,?,?,?,?,?,?)",
                     (time.time(), kind, project_id or ctx.get("project_id"), source_id or ctx.get("source_id"), ctx.get("job_id"),
                      model or ctx.get("model"), prompt_version, json.dumps(detail, default=str)[:4000]))


def validation_events(kind: str | None = None, source_id: str | None = None, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    q, args = "SELECT * FROM validation_events WHERE 1=1", []
    if kind:
        q += " AND kind=?"; args.append(kind)
    if source_id:
        q += " AND source_id=?"; args.append(source_id)
    if project_id:
        q += " AND project_id=?"; args.append(project_id)
    rows = connect().execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        try:
            d["detail"] = json.loads(d["detail"] or "{}")
        except ValueError:
            pass
        out.append(d)
    return out


def kv_bump(key: str, n: int = 1) -> None:
    """Atomic integer counter in kv (evidence/validator stats)."""
    if not n:
        return
    with tx() as conn:
        conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT)",
                     (key, str(n), n))


def kv_get(key: str) -> str | None:
    row = connect().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


PRE_FIX_MISMATCH_KEY = "model_mismatch:pre_0_63_29"


def snapshot_pre_fix_mismatches() -> None:
    """Record, ONCE, how many `model_mismatch` rows existed before 0.63.29's accounting fix.

    Those counts are not trustworthy: the answering model was chosen by `inputTokens + outputTokens` with cached
    tokens ignored, so the CLI's own scaffolding model (a few hundred uncached tokens) beat the model that did the
    work (over a hundred thousand CACHED tokens) — 363 times on Kyle's machine, and in both directions, which is
    the tell. See `claude_code._answering_model`.

    **The history is not rewritten** — the same rule 0.62.3 set for mis-dated spend: the number stays and sits
    beside an explanation, so a warning that read as 363 substitutions can be recognised as 363 mis-readings
    rather than quietly deleted. New rows counted after this snapshot are real, and Health shows the two apart."""
    try:
        if kv_get(PRE_FIX_MISMATCH_KEY) is not None:
            return
        rows = {r["task_key"]: r["count"] for r in _raw_model_mismatches()}
        kv_set(PRE_FIX_MISMATCH_KEY, json.dumps(rows))
    except sqlite3.OperationalError:
        return                             # no kv table yet: nothing to baseline, and nothing to lose


def _raw_model_mismatches() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        rows = connect().execute("SELECT key, value FROM kv WHERE key LIKE 'model_mismatch:%' "
                                 "AND key NOT IN ('model_mismatch:last', ?)", (PRE_FIX_MISMATCH_KEY,)).fetchall()
    except sqlite3.OperationalError:
        return out
    for row in rows:
        body = row["key"].split(":", 1)[1]
        task, pair, by = (body.rsplit(":", 2) + ["", ""])[:3] if body.count(":") >= 2 else (body, "", "")
        req, _, act = pair.partition(">")
        out.append({"task_key": body, "task": task, "requested": req, "actual": act,
                    "executed_by": by, "count": int(row["value"] or 0)})
    return out


def bump_model_mismatch(task: str, requested: str, actual: str, executed_by: str) -> None:
    """A provider returned a model the app did not ask for. Counted per task+pair in kv (no schema change) so Health
    and `doctor` can say it out loud — 0.56.3. Silent substitution is the failure this layer exists to prevent, and
    the local Claude Code path can do it whatever the contract says."""
    key = f"model_mismatch:{task}:{requested}>{actual}:{executed_by}"
    try:
        n = int(kv_get(key) or 0)
    except (TypeError, ValueError):
        n = 0
    kv_set(key, str(n + 1))
    kv_set("model_mismatch:last", json.dumps({"task": task, "requested": requested, "actual": actual,
                                              "executed_by": executed_by, "at": time.time()}))


def model_mismatches() -> list[dict[str, Any]]:
    """Every recorded substitution, newest count first — what Health renders and `doctor` fails on."""
    raw = _raw_model_mismatches()          # safe on a missing kv table: `doctor` runs before init_db
    if not raw:
        return []
    try:
        pre = json.loads(kv_get(PRE_FIX_MISMATCH_KEY) or "{}")
    except (ValueError, sqlite3.OperationalError):
        pre = {}
    out = []
    for r in raw:
        before = int(pre.get(r["task_key"]) or 0)
        r = {**r, "before_fix": min(before, r["count"]), "since_fix": max(0, r["count"] - before)}
        r.pop("task_key", None)
        out.append(r)
    return sorted(out, key=lambda r: (-r["since_fix"], -r["count"]))


def kv_set(key: str, value: str | None) -> None:
    with tx() as conn:
        if value is None:
            conn.execute("DELETE FROM kv WHERE key=?", (key,))
        else:
            conn.execute("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def kv_compare_set(key: str, expected: str | None, value: str | None) -> bool:
    """Set a KV value only when its serialized prior value still matches.

    Catalog page workers use this optimistic generation guard inside their short write batch.  A stale worker
    therefore rolls back its candidate/membership writes rather than moving a newer scan cursor backwards.
    """
    with tx() as conn:
        row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        actual = row["value"] if row else None
        if actual != expected:
            return False
        if value is None:
            conn.execute("DELETE FROM kv WHERE key=?", (key,))
        else:
            conn.execute("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    return True


def cancel_queued_jobs(kinds: tuple[str, ...] | None = None, project_id: str | None = None,
                       job_ids: list[str] | None = None) -> int:
    """Cancel every queued job (optionally only some kinds / one project / specific ids). Pending sources go back
    to 'proposed' so they can be approved later from the Review card instead of silently disappearing."""
    n = 0
    with tx() as conn:
        rows = conn.execute("SELECT id, kind, payload FROM jobs WHERE status='queued'").fetchall()
        for r in rows:
            if kinds and r["kind"] not in kinds:
                continue
            if job_ids is not None and r["id"] not in job_ids:
                continue
            try:
                pl = json.loads(r["payload"])
            except ValueError:
                pl = {}
            if project_id and pl.get("project_id") not in (None, project_id):
                continue
            conn.execute("UPDATE jobs SET status='cancelled', finished_at=?, message='cancelled', updated_at=? WHERE id=?", (now(), now(), r["id"]))
            job_event(r["id"], "cancelled", conn=conn, was="queued")
            _release_source_after_cancel(conn, r)
            if r["kind"] == "ingest_url" and pl.get("url"):
                # a single link that never started: mark its placeholder source so it is visible and retryable
                conn.execute("UPDATE sources SET status='failed', error='cancelled before it started — use Retry', updated_at=? WHERE url=? AND status='pending'",
                             (now(), pl["url"]))
            n += 1
    return n


def live_job_by_source() -> dict[str, dict[str, Any]]:
    """source_id -> the queued/running ingest job working on it (with its queue position), for the Sources list."""
    out: dict[str, dict[str, Any]] = {}
    pos = 0
    for r in connect().execute("SELECT id, kind, status, message, payload, updated_at, started_at, not_before FROM jobs "
                               "WHERE status IN ('queued','running') AND kind IN ('ingest_source','ingest_url','ingest_file') ORDER BY created_at").fetchall():
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        if r["status"] == "queued":
            pos += 1
        sid = pl.get("source_id")
        if sid and sid not in out:
            out[sid] = {"id": r["id"], "status": r["status"], "message": r["message"], "position": pos if r["status"] == "queued" else 0,
                        "updated_at": r["updated_at"] or r["started_at"], "waiting_until": r["not_before"]}
    return out


REQUIRED_TABLES = ("sources", "segments", "chunks", "projects", "project_sources", "project_notes", "project_facts",
                   "plans", "conversations", "messages", "jobs", "usage", "kv", "work_units")


def verify_database(path: Path) -> dict[str, Any]:
    """Open a database file read-only and prove it is a usable Neuro Search database.

    A backup only counts as verified after the full integrity walk succeeds.  Unlike
    ``quick_check``, SQLite's full ``integrity_check`` invokes FTS5's virtual-table
    integrity hook, which is the check that can detect the corruption seen in the
    2026-09-12 sleep/wake incident.  The path is a standalone backup, so this read
    does not touch the live database's WAL or ``-shm`` files.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check: {integrity}")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in REQUIRED_TABLES if t not in have]
        if missing:
            raise RuntimeError(f"missing tables: {', '.join(missing)}")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("sources", "segments", "chunks", "projects", "project_notes", "conversations", "messages", "plans")}
        return {"ok": True, "integrity": integrity, "counts": counts, "bytes": path.stat().st_size}
    finally:
        conn.close()


def backup(keep: int = 48) -> Path:
    """Consistent online snapshot of the database (SQLite backup API — safe while the app is running), then
    VERIFIED: the copy is reopened and checked (see verify_database) before it counts. A copy that fails is deleted
    and the failure raised, so "last verified backup" in the health view is never a lie.
    Files land in <data>/backups/neurosearch-YYYYmmdd-HHMM.db; the newest `keep` are retained."""
    import datetime as _dt
    d = settings.data_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"neurosearch-{_dt.datetime.now():%Y%m%d-%H%M}.db"
    src = connect()
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
    finally:
        out.close()
    try:
        info = verify_database(dest)
    except Exception as e:
        dest.unlink(missing_ok=True)
        kv_set("backup:last_error", json.dumps({"ts": time.time(), "error": str(e)[:300]}))
        raise RuntimeError(f"backup verification failed: {e}") from e
    kv_set("backup:last_verified", json.dumps({"ts": time.time(), "path": str(dest), **info}))
    olds = sorted(d.glob("neurosearch-*.db"))
    for f in olds[:-keep]:
        f.unlink(missing_ok=True)
    return dest


def integrity_check() -> dict[str, Any]:
    """quick_check + foreign_key_check on the live database, plus the application-level consistency checks SQLite
    cannot express as a declared FK. 2026-09-14: two real bugs (a duplicate-citation guard gap in
    claims.add_evidence, and replace_suggestions deleting a note a Claim had already adopted as origin_note_id)
    sat undetected for an unknown period because quick_check/foreign_key_check are structurally incapable of
    seeing either - the duplicate rows were perfectly valid FTS/b-tree data, and origin_note_id/note_id were never
    declared REFERENCES (deliberately: a Claim must survive its origin note's deletion, so ON DELETE CASCADE is
    wrong there - the right invariant is 'never create a new dangling one', which these two counts watch for).
    Both bugs are now fixed at the source; these counts are the regression detector - either going above the
    known, already-cleaned baseline again means the same class of bug came back."""
    t = time.time()
    res = connect().execute("PRAGMA quick_check").fetchone()[0]
    fk = connect().execute("PRAGMA foreign_key_check").fetchall()
    dup_evidence = connect().execute("""
        SELECT COUNT(*) FROM (
          SELECT 1 FROM claim_evidence GROUP BY claim_id, source_id, source_revision, locator, relation HAVING COUNT(*) > 1
        )""").fetchone()[0]
    dangling_origin = connect().execute(
        "SELECT COUNT(*) FROM project_claims c WHERE c.origin_note_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM project_notes n WHERE n.id=c.origin_note_id)").fetchone()[0]
    info = {"ts": t, "ok": res == "ok" and not fk and dup_evidence == 0 and dangling_origin == 0, "result": res,
            "foreign_key_violations": len(fk), "duplicate_claim_evidence": dup_evidence,
            "dangling_origin_note_id": dangling_origin, "seconds": round(time.time() - t, 2)}
    kv_set("db:last_integrity", json.dumps(info))
    return info


def preflight_autonomous(envelope_id: str) -> dict[str, Any]:
    """L-10 (EXECUTION-LADDER.md P0.G, CTO rulings §1.G): once per autonomous execution envelope, before any job
    in it may run -- full ``PRAGMA integrity_check`` on the LIVE database (not ``quick_check``: see
    ``verify_database``'s own reasoning, this is the check that actually caught 2026-09-14's real corruption,
    quick_check would not have), then a freshly taken and verified backup. Raises, never proceeds silently, if
    the live database is not clean -- refusing to start autonomous work against a database already known broken
    is the entire point.

    Idempotent per envelope: a second call with the same ``envelope_id`` (multiple jobs sharing one envelope)
    returns the ORIGINAL recorded preflight instead of re-running the check and taking a second backup -- but
    only once it has actually SUCCEEDED. A failed attempt is never cached as final (that would permanently lock
    an envelope out even after the database is repaired); it is recorded for `doctor` under
    ``db:last_preflight_failure`` and raised every time until a preflight for that envelope actually passes."""
    key = f"preflight:{envelope_id}"
    existing = kv_get(key)
    if existing:
        return json.loads(existing)
    t = time.time()
    live = connect().execute("PRAGMA integrity_check").fetchone()[0]
    if live != "ok":
        failure = {"envelope_id": envelope_id, "ts": t, "ok": False, "live_integrity": live}
        kv_set("db:last_preflight_failure", json.dumps(failure))
        raise RuntimeError(f"preflight refused for envelope {envelope_id!r}: live database integrity_check "
                           f"reported {live!r}, not 'ok' -- refusing to start autonomous work against it")
    backup_path = backup()   # raises RuntimeError itself if the fresh copy doesn't independently verify
    info = {"envelope_id": envelope_id, "ts": t, "ok": True, "live_integrity": live, "backup_path": str(backup_path)}
    kv_set(key, json.dumps(info))
    kv_set("db:last_preflight", json.dumps(info))
    return info


def rebuild_fts5() -> dict[str, Any]:
    """Rebuild the external-content FTS5 index under the app's writer connection.

    This is an explicit recovery operation for a reported FTS5 inconsistency.  The
    immediate transaction serializes it with other writers; no caller outside the
    app should ever open the live database to run the special ``rebuild`` command.
    A full integrity check is run after the rebuild and the result is retained in
    ``kv`` for the health/history surfaces.
    """
    started = time.time()
    conn = connect()
    before = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    info = {
        "ts": time.time(),
        "ok": result == "ok",
        "before": before,
        "result": result,
        "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "seconds": round(time.time() - started, 2),
    }
    kv_set("db:last_fts_rebuild", json.dumps(info))
    return info


def _flags_health() -> dict[str, Any]:
    """Every experimental / rollback flag with its current value and whether it sits at the release's safe default."""
    try:
        from . import release
        return release.flags_state()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:100]}


def _last_release_check() -> dict[str, Any] | None:
    """The most recent `neurosearch release-check` artifact (what passed, against which commit)."""
    try:
        d = Path(__file__).resolve().parent.parent / "evals" / "release"
        files = sorted(d.glob("release-check-*.json"))
        if not files:
            return None
        rep = json.loads(files[-1].read_text())
        return {"verdict": rep.get("verdict"), "app_version": rep.get("app_version"), "git_sha": rep.get("git_sha"), "timestamp": rep.get("timestamp"),
                "checks": len(rep.get("checks") or []), "artifact": files[-1].name}
    except Exception:  # noqa: BLE001
        return None


def _provider_health() -> list[dict[str, Any]]:
    try:
        from . import breakers
        return breakers.health()
    except Exception as e:  # noqa: BLE001
        return [{"operation": "?", "label": "Provider health", "status": "unknown", "detail": str(e)[:100]}]


def _spend_health() -> dict[str, Any]:
    """0.59.0: the reconciliation, in Health, because the gap between recorded and actual spend is exactly the kind
    of thing that has to be visible on the page a user opens when they wonder where the money went."""
    try:
        from . import usage
        r = usage.reconcile(days=7)
        return {"billing_mode": r["billing_mode"], "local_is_free": r["local_is_free"], "note": r["note"],
                "today": r["today"], "week": r["week"], "month": r["month"], "budgets": r["budgets"],
                "how_to_read": r["how_to_read"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _cost_value_health() -> dict[str, Any]:
    """0.59.3: one line of cost-per-unit-of-value, because "is it getting cheaper per useful thing?" is a different
    question from "how much have we spent" and the spend section could only answer the second."""
    try:
        from . import cost_value
        return cost_value.headline()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def backfill_failure_classes() -> int:
    """Classify failures recorded before 0.61.0. Idempotent, touches only unclassified failed rows, and never
    changes a status — the rows were already failed and stay failed; they just become distinguishable."""
    n = 0
    rows = connect().execute("SELECT id, error FROM sources WHERE status='failed' AND (error_class IS NULL OR error_class='')").fetchall()
    for r in rows:
        cls = failure_class(r["error"])
        if cls:
            with tx() as conn:
                conn.execute("UPDATE sources SET error_class=? WHERE id=?", (cls, r["id"]))
            n += 1
    if n:
        logging.getLogger(__name__).info("classified %d previously unclassified source failures", n)
    return n


def _storage_health() -> dict[str, Any]:
    """0.61.2: the database and its write-ahead log, in megabytes, because a 112 MB log that never checkpointed
    was the reason every read had become slow and nothing in the app said so."""
    try:
        from . import cache
        wal = wal_bytes()
        return {"db_mb": round(os.path.getsize(str(settings.db_path)) / 1e6, 1) if os.path.exists(str(settings.db_path)) else 0,
                "wal_mb": round(wal / 1e6, 1), "wal_threshold_mb": round(WAL_CHECKPOINT_AT / 1e6, 1),
                "wal_over_threshold": wal > WAL_CHECKPOINT_AT,
                "cache_entries": cache.size(), "cache_refreshing": cache.refreshing(),
                "note": ("The log is checkpointed every couple of minutes. It only grows past the threshold when a "
                         "long-running read keeps an older snapshot alive, which is worth knowing about."
                         if wal > WAL_CHECKPOINT_AT else "the write-ahead log is being checkpointed normally")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _failures_health() -> dict[str, Any]:
    try:
        return failure_summary()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _batches_health() -> dict[str, Any]:
    """0.60.3: provider batches nobody collected. On Kyle's data one cancelled job had left 426 items at
    `submitted` for two days — requests Anthropic may have billed and findings that were never written. Derived, so
    it clears itself the moment a batch is settled."""
    try:
        from . import batches
        rows = batches.unsettled()
        awaiting = sum(r.get("awaiting_collection", 0) for r in rows)
        unwritten = sum(r.get("collected_not_written", 0) for r in rows)
        return {"unsettled": len(rows), "items": sum(r["items"] for r in rows), "rows": rows[:8],
                "awaiting_collection": awaiting, "collected_not_written": unwritten,
                "note": (("Two different states. " if awaiting and unwritten else "") +
                         (f"{awaiting} request(s) nobody has collected yet — settling is free. " if awaiting else "") +
                         (f"{unwritten} result(s) were collected and never written, because the other windows of "
                          "their source were cancelled at the provider: half a source is not a reading of it, so "
                          "re-read those sources if you want them. " if unwritten else "")
                         if rows else "every provider batch has been collected and written")}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _findings_quality_health() -> dict[str, Any]:
    """F1-F5 counts per project, from the CACHE only (0.61.2).

    The pass takes 11.5 s on a 12,800-finding project, so Health — a page someone opens when the app already feels
    slow — must never trigger it. A project whose check has not run yet is listed as `pending` rather than
    computed on the spot or quietly omitted: the housekeeping loop warms it within a couple of minutes."""
    try:
        from . import findings_quality
        out = []
        for row in connect().execute("SELECT id, name FROM projects ORDER BY created_at").fetchall():
            try:
                s = findings_quality.summary(row["id"])
            except Exception:  # noqa: BLE001 — one bad project must not blank the whole section
                continue
            notes = connect().execute("SELECT COUNT(*) n FROM project_notes WHERE project_id=?", (row["id"],)).fetchone()["n"]
            if s.get("pending") and notes:
                out.append({"project": row["name"], "pending": True, "findings": int(notes),
                            "note": "the duplicate check has not run yet — it is computed in the background"})
            elif s.get("findings"):
                out.append({"project": row["name"], **s})
        return {"projects": out,
                "thresholds": {"near_jaccard": findings_quality.NEAR_JACCARD,
                               "set_jaccard": findings_quality.SET_JACCARD,
                               "contain_ratio": findings_quality.CONTAIN_RATIO},
                "note": "Duplicates are a FLOOR, not a ceiling: the check catches rewordings, not paraphrases. "
                        "Watch the duplicate share as the raised findings cap takes effect."}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _findings_cap_health() -> dict[str, Any]:
    """F4: how many findings a source is allowed to keep, and whether that is the shipped default. A cap change is
    the one thing in 0.58.1 with a live behavioural effect, so it is visible rather than buried in a constant."""
    try:
        from . import findings
        now = {"base": findings.CAP_BASE, "per_window": findings.CAP_PER_WINDOW, "max": findings.CAP_MAX}
        before = findings.CAP_DEFAULTS_BEFORE
        return {"current": now, "before_0_58_1": before, "raised": now != before,
                "example_caps": {f"{w} window(s)": findings.cap_for(w) for w in (1, 3, 10, 20)},
                "revert": "NEUROSEARCH_FINDINGS_CAP_BASE=12 NEUROSEARCH_FINDINGS_CAP_PER_WINDOW=8 "
                          "NEUROSEARCH_FINDINGS_CAP_MAX=120 restores the previous behaviour with no code change",
                "note": "overflow is kept as `reserve` (never exported, planned on or harvested) and can be promoted "
                        "per note; raising the cap only ever adds notes and never moves one already stored"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _scholar_health() -> dict[str, Any]:
    """Research catalogues: config only, never a probe. A section that made a network call every time Health opened
    would spend someone else's free service to answer a question config already answers."""
    try:
        from . import scholar
        return {"providers": scholar.available(), "ready": scholar.ready_providers(),
                "note": "Crossref and OpenAlex are $0 metadata sources; a record is a candidate, never evidence, "
                        "and only an open-access PDF becomes a source"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def health() -> dict[str, Any]:
    """What the health view needs: database, backups, queue, evidence validators, disk."""
    import shutil as _sh

    def _j(key: str) -> Any:
        v = kv_get(key)
        try:
            return json.loads(v) if v else None
        except ValueError:
            return None

    conn = connect()
    q = conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    jobs_by = {r["status"]: r["n"] for r in q}
    stale = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running' AND (lease_until IS NULL OR lease_until < ?)", (time.time(),)).fetchone()[0]
    leased = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='running' AND lease_until >= ?", (time.time(),)).fetchone()[0]
    ev = {k: int(kv_get(f"evidence:{k}") or 0) for k in ("findings_checked", "findings_rejected", "citations_checked", "citations_invalid", "plan_refs_checked", "plan_refs_dangling",
                                                          "schema_mismatches", "schema_mismatch_recovered", "schema_fallbacks", "schema_failures", "output_truncated", "output_refused",
                                                          "retrieval_degraded", "prefilter_keep", "prefilter_uncertain", "prefilter_drop", "prefilter_fail_open", "prefilter_aggressive",
                                                          "rerank_applied", "rerank_fallback", "fetch_blocked",
                                                          # 0.63.23 — the measurement that would have caught 0.63.22.
                                                          # A finding kept without a citation is a finding nothing can
                                                          # verify and `harvest` turns into a Claim resting on nothing,
                                                          # and 51.5% of his spreadsheet findings were in that state with
                                                          # no number anywhere reporting it.
                                                          "findings_uncitable", "findings_citable", "locator_from_quote", "quote_relocated")}
    ev["events"] = {r["kind"]: r["n"] for r in conn.execute("SELECT kind, COUNT(*) n FROM validation_events GROUP BY kind").fetchall()}
    try:
        du = _sh.disk_usage(str(settings.data_dir))
        disk = {"free_gb": round(du.free / 1e9, 1), "db_mb": round(settings.db_path.stat().st_size / 1e6, 1)}
    except OSError:
        disk = {}
    inv = invocation_counts()
    return {"db": {"integrity": _j("db:last_integrity"), "fts5_rebuild": _j("db:last_fts_rebuild"), "path": str(settings.db_path)},
            "invocations": {**inv, "ambiguous": inv.get("outcome_unknown", 0)},
            "backup": {"last_verified": _j("backup:last_verified"), "last_error": _j("backup:last_error")},
            "jobs": {**jobs_by, "stale_running": stale, "expired_leases": stale, "leased": leased,
                     "external_pending": jobs_by.get("external_pending", 0)},
            "structured_outputs": {"mismatches": ev["schema_mismatches"], "mismatches_recovered_by_retry": ev["schema_mismatch_recovered"],
                                   "fallbacks": ev["schema_fallbacks"], "unrecovered": ev["schema_failures"], "truncated": ev["output_truncated"],
                                   "refused": ev["output_refused"], "steady_state": "all zero"},
            "providers": _provider_health(),
            "scholar": _scholar_health(),
            "findings_cap": _findings_cap_health(),
            "findings_quality": _findings_quality_health(),
            "spend": _spend_health(),
            "cost_value": _cost_value_health(),
            "batches": _batches_health(),
            "failures": _failures_health(),
            "storage": _storage_health(),
            "model_routing": {"mismatches": model_mismatches(), "last": _j("model_mismatch:last"),
                              "note": "0.56.3: a provider returned a model the app did not request. Steady state is an "
                                      "empty list — the app has no model-substitution path, so any row here is a provider "
                                      "(usually the local Claude Code CLI) overriding a contract. `since_fix` is what "
                                      "counts: 0.63.29 corrected how the answering model is read from the CLI's "
                                      "modelUsage (cached tokens were ignored, so the CLI's scaffolding model beat the "
                                      "model that did the work), and `before_fix` rows are mis-readings kept rather "
                                      "than deleted."},
            "flags": _flags_health(),
            "release": _last_release_check(),
            "app_version": __import__("neurosearch").__version__,
            "library": _library_health(conn),
            "network": {"fetch_blocked": ev["fetch_blocked"], "note": "J1 boundary: fetches refused (private/internal address, bad scheme, size, redirect or time limit); reasons in validation_events kind=fetch_blocked"},
            "rerank": {"enabled": bool(settings.retrieval_rerank), "applied": ev["rerank_applied"], "fallbacks": ev["rerank_fallback"],
                       "note": "I2 experiment: reorders retrieved candidates only; every failure restores the retrieval ordering"},
            "prefilter": {"enabled": bool(settings.findings_prefilter), "keep": ev["prefilter_keep"], "uncertain": ev["prefilter_uncertain"], "drop": ev["prefilter_drop"],
                          "fail_open": ev["prefilter_fail_open"], "aggressive_sources_flagged": ev["prefilter_aggressive"],
                          "note": "drop is the only outcome that skips analysis; aggressive = a source lost ≥80% of ≥3 windows (flagged, never overridden)"},
            "evidence": {**ev,
                         "findings_kept": max(0, ev["findings_checked"] - ev["findings_rejected"]),
                         # Of the findings that PASSED quote validation, the share that could actually be cited: a
                         # verified finding with no locator is unusable as evidence, so validity alone was never the
                         # whole question (0.63.22). Both halves are counted by the SAME code path from the same
                         # release, so the rate describes one period — 0.63.23 divided the new uncitable count by
                         # the all-time `findings_checked` and read 100% while 79 uncited findings sat in the
                         # library. `citation_rate_since` says how many findings the rate is actually about.
                         "citation_rate_since": ev["findings_citable"] + ev["findings_uncitable"],
                         "finding_citation_rate": round(ev["findings_citable"] / (ev["findings_citable"] + ev["findings_uncitable"]), 4)
                                                  if (ev["findings_citable"] + ev["findings_uncitable"]) else None,
                         "finding_quote_validity": round(1 - ev["findings_rejected"] / ev["findings_checked"], 4) if ev["findings_checked"] else None,
                         "citation_validity": round(1 - ev["citations_invalid"] / ev["citations_checked"], 4) if ev["citations_checked"] else None},
            "disk": disk, "fake_ai": settings.fake_ai}


def _library_health(conn: sqlite3.Connection) -> dict[str, Any]:
    """G1: the Global Library as a reuse asset — how many sources, how many are shared by several projects, how many
    acquisitions were avoided because an add resolved to something already owned."""
    n = conn.execute("SELECT COUNT(*) FROM sources WHERE status != 'proposed'").fetchone()[0]
    ready = conn.execute("SELECT COUNT(*) FROM sources WHERE status = 'ready'").fetchone()[0]
    shared = conn.execute("SELECT COUNT(*) FROM (SELECT source_id FROM project_sources GROUP BY source_id HAVING COUNT(*) > 1)").fetchone()[0]
    dup_fp = conn.execute("SELECT COUNT(*) FROM (SELECT platform, content_fingerprint FROM sources WHERE content_fingerprint IS NOT NULL "
                          "GROUP BY platform, content_fingerprint HAVING COUNT(*) > 1)").fetchone()[0]
    cands = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    cand_unacq = conn.execute("SELECT COUNT(*) FROM candidates WHERE source_id IS NULL").fetchone()[0]
    try:
        from . import library
        profiles = library.stats()
    except Exception:  # noqa: BLE001
        profiles = None
    try:
        from . import works as _works
        works_stats = _works.stats()
    except Exception:  # noqa: BLE001
        works_stats = None
    return {"sources": n, "ready": ready, "shared_by_projects": shared, "candidates_seen": cands, "candidates_not_acquired": cand_unacq, "profiles": profiles, "works": works_stats,
            "acquisitions_avoided": int(kv_get("library:acquisitions_avoided") or 0),
            "failed_attached": int(kv_get("library:failed_attached") or 0),
            "duplicate_fingerprints": dup_fp,
            "note": "one global acquisition, N project relationships; acquisitions_avoided counts adds that resolved to an owned source"}


def set_job_payload(job_id: str, payload: dict[str, Any]) -> None:
    with tx() as conn:
        conn.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(payload), job_id))


def retry_job(job_id: str) -> dict[str, Any] | None:
    """Re-queue a failed job as a fresh attempt (same kind + payload); the old row is marked as retried."""
    j = get_job(job_id)
    if not j or j["status"] != "failed":
        return None
    payload = {k: v for k, v in (j.get("payload") or {}).items() if k not in ("_attempts", "_external_result")}
    new = create_job(j["kind"], payload, blocked_by=j.get("blocked_by") or None, dependency_policy=j.get("dependency_policy") or "ALL_SUCCESS")
    update_job(job_id, status="done", message=f"retried → {new['id'][:8]} — {j.get('message') or ''}"[:500])
    job_event(job_id, "retried", new_job=new["id"])
    sid = payload.get("source_id")
    if sid:
        set_source_status(sid, "pending")
    # dependents that were blocked on (or failed because of) the old job now depend on the new one and get to run
    with tx() as conn:
        for d in conn.execute("SELECT id, status, blocked_by, message FROM jobs WHERE blocked_by LIKE ?", (f'%{job_id}%',)).fetchall():
            try:
                deps = json.loads(d["blocked_by"] or "[]")
            except ValueError:
                continue
            if job_id not in deps:
                continue
            old_deps = list(deps)
            deps = [new["id"] if x == job_id else x for x in deps]
            _check_no_cycle(conn, d["id"], deps)
            job_event(d["id"], "dependency_rewired", conn=conn, previous=old_deps, now=deps, retried_upstream=job_id, replacement=new["id"])
            if d["status"] == "failed" and (d["message"] or "").startswith("error: not run — "):
                conn.execute("UPDATE jobs SET blocked_by=?, status='queued', finished_at=NULL, message='waiting for upstream jobs (retried)', updated_at=? WHERE id=?",
                             (json.dumps(deps), now(), d["id"]))
                job_event(d["id"], "unblocked", conn=conn, retried_upstream=job_id, now_waiting_on=new["id"])
            else:
                conn.execute("UPDATE jobs SET blocked_by=?, updated_at=? WHERE id=?", (json.dumps(deps), now(), d["id"]))
    return new


def failed_jobs(project_id: str | None = None, since_hours: float = 48) -> list[dict[str, Any]]:
    out = []
    for j in list_jobs(limit=1000):
        if j["status"] != "failed" or (now() - (j.get("finished_at") or j.get("created_at") or 0)) > since_hours * 3600:
            continue
        if project_id and (j.get("payload") or {}).get("project_id") not in (None, project_id):
            continue
        out.append(j)
    return out


def park_provider_wait(job_id: str, operation: str, until: float, message: str) -> None:
    """J2: the job asked a provider whose circuit is open. It goes back to the queue in the distinct `provider_wait` state:
    no attempt counted, nothing spent, woken when the breaker closes (or at the next probe time, to try for the probe)."""
    with tx() as conn:
        r = conn.execute("SELECT run_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.execute("UPDATE jobs SET status='queued', started_at=NULL, run_id=NULL, worker_id=NULL, lease_until=NULL, not_before=?, message=?, "
                     "wait_reason='provider', wait_operation=?, updated_at=? WHERE id=?", (until, message, operation, now(), job_id))
        job_event(job_id, "provider_wait", run_id=r["run_id"] if r else None, conn=conn, operation=operation, until=until)


def wake_provider_wait(operation: str) -> int:
    """The circuit closed: every job parked on that operation becomes runnable now."""
    with tx() as conn:
        n = conn.execute("UPDATE jobs SET not_before=NULL, message='provider available again — resuming', updated_at=? "
                         "WHERE status='queued' AND wait_reason='provider' AND wait_operation=?", (now(), operation)).rowcount
    return int(n or 0)


def provider_wait_jobs(operation: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM jobs WHERE status='queued' AND wait_reason='provider'" + (" AND wait_operation=?" if operation else "")
    return [row_to_dict(r) for r in connect().execute(q, (operation,) if operation else ()).fetchall()]  # type: ignore[misc]


def requeue_job(job_id: str, delay: float = 0, message: str | None = None, wait_reason: str | None = None, count_attempt: bool = False) -> None:
    """Back to the queue after `delay` seconds. wait_reason: retry | budget | rate_limit (budget/rate-limit waits are not
    failures and never count as attempts)."""
    with tx() as conn:
        r = conn.execute("SELECT run_id FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.execute("UPDATE jobs SET status='queued', started_at=NULL, run_id=NULL, worker_id=NULL, lease_until=NULL, not_before=?, message=?, "
                     "wait_reason=?, attempts=attempts+?, updated_at=? WHERE id=?",
                     (now() + delay, message, wait_reason, 1 if count_attempt else 0, now(), job_id))
        job_event(job_id, f"{wait_reason}_wait" if wait_reason else "requeued", run_id=r["run_id"] if r else None, conn=conn, delay=delay, message=(message or "")[:200])


def requeue_stale_running_jobs() -> int:
    """On startup: jobs left 'running' by a crashed process go back to queued (lease-based recovery)."""
    return len(recover_expired_leases(all_running=True))


# -------------------------------------------------------------- projects

def project_steering(p: dict[str, Any]) -> str:
    """Everything the user told us up front, as one block for prompts."""
    lines = []
    if p.get("goal"):
        lines.append(f"Goal (what done looks like): {p['goal']}")
    if p.get("brief"):
        lines.append(f"Brief (what we need to find out): {p['brief']}")
    if p.get("context"):
        lines.append(f"Situation (budget, deadline, experience, tools, constraints): {p['context']}")
    if p.get("audience"):
        lines.append(f"Who this is for: {p['audience']}")
    if p.get("output_pref"):
        lines.append(f"Desired outcome/output: {p['output_pref']}")
    if p.get("source_prefs"):
        lines.append(f"Source preferences: {p['source_prefs']}")
    qs = p.get("questions") or []
    if isinstance(qs, str):
        try:
            qs = json.loads(qs)
        except ValueError:
            qs = []
    if qs:
        lines.append("Starting questions: " + " | ".join(qs))
    return "\n".join(lines) or "(nothing provided)"


def create_project(name: str, brief: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    pid = new_id()
    with tx() as conn:
        t = now()
        conn.execute(
            "INSERT INTO projects (id, name, brief, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pid, name, brief, json.dumps(tags or []), t, t),
        )
    return get_project(pid)  # type: ignore[return-value]


def update_project(project_id: str, **fields: Any) -> dict[str, Any] | None:
    fields = {k: v for k, v in fields.items()
              if k in ("name", "brief", "tags", "context", "mode", "goal", "audience", "output_pref", "source_prefs", "questions") and v is not None}
    for k in ("tags", "questions"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    if fields:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k}=?" for k in fields)
        tracked = [k for k in ("brief", "goal", "questions") if k in fields]
        with tx() as conn:
            old = conn.execute("SELECT brief, goal, questions FROM projects WHERE id=?", (project_id,)).fetchone()
            conn.execute(f"UPDATE projects SET {sets} WHERE id=?", (*fields.values(), project_id))
            if old is not None and tracked:
                from . import ledger
                ledger.record(conn, project_id, event_type="brief_changed", object_type="project", object_id=project_id,
                              before={k: old[k] for k in tracked}, after={k: fields[k] for k in tracked}, floor={"standard"})
    return get_project(project_id)


def get_project(project_id: str) -> dict[str, Any] | None:
    row = row_to_dict(connect().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
    if row:
        row["source_ids"] = project_source_ids(project_id)
        row["n_sources"] = len(row["source_ids"])
        row["collections"] = [dict(r) for r in connect().execute(
            "SELECT c.* FROM collections c JOIN project_collections pc ON pc.collection_id=c.id WHERE pc.project_id=?",
            (project_id,)).fetchall()]
    return row


def find_project(name_or_id: str) -> dict[str, Any] | None:
    p = get_project(name_or_id)
    if p:
        return p
    row = connect().execute("SELECT id FROM projects WHERE lower(name)=lower(?)", (name_or_id,)).fetchone()
    return get_project(row["id"]) if row else None


def list_projects() -> list[dict[str, Any]]:
    rows = [row_to_dict(r) for r in connect().execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()]
    for r in rows:
        r["n_sources"] = len(project_source_ids(r["id"]))  # type: ignore[index]
    return rows  # type: ignore[return-value]


def delete_project(project_id: str) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


def project_source_ids(project_id: str, ready_only: bool = True) -> list[str]:
    """Sources in a project: direct members + members of linked collections + tag matches.
    ready_only=True (default) is what search uses; False also returns pending/failed ones for listing."""
    conn = connect()
    st = "s.status='ready'" if ready_only else "1=1"
    p = conn.execute("SELECT tags FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p:
        return []
    ids: set[str] = set()
    ids.update(r["source_id"] for r in conn.execute(
        f"SELECT ps.source_id FROM project_sources ps JOIN sources s ON s.id=ps.source_id WHERE ps.project_id=? AND ps.excluded=0 AND {st}",
        (project_id,)).fetchall())
    ids.update(r["source_id"] for r in conn.execute(
        f"""SELECT sc.source_id FROM project_collections pc
           JOIN source_collections sc ON sc.collection_id = pc.collection_id
           JOIN sources s ON s.id = sc.source_id
           WHERE pc.project_id=? AND {st}""", (project_id,)).fetchall())
    try:
        tags = json.loads(p["tags"] or "[]")
    except ValueError:
        tags = []
    if tags:
        st2 = st.replace("s.status", "status")
        for r in conn.execute(f"SELECT id, tags FROM sources WHERE {st2} AND tags IS NOT NULL").fetchall():
            try:
                stags = json.loads(r["tags"] or "[]")
            except ValueError:
                continue
            if any(t in stags for t in tags):
                ids.add(r["id"])
    excluded = {r["source_id"] for r in conn.execute("SELECT source_id FROM project_sources WHERE project_id=? AND excluded=1", (project_id,)).fetchall()}
    return sorted(ids - excluded)


def _ledger_membership(conn: sqlite3.Connection, project_id: str, source_ids: list[str], *, adding: bool) -> list[str]:
    """P11 EA-2: which of `source_ids` this add/remove will actually change (read before the write, same tx)."""
    ids = list(dict.fromkeys(source_ids))
    have: dict[str, int] = {}
    for i in range(0, len(ids), 800):
        part = ids[i:i + 800]
        q = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT source_id, excluded FROM project_sources WHERE project_id=? AND source_id IN ({q})", (project_id, *part)).fetchall():
            have[r["source_id"]] = r["excluded"]
    if adding:
        return [s for s in ids if have.get(s, 1) == 1]          # absent, or present only as an exclusion marker
    return [s for s in ids if have.get(s) == 0]


def _record_membership(conn: sqlite3.Connection, project_id: str, changed: list[str], event_type: str) -> None:
    if not changed:
        return
    from . import access, ledger
    cls = access.source_classes(changed)
    for sid in changed:
        member = event_type == "source_attached"
        ledger.record(conn, project_id, event_type=event_type, object_type="source_membership", object_id=sid,
                      before={"member": not member}, after={"member": member}, floor={cls[sid]})


def add_project_sources(project_id: str, source_ids: list[str]) -> None:
    with tx() as conn:
        changed = _ledger_membership(conn, project_id, source_ids, adding=True)
        conn.executemany("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", [(project_id, s) for s in source_ids])
        conn.executemany("UPDATE project_sources SET excluded=0 WHERE project_id=? AND source_id=? AND excluded=1", [(project_id, s) for s in source_ids])   # an explicit add lifts a removal
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
        _record_membership(conn, project_id, changed, "source_attached")



# ------------------------------------------------------------------ Mission BOOTSTRAP (R2): reuse suggestions

def upsert_project_reuse(project_id: str, rows: list[dict[str, Any]], brief_revision_: str | None = None,
                         scan_version: str | None = None) -> int:
    """Store this scan's suggestions. A row the user has already decided on (attached/dismissed) keeps its state —
    a re-scan may refresh why it matched, but it never un-decides the user."""
    if not rows:
        return 0
    t = time.time()
    conn = connect()
    with conn:
        for r in rows:
            conn.execute(
                """INSERT INTO project_reuse (project_id, object_kind, object_id, state, band, score, why, origin, brief_revision, scan_version, created_at, updated_at)
                   VALUES (?,?,?, 'suggested', ?,?,?,?,?,?,?,?)
                   ON CONFLICT(project_id, object_kind, object_id) DO UPDATE SET
                     band=excluded.band, score=excluded.score, why=excluded.why, origin=excluded.origin,
                     brief_revision=excluded.brief_revision, scan_version=excluded.scan_version,
                     updated_at=excluded.updated_at""",
                (project_id, r["object_kind"], r["object_id"], r.get("band"), r.get("score"), r.get("why"),
                 r.get("origin"), brief_revision_, scan_version, t, t))
    return len(rows)


def list_project_reuse(project_id: str, object_kind: str = "source", state: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM project_reuse WHERE project_id=? AND object_kind=?"
    args: list[Any] = [project_id, object_kind]
    if state:
        q += " AND state=?"
        args.append(state)
    return [dict(r) for r in connect().execute(q + " ORDER BY (band='strong') DESC, score DESC", args).fetchall()]


def retire_project_reuse(project_id: str, keep_object_ids: list[str], object_kind: str = "source") -> int:
    """Retire the SUGGESTED rows this scan did not reproduce (0.61.0).

    A suggested row's only author is the scan, so a scan that no longer makes the suggestion may withdraw it. Rows
    the user decided on — attached or dismissed — are never touched, and the row is kept in a `retired` state
    rather than deleted, so "5 earlier suggestions no longer match" is still an answerable question."""
    keep = set(keep_object_ids or [])
    with tx() as conn:
        rows = conn.execute("SELECT object_id FROM project_reuse WHERE project_id=? AND object_kind=? AND state='suggested'",
                            (project_id, object_kind)).fetchall()
        gone = [r["object_id"] for r in rows if r["object_id"] not in keep]
        if not gone:
            return 0
        conn.execute(f"UPDATE project_reuse SET state='retired', updated_at=? WHERE project_id=? AND object_kind=? "
                     f"AND object_id IN ({','.join('?' for _ in gone)})", (now(), project_id, object_kind, *gone))
        return len(gone)


def set_project_reuse_state(project_id: str, object_ids: list[str], state: str, object_kind: str = "source") -> int:
    if not object_ids:
        return 0
    conn = connect()
    with conn:
        cur = conn.execute(
            f"UPDATE project_reuse SET state=?, updated_at=? WHERE project_id=? AND object_kind=? AND object_id IN ({','.join('?' for _ in object_ids)})",
            (state, time.time(), project_id, object_kind, *object_ids))
    return cur.rowcount


def record_bootstrap_run(project_id: str, summary: dict[str, Any], brief_revision_: str | None = None) -> None:
    kv_set(f"bootstrap:run:{project_id}", json.dumps({**summary, "brief_revision": brief_revision_, "at": time.time()}))


def last_bootstrap_run(project_id: str) -> dict[str, Any] | None:
    raw = kv_get(f"bootstrap:run:{project_id}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def project_source_inventory(project_id: str) -> list[dict[str, Any]]:
    """Compact inventory of a project's sources (all statuses except proposed) for the chat's list_sources /
    inventory block: id, platform, title, channel, published_at, duration, description, status, priority. Newest first."""
    ids = project_source_ids(project_id, ready_only=False)
    if not ids:
        return []
    conn = connect()
    prio = priority_source_ids(project_id)
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        rows = conn.execute("SELECT id, platform, title, channel, published_at, duration, description, status, url, created_at FROM sources "
                            "WHERE id IN (" + ",".join("?" for _ in part) + ") AND status != 'proposed'", part).fetchall()
        for r in rows:
            d = row_to_dict(r)
            if d["platform"] not in ("document", "spreadsheet", "book"):
                d["description"] = None                       # long video descriptions are not inventory material
            d["priority"] = d["id"] in prio
            out.append(d)
    out.sort(key=lambda d: -(d.get("created_at") or 0))
    return out


def set_source_priority(project_id: str, source_ids: list[str], priority: bool) -> int:
    """Flag (or unflag) sources as priority for THIS project only. A source reached through a collection or tag gets
    a direct project_sources row so the flag has somewhere to live. Returns the number of rows touched."""
    n = 0
    with tx() as conn:
        for sid in source_ids:
            conn.execute("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", (project_id, sid))
            n += conn.execute("UPDATE project_sources SET priority=? WHERE project_id=? AND source_id=?", (1 if priority else 0, project_id, sid)).rowcount
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))
    return n


def priority_source_ids(project_id: str) -> set[str]:
    return {r["source_id"] for r in connect().execute("SELECT source_id FROM project_sources WHERE project_id=? AND priority=1", (project_id,)).fetchall()}


def remove_project_sources(project_id: str, source_ids: list[str]) -> None:
    """Remove from THIS project and remember it: the row stays as an exclusion marker so a linked collection, a tag match
    or a retried ingest job cannot bring the source back (0.34.2 — the 'it keeps showing up' bug)."""
    with tx() as conn:
        changed = _ledger_membership(conn, project_id, source_ids, adding=False)
        conn.executemany("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", [(project_id, s) for s in source_ids])
        conn.executemany("UPDATE project_sources SET excluded=1, priority=0 WHERE project_id=? AND source_id=?", [(project_id, s) for s in source_ids])
        _record_membership(conn, project_id, changed, "source_removed")


def add_project_collections(project_id: str, collection_ids: list[str]) -> None:
    with tx() as conn:
        # CR8: named columns, not bare VALUES(?,?) -- project_collections gained source_role/monitor_policy
        # (both DEFAULT-backed), and a positional VALUES(?,?) breaks the moment the table has more than 2
        # columns. INSERT OR IGNORE leaves an existing row's policy untouched on a re-attach.
        conn.executemany("INSERT OR IGNORE INTO project_collections (project_id, collection_id) VALUES (?,?)",
                         [(project_id, c) for c in collection_ids])
        # Catalog membership is candidate-only. A project attaching to an existing catalog should be able to
        # review its remembered rows immediately, while never inheriting another project's captured Sources.
        t = now()
        for collection_id in dict.fromkeys(collection_ids):
            # A thread may have been captured directly before an older catalog candidate was reconciled.
            # Repair only this attached catalog's unresolved Reddit bridge, once at attachment time; page
            # scans keep their bounded metadata write and do not rewrite the whole catalog.
            conn.execute(
                "UPDATE candidates SET source_id=(SELECT s.id FROM sources s "
                "WHERE s.platform='community' AND s.external_id=candidates.external_id) "
                "WHERE platform='reddit' AND source_id IS NULL "
                "AND id IN (SELECT candidate_id FROM collection_candidates WHERE collection_id=?) "
                "AND EXISTS (SELECT 1 FROM sources s WHERE s.platform='community' AND s.external_id=candidates.external_id)",
                (collection_id,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO candidate_projects (candidate_id, project_id, state, origin, first_seen_at, updated_at) "
                "SELECT cc.candidate_id, ?, 'available', ?, ?, ? FROM collection_candidates cc "
                "WHERE cc.collection_id=?",
                (project_id, json.dumps({"kind": "catalog", "collection_id": collection_id}), t, t, collection_id),
            )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))


def remove_project_collections(project_id: str, collection_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("DELETE FROM project_collections WHERE project_id=? AND collection_id=?",
                         [(project_id, c) for c in collection_ids])


def get_collection_policy(project_id: str, collection_id: str) -> dict[str, Any] | None:
    """CR8 (2026-09-16): the raw, stored source_role/monitor_policy for one project<->collection relationship.
    None when the relationship itself doesn't exist (never attached, or removed)."""
    row = connect().execute(
        "SELECT project_id, collection_id, source_role, monitor_policy FROM project_collections "
        "WHERE project_id=? AND collection_id=?", (project_id, collection_id)).fetchone()
    return dict(row) if row else None


def set_collection_policy(project_id: str, collection_id: str, *, source_role: str | None = None,
                          monitor_policy: str | None = None) -> dict[str, Any] | None:
    """CR8 (2026-09-16): update source_role and/or monitor_policy on an EXISTING project<->collection
    relationship. Only touches the field(s) given -- passing just one leaves the other as stored. Never creates
    the relationship itself (add_project_collections does that); returns None if it doesn't exist. Pure
    bookkeeping -- never touches candidates/sources/jobs, so changing policy never ingests anything."""
    if source_role is not None and source_role not in ("primary", "secondary", "unspecified"):
        raise ValueError(f"invalid source_role: {source_role!r}")
    if monitor_policy is not None and monitor_policy not in ("auto", "on", "off"):
        raise ValueError(f"invalid monitor_policy: {monitor_policy!r}")
    if source_role is None and monitor_policy is None:
        return get_collection_policy(project_id, collection_id)
    with tx() as conn:
        if source_role is not None:
            conn.execute("UPDATE project_collections SET source_role=? WHERE project_id=? AND collection_id=?",
                        (source_role, project_id, collection_id))
        if monitor_policy is not None:
            conn.execute("UPDATE project_collections SET monitor_policy=? WHERE project_id=? AND collection_id=?",
                        (monitor_policy, project_id, collection_id))
    return get_collection_policy(project_id, collection_id)


def add_project_note(project_id: str, content: str, citations: list | None = None, status: str = "approved",
                     source_id: str | None = None, importance: int | None = None) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO project_notes (project_id, content, citations, created_at, status, source_id, importance) VALUES (?,?,?,?,?,?,?)",
            (project_id, content, json.dumps(citations or []), now(), status, source_id, importance),
        )
        return row_to_dict(conn.execute("SELECT * FROM project_notes WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_project_notes(project_id: str, status: str | None = "approved", limit: int | None = None) -> list[dict[str, Any]]:
    """Approved notes by default (what exports and the planner use). status=None returns all.

    `limit` exists because this returns FULL note text: on Kyle's business project that is 11,767 notes and about
    8 MB, and `/api/projects/{id}` was shipping all of it to the browser on every visit to the Findings, Chats,
    Settings and Plan views (0.60.1). A caller that wants everything still gets everything by leaving it None."""
    if status:
        q = "SELECT * FROM project_notes WHERE project_id=? AND status=? ORDER BY importance DESC, created_at DESC"
        args: tuple[Any, ...] = (project_id, status)
    else:
        q = "SELECT * FROM project_notes WHERE project_id=? ORDER BY created_at DESC"
        args = (project_id,)
    if limit is not None:
        q += " LIMIT ?"
        args = (*args, int(limit))
    return [row_to_dict(r) for r in connect().execute(q, args).fetchall()]  # type: ignore[misc]


# 0.61.2 — THE WRITE-AHEAD LOG WAS 112 MB AND NEVER SHRANK.
#
# Measured on Kyle's machine while the app was unresponsive: `data/neurosearch.db` 627 MB and
# `data/neurosearch.db-wal` **111.8 MB**, static — not growing, not shrinking. SQLite auto-checkpoints at
# `wal_autocheckpoint` (1000 pages ≈ 4 MB) but only when no reader holds an older snapshot, and this app keeps a
# long-lived connection per thread while several threads run multi-second derived-state passes. So the checkpoint
# was starved and every read had to walk a 112 MB log. `journal_size_limit` was -1, meaning the file is never
# truncated even after a successful checkpoint.
WAL_LIMIT_BYTES = 64 * 1024 * 1024        # truncate the log back to this after a checkpoint
WAL_CHECKPOINT_AT = 32 * 1024 * 1024      # above this, force a checkpoint at the next quiet moment


def wal_bytes() -> int:
    try:
        return int(os.path.getsize(str(settings.db_path) + "-wal"))
    except OSError:
        return 0


def checkpoint_wal(force: bool = False) -> dict[str, Any]:
    """TRUNCATE the write-ahead log when it has grown past `WAL_CHECKPOINT_AT`.

    TRUNCATE (not PASSIVE) because the point is to give the file back: a passive checkpoint leaves 112 MB of
    already-copied log on disk. It can fail while a reader holds an old snapshot, which is not an error — it just
    means try again later, so this reports rather than raises."""
    before = wal_bytes()
    if not force and before < WAL_CHECKPOINT_AT:
        return {"checkpointed": False, "wal_bytes": before, "why": "below the threshold"}
    try:
        conn = connect()
        conn.execute(f"PRAGMA journal_size_limit={WAL_LIMIT_BYTES}")
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        after = wal_bytes()
        ok = bool(row is not None and int(row[0]) == 0)
        if ok:
            logging.getLogger(__name__).info("WAL checkpointed: %.1f MB -> %.1f MB", before / 1e6, after / 1e6)
        return {"checkpointed": ok, "wal_bytes": after, "was": before,
                "why": None if ok else "a reader still holds an older snapshot — it will be retried"}
    except Exception as e:  # noqa: BLE001 — a housekeeping step must never break a request
        return {"checkpointed": False, "wal_bytes": before, "why": str(e)[:160]}


def analyze_if_due(force: bool = False) -> dict[str, Any]:
    """Refresh SQLite planner statistics at most weekly.

    `ANALYZE` had never run on the measured backup (`sqlite_stat1` was absent). The housekeeping thread owns this
    maintenance so request paths never pay for it. A durable timestamp makes restarts cheap; failures leave the
    timestamp untouched and are retried by the next housekeeping pass.
    """
    key = "storage:last_analyze"
    try:
        last = float(kv_get(key) or 0)
    except (TypeError, ValueError):
        last = 0
    age = max(0.0, now() - last)
    if not force and age < ANALYZE_INTERVAL_S:
        return {"analyzed": False, "why": "not due", "age_s": age}
    started = time.perf_counter()
    conn = connect()
    conn.execute("ANALYZE")
    kv_set(key, str(now()))
    rows = conn.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0]
    return {"analyzed": True, "seconds": round(time.perf_counter() - started, 3), "stat_rows": int(rows)}


def chunk_count() -> int:
    r = connect().execute("SELECT COUNT(*) n FROM chunks").fetchone()
    return int(r["n"] or 0)


def sources_with_chunks() -> int:
    """The denominator for term rarity: sources that actually have retrievable text (0.60.2)."""
    r = connect().execute("SELECT COUNT(DISTINCT source_id) n FROM chunks").fetchone()
    return int(r["n"] or 0)


def library_revision() -> str:
    """A fingerprint of the retrievable library: how many chunks exist and when a source last changed. Term rarity
    (library.term_df) only moves when this does, so it is what those lookups cache on (0.60.2)."""
    r = connect().execute("SELECT (SELECT COUNT(*) FROM chunks), (SELECT COALESCE(MAX(updated_at),0) FROM sources)").fetchone()
    return f"{r[0]}:{r[1]}"


def analysis_jobs_queued(project_id: str) -> int:
    """How many findings jobs for this project are QUEUED rather than running — the ones a first wave can move to
    the front. Previously the browser derived this by downloading every source in the project (0.60.1)."""
    n = 0
    for r in connect().execute("SELECT payload FROM jobs WHERE kind IN ('suggest_findings','suggest_findings_batch') "
                               "AND status='queued'").fetchall():
        try:
            if json.loads(r["payload"]).get("project_id") == project_id:
                n += 1
        except ValueError:
            continue
    return n


def note_counts(project_id: str) -> dict[str, int]:
    """Counts by status, so a screen can show "1,383 suggested" without downloading 1,383 findings."""
    rows = connect().execute("SELECT COALESCE(status,'approved') s, COUNT(*) n FROM project_notes WHERE project_id=? "
                             "GROUP BY s", (project_id,)).fetchall()
    out = {r["s"]: int(r["n"]) for r in rows}
    out["total"] = sum(out.values())
    return out


def set_note_status(note_id: int, status: str) -> dict[str, Any] | None:
    """The one door every status change goes through, so stamping `reviewed_at` here covers every path -- the
    drawer, the workbench, bulk, focus review and the sweeps -- and cannot be bypassed by adding a caller."""
    with tx() as conn:
        before = conn.execute("SELECT status, project_id FROM project_notes WHERE id=?", (note_id,)).fetchone()
        conn.execute("UPDATE project_notes SET status=?, reviewed_at=?, "
                     "created_at=CASE WHEN ?='approved' THEN ? ELSE created_at END WHERE id=?",
                     (status, now(), status, now(), note_id))
        row = row_to_dict(conn.execute("SELECT * FROM project_notes WHERE id=?", (note_id,)).fetchone())
        if before is not None:
            from . import ledger
            ledger.record(conn, before["project_id"], event_type="finding_status_changed", object_type="finding", object_id=note_id,
                          before={"status": before["status"] or "approved"}, after={"status": status})
    # 2026-09-21: a status crossing the dismissed line re-assesses the Claims this finding backs -- the twin of
    # the G5 source-revision hook above (`stale_by_source`). Same shape on purpose: only when it matters, a late
    # import, and never able to break the write it follows.
    was = (before["status"] if before else None) or "approved"
    if row and (was == "dismissed") != (status == "dismissed"):
        try:
            if connect().execute("SELECT 1 FROM project_claims WHERE origin_note_id=? LIMIT 1", (note_id,)).fetchone() \
                    or connect().execute("SELECT 1 FROM claim_evidence_notes WHERE note_id=? LIMIT 1", (note_id,)).fetchone():
                from . import claims
                claims.stale_by_note(note_id)
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning("claim re-assessment hook skipped for note %s: %s", note_id, e)
    return row


def replace_suggestions(project_id: str, source_id: str, notes: list[dict[str, Any]], provenance: dict[str, Any] | None = None) -> int:
    """Replace pending suggestions for (project, source); dismissed/approved ones are kept. Every note records the
    model/prompt that wrote it and the brief + source revisions it was written against."""
    prov = provenance or {}
    srev = prov.get("source_revision") or source_revision(source_id)
    brev = prov.get("brief_revision") or brief_revision(project_id)
    with tx() as conn:
        # Only delete pending suggestions that nothing has adopted yet. harvest() (claims.py) can turn a
        # still-'suggested'/'reserve' note into a Claim's origin (project_claims.origin_note_id) or fold it in as
        # evidence (claim_evidence_notes) without ever changing the note's own status - so a blanket delete here
        # would silently orphan that Claim's provenance link the next time this source is re-suggested. Exclude
        # any note a Claim has already adopted; genuinely-untouched pending suggestions are unaffected.
        conn.execute(
            "DELETE FROM project_notes WHERE project_id=? AND source_id=? AND status IN ('suggested','reserve') "
            "AND id NOT IN (SELECT origin_note_id FROM project_claims WHERE origin_note_id IS NOT NULL) "
            "AND id NOT IN (SELECT note_id FROM claim_evidence_notes)",
            (project_id, source_id))
        t = now()
        conn.executemany(
            "INSERT INTO project_notes (project_id, content, citations, created_at, status, source_id, importance, title, model, prompt_version, source_revision, brief_revision, input_hash, transport, batch_id, routing) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(project_id, n["content"], json.dumps(n.get("citations") or []), t, n.get("status") or "suggested", source_id, n.get("importance"), n.get("title"),
              prov.get("model"), prov.get("prompt_version"), srev, brev, prov.get("input_hash"), prov.get("transport", "interactive"), prov.get("batch_id"), prov.get("routing")) for n in notes])
        conn.execute("UPDATE project_sources SET suggested_at=? WHERE project_id=? AND source_id=?", (t, project_id, source_id))
        if conn.execute("SELECT 1 FROM project_sources WHERE project_id=? AND source_id=?", (project_id, source_id)).fetchone() is None:
            conn.execute("INSERT OR IGNORE INTO project_sources (project_id, source_id, suggested_at) VALUES (?,?,?)", (project_id, source_id, t))
    return sum(1 for n in notes if (n.get("status") or "suggested") == "suggested")


def sources_needing_suggestions(project_id: str) -> list[str]:
    """Ready sources in the project that have never had findings suggested for this project."""
    conn = connect()
    done = {r["source_id"] for r in conn.execute(
        "SELECT source_id FROM project_sources WHERE project_id=? AND suggested_at IS NOT NULL", (project_id,)).fetchall()}
    done |= {r["source_id"] for r in conn.execute(
        "SELECT DISTINCT source_id FROM project_notes WHERE project_id=? AND source_id IS NOT NULL", (project_id,)).fetchall()}
    return [s for s in project_source_ids(project_id) if s not in done]


def suggestion_counts(project_id: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in connect().execute(
        "SELECT source_id, status, COUNT(*) n FROM project_notes WHERE project_id=? AND source_id IS NOT NULL GROUP BY source_id, status",
        (project_id,)).fetchall():
        out.setdefault(r["source_id"], {})[r["status"]] = r["n"]
    return out


def analysed_sources(project_id: str) -> set[str]:
    return {r["source_id"] for r in connect().execute(
        "SELECT source_id FROM project_sources WHERE project_id=? AND suggested_at IS NOT NULL", (project_id,)).fetchall()}


def analysis_jobs_by_source(project_id: str) -> dict[str, dict[str, Any]]:
    """source_id → the queued/running findings job on it (status, message, progress, depth, lane) — the source card's live line."""
    out: dict[str, dict[str, Any]] = {}
    for r in connect().execute("SELECT id, status, message, progress, payload, lane, updated_at FROM jobs WHERE kind='suggest_findings' AND status IN ('queued','running') ORDER BY created_at").fetchall():
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        if pl.get("project_id") != project_id:
            continue
        for sid in pl.get("source_ids") or []:
            out.setdefault(sid, {"id": r["id"], "status": r["status"], "message": r["message"], "progress": r["progress"], "depth": pl.get("depth"), "lane": r["lane"], "updated_at": r["updated_at"]})
    return out


def sources_being_analysed(project_id: str) -> set[str]:
    out: set[str] = set()
    for r in connect().execute("SELECT id, kind, payload FROM jobs WHERE kind IN ('suggest_findings','suggest_findings_batch') AND status IN ('queued','running','external_pending')").fetchall():
        try:
            pl = json.loads(r["payload"])
        except ValueError:
            continue
        if pl.get("project_id") != project_id:
            continue
        if r["kind"] == "suggest_findings_batch":
            # a background job: only the sources whose findings have not landed yet (completed sources are usable already)
            planned = {x["source_id"] for x in batch_items(r["id"])}
            landed = {x["source_id"] for x in batch_items(r["id"], status="materialized")}
            out.update((planned or set(pl.get("source_ids") or [])) - landed)
        else:
            out.update(pl.get("source_ids") or [])
    return out


def add_discoveries(project_id: str, items: list[dict[str, Any]], note: str = "", refine: str | None = None,
                    provenance: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    existing = {d["name"].lower() for d in list_discoveries(project_id)}
    prov = provenance or {}
    brev = brief_revision(project_id)
    out = []
    with tx() as conn:
        for it in items:
            if it["name"].lower() in existing:
                continue
            cur = conn.execute(
                """INSERT INTO discoveries (project_id, name, kind, url, known_for, why, angle, start_with, fit, depth, note, refine, created_at, model, prompt_version, brief_revision, routing)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, it["name"], it.get("kind"), it.get("url"), it.get("known_for"), it.get("why"), it.get("angle"),
                 json.dumps(it.get("start_with") or []), it.get("fit"), it.get("depth"), note, refine, now(),
                 prov.get("model"), prov.get("prompt_version"), brev, prov.get("routing")))
            out.append(cur.lastrowid)
    rows = [d for d in list_discoveries(project_id) if d["id"] in set(out)]
    return rows


def update_discovery(disc_id: int, url: str | None = None, start_with: list[dict[str, Any]] | None = None,
                     link_check: dict[str, Any] | None = None) -> None:
    sets, args = [], []
    if url:
        sets.append("url=?"); args.append(url)
    if start_with:
        sets.append("start_with=?"); args.append(json.dumps(start_with))
    if link_check is not None:
        sets.append("link_check=?"); args.append(json.dumps(link_check))
    if sets:
        with tx() as conn:
            conn.execute(f"UPDATE discoveries SET {', '.join(sets)} WHERE id=?", (*args, disc_id))


def list_discoveries(project_id: str, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM discoveries WHERE project_id=?"
    args: list[Any] = [project_id]
    if status:
        sql += " AND status=?"; args.append(status)
    sql += " ORDER BY fit DESC, created_at DESC"
    rows = []
    for r in connect().execute(sql, args).fetchall():
        d = dict(r)
        try:
            d["start_with"] = json.loads(d.get("start_with") or "[]")
        except ValueError:
            d["start_with"] = []
        try:
            d["link_check"] = json.loads(d.get("link_check") or "null")
        except ValueError:
            d["link_check"] = None
        rows.append(d)
    return rows


def set_discovery_status(disc_id: int, status: str) -> dict[str, Any] | None:
    with tx() as conn:
        conn.execute("UPDATE discoveries SET status=? WHERE id=?", (status, disc_id))
        row = conn.execute("SELECT * FROM discoveries WHERE id=?", (disc_id,)).fetchone()
        return dict(row) if row else None


def projects_for_source(source_id: str) -> list[str]:
    """Projects this source belongs to (direct membership or via a linked collection)."""
    conn = connect()
    ids = {r["project_id"] for r in conn.execute("SELECT project_id FROM project_sources WHERE source_id=? AND excluded=0", (source_id,)).fetchall()}
    ids |= {r["project_id"] for r in conn.execute(
        """SELECT pc.project_id FROM project_collections pc JOIN source_collections sc ON sc.collection_id=pc.collection_id
           WHERE sc.source_id=?""", (source_id,)).fetchall()}
    ids -= {r["project_id"] for r in conn.execute("SELECT project_id FROM project_sources WHERE source_id=? AND excluded=1", (source_id,)).fetchall()}
    return sorted(ids)


def set_source_summary(source_id: str, summary: str | None, substance: int | None, project_id: str | None = None, **prov: Any) -> None:
    """A summary/substance score is written against a project's brief, so it belongs to (project, source)."""
    if project_id is None:
        return
    upsert_analysis(project_id, source_id, "summary", summary=summary, substance=substance, **prov)


def delete_project_note(note_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM project_notes WHERE id=?", (note_id,))


# ------------------------------------------------------ facts & plans

def add_fact(project_id: str, kind: str, content: str, origin: str = "user") -> dict[str, Any]:
    """The local write path (UI, MCP record_fact, retire). P11: attributed to whoever is acting (ledger.acting) and
    ledgered; left unclassified for external disclosure until the owner classifies it (§41, §43)."""
    from . import ledger
    who = ledger.current()
    t = now()
    with tx() as conn:
        cur = conn.execute("INSERT INTO project_facts (project_id, kind, content, origin, created_at, actor_id, external_client_id, "
                           "effective_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                           (project_id, kind, content, origin, t, who.get("actor_id"), who.get("client_id"), t, t))
        fid = cur.lastrowid
        from .facts import _event_for
        ledger.record(conn, project_id, event_type=_event_for(kind, "active", "project"), object_type="fact", object_id=fid,
                      before=None, after={"kind": kind, "content": content[:1000], "status": "active", "origin": origin},
                      floor={"restricted"})
        return dict(conn.execute("SELECT * FROM project_facts WHERE id=?", (fid,)).fetchone())


def list_facts(project_id: str, include_history: bool = False) -> list[dict[str, Any]]:
    """The project's CURRENT position (P11: superseded, withdrawn, proposed and personal rows are history or
    someone's preference, not project state). `include_history=True` returns every row."""
    q = "SELECT * FROM project_facts WHERE project_id=?" + ("" if include_history else " AND status='active' AND scope='project'")
    return [dict(r) for r in connect().execute(q + " ORDER BY created_at", (project_id,)).fetchall()]


def delete_fact(fact_id: int) -> None:
    with tx() as conn:
        old = conn.execute("SELECT * FROM project_facts WHERE id=?", (fact_id,)).fetchone()
        conn.execute("DELETE FROM project_facts WHERE id=?", (fact_id,))
        if old is not None:
            from . import ledger
            ledger.record(conn, old["project_id"], event_type="fact_deleted", object_type="fact", object_id=fact_id,
                          before={"kind": old["kind"], "content": old["content"][:1000]}, after={"deleted": True},
                          floor={old["disclosure_class"] or "restricted"})


# Discovery exclude list (item 2, 2026-09-20): a short, explicit "not interested in" list the user controls per
# project, separate from the free-text brief. `project_facts` already had a `rejected` kind for this same intent
# (Kyle rejected laundromats there twice -- ids 8 and 19 on "buying businesses" -- retiring 84 sources at the
# time) but nothing ever READ project_facts to filter candidates; it was pure history, not an active rule. This
# table is deliberately narrow and mechanical (kind + term, nothing else) so `candidates._excluded_by` can check
# every candidate against it cheaply, in Python, with no model call -- unlike the brief, which is free text an AI
# has to interpret.
def add_exclude(project_id: str, kind: str, term: str, reason: str | None = None) -> dict[str, Any]:
    assert kind in ("keyword", "creator")
    with tx() as conn:
        existing = conn.execute("SELECT id FROM project_excludes WHERE project_id=? AND kind=? AND lower(term)=lower(?)",
                                 (project_id, kind, term)).fetchone()
        if existing:
            return dict(conn.execute("SELECT * FROM project_excludes WHERE id=?", (existing["id"],)).fetchone())
        cur = conn.execute("INSERT INTO project_excludes (project_id, kind, term, reason, created_at) VALUES (?,?,?,?,?)",
                           (project_id, kind, term, reason, now()))
        return dict(conn.execute("SELECT * FROM project_excludes WHERE id=?", (cur.lastrowid,)).fetchone())


def list_excludes(project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT * FROM project_excludes WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()]


def delete_exclude(exclude_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM project_excludes WHERE id=?", (exclude_id,))


def _sha(*parts: Any) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def brief_revision(project: dict[str, Any] | str) -> str:
    """Revision of everything the user told us that steers analysis (brief, goal, audience, output, source prefs,
    questions, context). Changes when any of it changes."""
    p = get_project(project) if isinstance(project, str) else project
    if not p:
        return "none"
    return _sha(*(p.get(k) for k in ("brief", "goal", "audience", "output_pref", "source_prefs", "questions", "context")))


def facts_revision(project_id: str) -> str:
    return _sha([(f["kind"], f["content"]) for f in list_facts(project_id)])


def source_set_revision(project_id: str) -> str:
    """Which ready sources are in scope, at which revisions."""
    ids = sorted(project_source_ids(project_id))
    revs: dict[str, Any] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        revs = {r["id"]: r["revision"] for r in connect().execute(f"SELECT id, revision FROM sources WHERE id IN ({marks})", ids).fetchall()}
    return _sha([(i, revs.get(i)) for i in ids])


def project_revisions(project_id: str) -> dict[str, str]:
    return {"brief_revision": brief_revision(project_id), "facts_revision": facts_revision(project_id), "source_set_revision": source_set_revision(project_id)}


def project_snapshot(project_id: str) -> dict[str, int]:
    """Counts used to detect 'research changed since the plan was built'."""
    conn = connect()
    n_msgs = conn.execute("SELECT COUNT(*) n FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.project_id=?",
                          (project_id,)).fetchone()["n"]
    return {
        "sources": len(project_source_ids(project_id)),
        "notes": conn.execute("SELECT COUNT(*) n FROM project_notes WHERE project_id=?", (project_id,)).fetchone()["n"],
        "facts": conn.execute("SELECT COUNT(*) n FROM project_facts WHERE project_id=?", (project_id,)).fetchone()["n"],
        "messages": n_msgs,
    }


def save_plan(project_id: str, plan: dict[str, Any], snapshot: dict[str, Any], carry_statuses_from: str | None = None,
              provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    pid = new_id()
    prov = {**project_revisions(project_id), **(provenance or {})}
    with tx() as conn:
        v = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM plans WHERE project_id=?", (project_id,)).fetchone()["v"]
        t = now()
        conn.execute("""INSERT INTO plans (id, project_id, version, plan, snapshot, created_at, updated_at, model, prompt_version,
                        brief_revision, facts_revision, source_set_revision, routing) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, project_id, v, json.dumps(plan), json.dumps(snapshot), t, t, prov.get("model"), prov.get("prompt_version"),
                      prov["brief_revision"], prov["facts_revision"], prov["source_set_revision"], prov.get("routing")))
        if carry_statuses_from:
            rows = conn.execute("SELECT key, status, note FROM plan_items WHERE plan_id=?", (carry_statuses_from,)).fetchall()
            prev_row = conn.execute("SELECT plan FROM plans WHERE id=?", (carry_statuses_from,)).fetchone()
            prev_ids = (json.loads(prev_row["plan"] or "{}") if prev_row else {}).get("_ids") or {}
            new_ids = plan.get("_ids") or {}
            if prev_ids and new_ids:
                # F4: statuses follow the semantic id, not the array position — a task that moved keeps its DONE
                by_id = {v: k for k, v in new_ids.items()}
                carried = [(pid, by_id[prev_ids[r["key"]]], r["status"], r["note"], t) for r in rows if r["key"] in prev_ids and prev_ids[r["key"]] in by_id]
            else:
                carried = [(pid, r["key"], r["status"], r["note"], t) for r in rows]
            conn.executemany("INSERT OR IGNORE INTO plan_items (plan_id, key, status, note, updated_at) VALUES (?,?,?,?,?)", carried)
        from . import ledger
        ledger.record(conn, project_id, event_type="plan_version_created", object_type="plan", object_id=pid,
                      before=None, after={"version": v}, floor=_plan_floor(conn, plan))
    return get_plan(pid)  # type: ignore[return-value]


def get_plan(plan_id: str) -> dict[str, Any] | None:
    row = connect().execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan"] or "{}")
    d["snapshot"] = json.loads(d["snapshot"] or "{}")
    d["items"] = {r["key"]: {"status": r["status"], "note": r["note"]} for r in
                  connect().execute("SELECT key, status, note FROM plan_items WHERE plan_id=?", (plan_id,)).fetchall()}
    d["updates"] = [dict(r) for r in connect().execute(
        "SELECT * FROM plan_updates WHERE plan_id=? ORDER BY created_at", (plan_id,)).fetchall()]
    return d


def latest_plan(project_id: str) -> dict[str, Any] | None:
    row = connect().execute("SELECT id FROM plans WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
    return get_plan(row["id"]) if row else None


def list_plans(project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT id, version, status, created_at FROM plans WHERE project_id=? ORDER BY version DESC", (project_id,)).fetchall()]


def set_plan_status(plan_id: str, status: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE plans SET status=?, updated_at=? WHERE id=?", (status, now(), plan_id))


def _plan_floor(conn: sqlite3.Connection, plan: dict[str, Any]) -> set[str]:
    """P11: a plan is disclosable only as far as every finding it cites (decision_impact's own walk of the plan)."""
    from . import access
    from .decision_impact import _walk_evidence_ids
    ids: set[str] = set()
    _walk_evidence_ids(plan, ids)
    if not ids:
        return {"standard"}
    emap = plan.get("_evidence") or {}
    note_ids = [emap[x]["note_id"] for x in ids if isinstance(emap.get(x), dict) and emap[x].get("note_id") is not None]
    floor: set[str] = set().union(*access.note_floors(note_ids).values()) if note_ids else set()
    if len(note_ids) < len(ids):
        floor.add(access.UNCLASSIFIED)        # a citation this can't resolve to a finding has no provable class (§42)
    return floor


def set_item_status(plan_id: str, key: str, status: str, note: str | None = None) -> None:
    with tx() as conn:
        old = conn.execute("SELECT i.status, p.project_id FROM plans p LEFT JOIN plan_items i ON i.plan_id=p.id AND i.key=? WHERE p.id=?",
                           (key, plan_id)).fetchone()
        conn.execute("""INSERT INTO plan_items (plan_id, key, status, note, updated_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(plan_id, key) DO UPDATE SET status=excluded.status,
                        note=COALESCE(excluded.note, plan_items.note), updated_at=excluded.updated_at""",
                     (plan_id, key, status, note, now()))
        if old is not None:
            from . import ledger
            ledger.record(conn, old["project_id"], event_type="plan_item_status_changed", object_type="plan_item",
                          object_id=f"{plan_id}:{key}", before={"status": old["status"] or "not_started"}, after={"status": status},
                          floor={"standard"})


def add_plan_updates(plan_id: str, updates: list[dict[str, Any]], origin: str | None = None) -> None:
    """LP3: `origin` scopes both the clear and the insert, so the LLM-based suggest_updates() path (origin=None)
    and plan_narrative.propose_updates() (origin='lp3') each own their own pending queue on the same plan and
    never clear the other's rows out from under it.

    LP5: each update dict may carry `claim_id`/`tension_id` -- the Claim or tension this proposal traces back to.
    Optional and origin-independent (the LLM-based path has no claim to attach and simply omits them)."""
    with tx() as conn:
        if origin is None:
            conn.execute("DELETE FROM plan_updates WHERE plan_id=? AND status='pending' AND origin IS NULL", (plan_id,))
        else:
            conn.execute("DELETE FROM plan_updates WHERE plan_id=? AND status='pending' AND origin=?", (plan_id, origin))
        conn.executemany(
            "INSERT INTO plan_updates (plan_id, section, previous, proposed, reason, origin, claim_id, tension_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(plan_id, u.get("section", ""), u.get("previous"), u.get("proposed", ""), u.get("reason"), origin,
              u.get("claim_id"), u.get("tension_id"), now()) for u in updates])


def set_update_status(update_id: int, status: str, decided_by: str = "user") -> dict[str, Any] | None:
    """LP5: stamps `decided_at`/`decided_by` the moment a pending row is accepted or rejected -- never on a
    re-read, so a row's provenance reflects the actual decision moment, not whenever it was last fetched."""
    with tx() as conn:
        conn.execute("UPDATE plan_updates SET status=?, decided_at=?, decided_by=? WHERE id=?",
                     (status, now(), decided_by, update_id))
        row = conn.execute("SELECT * FROM plan_updates WHERE id=?", (update_id,)).fetchone()
        return dict(row) if row else None


# --------------------------------------------------------- conversations

def save_message(conversation_id: str, role: str, content: str, citations: list | None = None,
                 title: str | None = None, project_id: str | None = None, meta: dict[str, Any] | None = None) -> int:
    """Returns the new messages.id (CHR0, docs/CHAT-REFRESH-PLAN.md §2): an assistant row records which user row it
    answered, and a later refresh records which assistant row it started from, as REAL ids — never as "the nearest
    timestamp". This is the narrowest seam that makes those relationships stable; nothing else about the write changed."""
    with tx() as conn:
        t = now()
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conversation_id, project_id, title, t, t),
        )
        conn.execute("UPDATE conversations SET updated_at=?, title=COALESCE(title, ?) WHERE id=?", (t, title, conversation_id))
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations, created_at, meta) VALUES (?,?,?,?,?,?)",
            (conversation_id, role, content, json.dumps(citations) if citations is not None else None, t,
             json.dumps(meta) if meta else None),
        )
        return int(cur.lastrowid or 0)


def get_messages(conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = connect().execute(
        "SELECT id, role, content, citations, created_at, meta FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return [row_to_dict(r) for r in reversed(rows)]  # type: ignore[misc]


def conversation_baseline(conversation_id: str) -> dict[str, Any] | None:
    """CHR0: the conversation's last SUCCESSFUL knowledge state — the newest assistant row carrying meta.evidence.
    A failed turn (save_failure: meta.incomplete) or a pre-CHR0 answer has no evidence key and is skipped, so the
    baseline never advances onto a turn that did not finish. None when no row qualifies (a legacy chat: the
    Approximate branch, plan §12, decides what to do with that)."""
    rows = connect().execute(
        "SELECT id, created_at, meta FROM messages WHERE conversation_id=? AND role='assistant' AND meta IS NOT NULL "
        "ORDER BY id DESC LIMIT 50", (conversation_id,)).fetchall()
    for r in rows:
        try:
            meta = json.loads(r["meta"] or "{}")
        except ValueError:
            continue
        ev = meta.get("evidence")
        if isinstance(ev, dict) and not meta.get("incomplete"):
            return {"message_id": int(r["id"]), "answered_at": float(r["created_at"]), "evidence": ev}
    return None


def first_user_message(conversation_id: str) -> str:
    """The question a chat OPENED with — which is not what `get_messages(limit=1)` returns.

    `get_messages` is a tail: `ORDER BY id DESC LIMIT n`, reversed, because a chat view wants the latest turns. The
    0.63.1 retitle backfill asked it for `limit=1` and got the newest message — an assistant reply in 41 of Kyle's
    42 chats — so it found no user message and renamed nothing. The tests did not catch it because a test
    conversation has one message, where the head and the tail are the same row. A title comes from the head, so the
    head gets its own query (0.63.2)."""
    r = connect().execute(
        "SELECT content FROM messages WHERE conversation_id=? AND role='user' AND TRIM(content) <> '' "
        "ORDER BY id ASC LIMIT 1", (conversation_id,)).fetchone()
    return str(r["content"]) if r else ""


def count_messages(conversation_id: str) -> int:
    """0.60.0: how many messages a conversation really has, so a retelling can say what share of it it covers."""
    r = connect().execute("SELECT COUNT(*) n FROM messages WHERE conversation_id=? AND role IN ('user','assistant') "
                          "AND TRIM(content) <> ''", (conversation_id,)).fetchone()
    return int(r["n"] or 0)


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    r = connect().execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return dict(r) if r else None


def conversation_project(conversation_id: str) -> str | None:
    r = connect().execute("SELECT project_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return r["project_id"] if r else None


def list_conversations(project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if project_id:
        rows = connect().execute(
            "SELECT * FROM conversations WHERE project_id=? ORDER BY updated_at DESC LIMIT ?", (project_id, limit)).fetchall()
    else:
        rows = connect().execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def create_conversation(project_id: str | None, title: str | None = None) -> dict[str, Any]:
    cid = new_id()
    with tx() as conn:
        t = now()
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (cid, project_id, title, t, t))
        return dict(conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone())


def rename_conversation(conversation_id: str, title: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now(), conversation_id))


def delete_conversation(conversation_id: str) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))


# ------------------------------------------------------------------ Rung G: batch cohorts (logical work items → provider batch, mapped by custom_id)

# ------------------------------------------------------------------ findings window pre-filter decisions (H1)

def window_decision_get(project_id: str, source_id: str, window_index: int, input_hash: str) -> dict[str, Any] | None:
    r = connect().execute("SELECT * FROM window_decisions WHERE project_id=? AND source_id=? AND window_index=? AND input_hash=?",
                          (project_id, source_id, window_index, input_hash)).fetchone()
    return row_to_dict(r) if r else None


def window_decision_put(d: dict[str, Any]) -> None:
    cols = ("project_id", "source_id", "window_index", "windows", "input_hash", "decision", "reason", "fail_open", "model", "configured_model",
            "prompt_version", "schema_version", "window_chars", "sample_chars", "input_tokens", "output_tokens", "cost")
    with tx() as conn:
        conn.execute(f"INSERT INTO window_decisions ({', '.join(cols)}, created_at) VALUES ({', '.join('?' * len(cols))}, ?) "
                     "ON CONFLICT(project_id, source_id, window_index, input_hash) DO UPDATE SET decision=excluded.decision, reason=excluded.reason, "
                     "fail_open=excluded.fail_open, model=excluded.model, input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens, cost=excluded.cost",
                     (*[d.get(c) for c in cols], now()))


def window_decisions(project_id: str, source_id: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM window_decisions WHERE project_id=?" + (" AND source_id=?" if source_id else "") + " ORDER BY source_id, window_index, created_at"
    return [row_to_dict(r) for r in connect().execute(q, (project_id, source_id) if source_id else (project_id,)).fetchall()]  # type: ignore[misc]


def batch_items_add(job_id: str, cohort_no: int, items: list[dict[str, Any]]) -> None:
    with tx() as conn:
        t = now()
        conn.executemany("INSERT OR IGNORE INTO batch_items (job_id, cohort_no, custom_id, task, project_id, source_id, window_index, windows, params, status, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         [(job_id, cohort_no, it["custom_id"], it["task"], it.get("project_id"), it.get("source_id"), it.get("window_index"), it.get("windows"),
                           json.dumps(it["params"]), "planned", t, t) for it in items])


def batch_coverage(source_id: str, input_hash: str) -> dict[str, Any]:
    """Is there batch work ALREADY BOUGHT for exactly these inputs, still waiting to be collected? (0.62.6)

    `findings.batch_requests` builds a `custom_id` of `fw-<source12>-<window>-<inputhash12>`, so the question is
    answerable from the item table with no new state: the same inputs always produce the same ids.

    **Measured on Kyle's database, 2026-09-10.** 166 sources were analysed TWICE that day at a cost of $22.67, and
    every pair had the same shape: a `local` pass around midday, then a `batch` pass between 15:50 and 16:12 — the
    window in which 410 stranded batches were recovered and settled. Same `brief_revision`, same `facts_revision`,
    same source revision: nothing had changed, so nothing needed re-reading. The batch had been submitted (and
    charged) on Sep 8–9, its results sat uncollected, and in the meantime the ordinary queue read the same sources
    again because `is_current` only ever consulted the analysis ROW. Work in flight was invisible to it.

    Returns `{"covered": bool, "items": n, "waiting": n, "collected": n, "batch_ids": [...]}` — `waiting` is
    submitted and not yet back, `collected` is a result already persisted here but not yet materialised. Either
    means the money is spent and the answer is coming."""
    like = f"fw-{source_id[:12]}-%-{input_hash[:12]}"
    rows = connect().execute(
        "SELECT status, batch_id FROM batch_items WHERE custom_id LIKE ? AND status IN ('submitted','succeeded')",
        (like,)).fetchall()
    waiting = sum(1 for r in rows if r["status"] == "submitted")
    collected = sum(1 for r in rows if r["status"] == "succeeded")
    return {"covered": bool(rows), "items": len(rows), "waiting": waiting, "collected": collected,
            "batch_ids": sorted({r["batch_id"] for r in rows if r["batch_id"]})}


def batch_items(job_id: str, cohort_no: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
    q, args = "SELECT * FROM batch_items WHERE job_id=?", [job_id]
    if cohort_no is not None:
        q += " AND cohort_no=?"; args.append(cohort_no)
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY cohort_no, source_id, window_index"
    out = []
    for r in connect().execute(q, args).fetchall():
        d = row_to_dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        d["raw"] = json.loads(d["raw"]) if d.get("raw") else None
        out.append(d)
    return out


def batch_items_submitted(job_id: str, cohort_no: int, batch_id: str, invocation_ids: dict[str, str]) -> None:
    with tx() as conn:
        t = now()
        for cid, iid in invocation_ids.items():
            conn.execute("UPDATE batch_items SET batch_id=?, invocation_id=?, status='submitted', updated_at=? WHERE job_id=? AND cohort_no=? AND custom_id=?",
                         (batch_id, iid, t, job_id, cohort_no, cid))


def batch_item_result(batch_id: str, custom_id: str, status: str, raw: Any = None, error: str | None = None) -> None:
    """Persist one provider result the moment it is read: Neuro Search's database is authoritative from here on."""
    with tx() as conn:
        conn.execute("UPDATE batch_items SET status=?, raw=?, error=?, updated_at=?, result_at=COALESCE(result_at, ?) "
                     "WHERE batch_id=? AND custom_id=?",
                     (status, json.dumps(raw, default=str) if raw is not None else None, error, now(), now(),
                      batch_id, custom_id))


def work_unit_get(unit_key: str) -> dict[str, Any] | None:
    """Return one completed, content-addressed unit. Malformed legacy data fails closed and is recomputed."""
    row = connect().execute("SELECT * FROM work_units WHERE unit_key=?", (unit_key,)).fetchone()
    if not row:
        return None
    out = dict(row)
    try:
        out["result"] = json.loads(out["result"])
    except (TypeError, ValueError):
        return None
    return out


_work_unit_locks_guard = threading.Lock()
_work_unit_locks: dict[str, tuple[threading.Lock, int]] = {}


@contextmanager
def work_unit_lock(unit_key: str) -> Iterator[None]:
    """Serialize one logical unit inside the single app process; unrelated units remain fully independent."""
    with _work_unit_locks_guard:
        lock, users = _work_unit_locks.get(unit_key, (threading.Lock(), 0))
        _work_unit_locks[unit_key] = (lock, users + 1)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _work_unit_locks_guard:
            current, users = _work_unit_locks.get(unit_key, (lock, 1))
            if current is lock and users <= 1:
                _work_unit_locks.pop(unit_key, None)
            elif current is lock:
                _work_unit_locks[unit_key] = (lock, users - 1)


def work_unit_complete(unit_key: str, *, task: str, project_id: str | None, source_id: str | None,
                       parent_hash: str, unit_index: int, unit_count: int, model: str,
                       prompt_version: str, schema_version: str | None, source_revision: str | None,
                       brief_revision: str | None, facts_revision: str | None, depth: str | None,
                       result: Any) -> None:
    """Commit a provider result immediately. Replays of the same exact unit keep the first durable answer."""
    t = now()
    with tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO work_units (unit_key, task, project_id, source_id, parent_hash, unit_index, "
            "unit_count, model, prompt_version, schema_version, source_revision, brief_revision, facts_revision, "
            "depth, result, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (unit_key, task, project_id, source_id, parent_hash, unit_index, unit_count, model, prompt_version,
             schema_version, source_revision, brief_revision, facts_revision, depth,
             json.dumps(result, sort_keys=True, default=str), t, t),
        )


def work_units_for_parent(task: str, project_id: str, source_id: str, parent_hash: str) -> list[dict[str, Any]]:
    rows = connect().execute(
        "SELECT * FROM work_units WHERE task=? AND project_id=? AND source_id=? AND parent_hash=? ORDER BY unit_index",
        (task, project_id, source_id, parent_hash),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["result"] = json.loads(item["result"])
        except (TypeError, ValueError):
            continue
        out.append(item)
    return out


def batch_items_mark_unsettled(batch_id: str, reason: str) -> int:
    """A batch the provider no longer has: its still-submitted items stop claiming to be in flight, each with the
    reason recorded (0.60.3). Nothing that already succeeded or materialised is touched."""
    with tx() as conn:
        cur = conn.execute("UPDATE batch_items SET status='errored', error=?, updated_at=? "
                           "WHERE batch_id=? AND status='submitted'", (reason[:300], now(), batch_id))
        return int(cur.rowcount or 0)


def batch_items_materialized(job_id: str, source_id: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE batch_items SET status='materialized', updated_at=? WHERE job_id=? AND source_id=? AND status='succeeded'", (now(), job_id, source_id))


def batch_items_for_batch(batch_id: str) -> list[dict[str, Any]]:
    out = []
    for r in connect().execute("SELECT * FROM batch_items WHERE batch_id=? ORDER BY source_id, window_index", (batch_id,)).fetchall():
        d = row_to_dict(r); d["params"] = json.loads(d["params"] or "{}"); d["raw"] = json.loads(d["raw"]) if d.get("raw") else None
        out.append(d)
    return out

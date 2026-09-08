"""SQLite storage: sources, segments, chunks (+FTS5), collections, jobs.

One database file, WAL mode, safe for a single app process with a few worker threads.
"""
from __future__ import annotations

import logging
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np

from .config import settings

FALLBACK_POLICY_VERSION = "fallback-policy-v1"    # mirrored from contracts (db must not import contracts)

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
    source_id        TEXT REFERENCES sources(id) ON DELETE SET NULL,   -- set once acquired: the candidate RESOLVES to the global source
    UNIQUE (platform, external_id)
);
CREATE INDEX IF NOT EXISTS ix_candidates_source ON candidates(source_id);
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
"""

_local = threading.local()


def connect() -> sqlite3.Connection:
    """Thread-local connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(settings.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


MIGRATIONS = [
    ("projects", "context", "ALTER TABLE projects ADD COLUMN context TEXT"),
    ("project_notes", "status", "ALTER TABLE project_notes ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'"),
    ("project_notes", "source_id", "ALTER TABLE project_notes ADD COLUMN source_id TEXT"),
    ("project_notes", "importance", "ALTER TABLE project_notes ADD COLUMN importance INTEGER"),
    ("project_notes", "title", "ALTER TABLE project_notes ADD COLUMN title TEXT"),
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
    ("jobs", "wait_reason", "ALTER TABLE jobs ADD COLUMN wait_reason TEXT"),
    # L1 Local-First AI: intent (execution_policy: local_preferred | local_only | api_requested | api_only) and outcome (executed_by,
    # fallback_reason) are separate columns — a job that meant local and ran on the API says so
    ("jobs", "execution_policy", "ALTER TABLE jobs ADD COLUMN execution_policy TEXT NOT NULL DEFAULT 'local_preferred'"),
    ("jobs", "executed_by", "ALTER TABLE jobs ADD COLUMN executed_by TEXT"),
    ("jobs", "fallback_reason", "ALTER TABLE jobs ADD COLUMN fallback_reason TEXT"),
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
    ("community_syntheses", "coverage", "ALTER TABLE community_syntheses ADD COLUMN coverage TEXT"),   # B2: JSON — partial/unknown threads behind the state         # B2: JSON — captured vs expected, never "complete" by default
    ("project_notes", "batch_id", "ALTER TABLE project_notes ADD COLUMN batch_id TEXT"),
    ("project_source_analysis", "depth", "ALTER TABLE project_source_analysis ADD COLUMN depth TEXT"),   # D2: NULL = ordinary reading, 'deep' = Read deeper
    ("project_source_analysis", "accepted_hash", "ALTER TABLE project_source_analysis ADD COLUMN accepted_hash TEXT"),   # S1: the input hash the user accepted as still usable
    ("project_source_analysis", "accepted_at", "ALTER TABLE project_source_analysis ADD COLUMN accepted_at REAL"),
    ("project_source_analysis", "transport", "ALTER TABLE project_source_analysis ADD COLUMN transport TEXT"),
    ("project_source_analysis", "batch_id", "ALTER TABLE project_source_analysis ADD COLUMN batch_id TEXT"),
    ("usage", "transport", "ALTER TABLE usage ADD COLUMN transport TEXT"),
    ("project_source_analysis", "prefilter", "ALTER TABLE project_source_analysis ADD COLUMN prefilter TEXT"),
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
    conn.commit()
    _migrate_source_analysis(conn)


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


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    if getattr(_local, "batch", 0):      # inside batch(): the batch commits, not each tx
        yield conn
        return
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@contextmanager
def batch() -> Iterator[None]:
    """Group many small writes into one transaction (bulk listings). Keeps the write lock briefly held
    once instead of hundreds of times, so API requests and other workers aren't starved."""
    _local.batch = getattr(_local, "batch", 0) + 1
    try:
        yield
        if _local.batch == 1:
            connect().commit()
    except Exception:
        if _local.batch == 1:
            connect().rollback()
        raise
    finally:
        _local.batch -= 1


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
        else:
            sid = fields.get("id") or new_id()
            fields.update(id=sid, created_at=t, updated_at=t)
            cols = ", ".join(fields)
            qs = ", ".join("?" for _ in fields)
            conn.execute(f"INSERT INTO sources ({cols}) VALUES ({qs})", tuple(fields.values()))
        return row_to_dict(conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())  # type: ignore[return-value]


def get_source(source_id: str) -> dict[str, Any] | None:
    return row_to_dict(connect().execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


def find_source(platform: str, external_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        connect().execute("SELECT * FROM sources WHERE platform=? AND external_id=?", (platform, external_id)).fetchone()
    )


def list_sources(
    *, status: str | None = None, collection_id: str | None = None, query: str | None = None,
    limit: int = 500, offset: int = 0,
) -> list[dict[str, Any]]:
    sql = "SELECT s.* FROM sources s"
    where, args = [], []
    if collection_id:
        sql += " JOIN source_collections sc ON sc.source_id = s.id"
        where.append("sc.collection_id=?"); args.append(collection_id)
    if status:
        where.append("s.status=?"); args.append(status)
    if query:
        where.append("(s.title LIKE ? OR s.channel LIKE ?)"); args += [f"%{query}%", f"%{query}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(s.published_at, '') DESC, s.created_at DESC LIMIT ? OFFSET ?"
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
    with tx() as conn:
        conn.execute("UPDATE sources SET status=?, error=?, updated_at=? WHERE id=?", (status, error, now(), source_id))


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
        conn.execute("UPDATE sources SET revision=?, stage=CASE WHEN ? THEN 'chunks' ELSE 'transcript' END WHERE id=?",
                     (segments_revision(segments), bool(chunks), source_id))
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
    with tx() as conn:
        conn.executemany("UPDATE chunks SET embedding=? WHERE id=?", [(_pack(e), cid) for cid, e in pairs])


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


def list_collections() -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        """SELECT c.*, COUNT(sc.source_id) AS n_sources FROM collections c
           LEFT JOIN source_collections sc ON sc.collection_id = c.id
           GROUP BY c.id ORDER BY c.created_at DESC"""
    ).fetchall()]


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
    if kind == "suggest_findings" and len(payload.get("source_ids") or []) == 1:
        return f"findings:{payload.get('project_id')}:{payload['source_ids'][0]}"
    if kind == "rank_proposed":
        return f"rank:{payload.get('collection_id')}"
    if kind == "build_plan":
        return f"plan:{payload.get('project_id')}"
    if kind == "discover":
        return f"discover:{payload.get('project_id')}:{payload.get('refine') or ''}"
    if kind == "extract_claims":
        return f"claims:{payload.get('project_id')}"
    return None


EXECUTION_POLICIES = ("local_preferred", "local_only", "api_requested", "api_only")


def set_job_policy(job_id: str, policy: str) -> dict[str, Any] | None:
    assert policy in EXECUTION_POLICIES, policy
    with tx() as conn:
        conn.execute("UPDATE jobs SET execution_policy=?, updated_at=? WHERE id=?", (policy, now(), job_id))
        job_event(job_id, "policy", conn=conn, policy=policy)
    return get_job(job_id)


def set_job_execution(job_id: str, executed_by: str | None, fallback_reason: str | None) -> None:
    with tx() as conn:
        conn.execute("UPDATE jobs SET executed_by=?, fallback_reason=? WHERE id=?", (executed_by, fallback_reason, job_id))


def create_job(kind: str, payload: dict, blocked_by: list[str] | None = None, dependency_policy: str = "ALL_SUCCESS",
               dedupe_key: str | None = None, execution_policy: str = "local_preferred") -> dict[str, Any]:
    """blocked_by: job ids that must finish before this one can be claimed (see dependency_policy). dedupe_key (natural
    identity of the work; default from dedupe_key_for) makes a second identical request while the first is still
    active return the existing job instead of a duplicate."""
    assert dependency_policy in DEP_POLICIES, dependency_policy
    key = dedupe_key or dedupe_key_for(kind, payload)
    blocked_by = list(dict.fromkeys(blocked_by)) if blocked_by else None      # de-duplicated, order kept
    with tx() as conn:
        if blocked_by:
            _check_no_cycle(conn, None, blocked_by)
        if key:
            marks = ",".join("?" for _ in JOB_ACTIVE)
            ex = conn.execute(f"SELECT id FROM jobs WHERE dedupe_key=? AND status IN ({marks}) ORDER BY created_at LIMIT 1", (key, *JOB_ACTIVE)).fetchone()
            if ex:
                job_event(ex["id"], "deduplicated", conn=conn, kind=kind)
                return get_job(ex["id"])  # type: ignore[return-value]
        jid = new_id()
        assert execution_policy in EXECUTION_POLICIES, execution_policy
        conn.execute(
            "INSERT INTO jobs (id, kind, payload, created_at, blocked_by, message, dependency_policy, dedupe_key, execution_policy) VALUES (?,?,?,?,?,?,?,?,?)",
            (jid, kind, json.dumps(payload), now(), json.dumps(blocked_by) if blocked_by else None,
             f"waiting for {len(blocked_by)} upstream job{'s' if len(blocked_by) != 1 else ''}" if blocked_by else None, dependency_policy, key, execution_policy),
        )
        job_event(jid, "queued", conn=conn, kind=kind, blocked_by=blocked_by or None, dedupe_key=key)
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


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in connect().execute(  # type: ignore[misc]
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()]


def claim_job(kinds: tuple[str, ...] | None = None, worker_id: str = "worker", lease_seconds: float = LEASE_SECONDS,
              exclude_kinds: tuple[str, ...] | None = None, policies: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    """Atomically claim the oldest claimable queued job: not waiting (not_before), not blocked, not cancelled.
    Claiming takes a lease (worker_id, run_id, lease_until); exactly one worker can win the UPDATE.
    L1 pools: `exclude_kinds` keeps general workers off the AI kinds; `policies` restricts a pool to jobs whose execution_policy is listed."""
    with tx() as conn:
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
        row = None
        for cand in conn.execute(q + " ORDER BY created_at LIMIT 50", args).fetchall():
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
            "UPDATE jobs SET status='running', started_at=?, run_id=?, worker_id=?, claimed_at=?, heartbeat_at=?, lease_until=?, not_before=NULL, wait_reason=NULL "
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
        if j.get("not_before") and j["not_before"] > now():
            return {"budget": "budget_wait", "retry": "retry_wait", "rate_limit": "rate_limit_wait", "provider": "provider_wait"}.get(j.get("wait_reason") or "", "retry_wait")
        return "queued"
    if st == "running" and j.get("cancel_requested_at"):
        return "cancelling"
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
            return "cancelled"
        return r["status"]


def cancel_requested(job_id: str) -> bool:
    r = connect().execute("SELECT cancel_requested_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(r and r["cancel_requested_at"])


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
        return ok


def update_job(job_id: str, *, progress: float | None = None, message: str | None = None,
               status: str | None = None, result: dict | None = None) -> None:
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
    with tx() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", (*args, job_id))


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
            """SELECT s.*, a.relevance AS a_relevance, a.relevance_why AS a_relevance_why
               FROM sources s JOIN source_collections sc ON sc.source_id=s.id
               LEFT JOIN project_source_analysis a ON a.source_id=s.id AND a.project_id=? AND a.analysis_kind='relevance'
               WHERE sc.collection_id=? AND s.status='proposed'
               ORDER BY (a.relevance IS NULL), a.relevance DESC, s.created_at""", (project_id, collection_id)).fetchall():
        d = row_to_dict(r)
        d["relevance"], d["relevance_why"] = d.pop("a_relevance"), d.pop("a_relevance_why")     # the legacy global columns are ignored
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


def upsert_analysis(project_id: str, source_id: str, analysis_kind: str, **fields: Any) -> None:
    """Write one project-relative analysis artifact (one per AI task) with ITS provenance. A fresh write is current."""
    assert analysis_kind in ANALYSIS_KINDS, analysis_kind
    allowed = {"summary", "substance", "relevance", "relevance_why", "model", "provider", "prompt_version", "schema_version",
               "input_hash", "source_revision", "brief_revision", "facts_revision", "status", "transport", "batch_id", "prefilter", "routing", "depth"}
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
        props = proposed_sources(c["id"])
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


def kv_set(key: str, value: str | None) -> None:
    with tx() as conn:
        if value is None:
            conn.execute("DELETE FROM kv WHERE key=?", (key,))
        else:
            conn.execute("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


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
                   "plans", "conversations", "messages", "jobs", "usage", "kv")


def verify_database(path: Path) -> dict[str, Any]:
    """Open a database file read-only and prove it is a usable Neuro Search database: quick_check passes, every
    required table exists, and the main tables can be counted. Raises RuntimeError otherwise."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        qc = conn.execute("PRAGMA quick_check").fetchone()[0]
        if qc != "ok":
            raise RuntimeError(f"quick_check: {qc}")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in REQUIRED_TABLES if t not in have]
        if missing:
            raise RuntimeError(f"missing tables: {', '.join(missing)}")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("sources", "segments", "chunks", "projects", "project_notes", "conversations", "messages", "plans")}
        return {"ok": True, "counts": counts, "bytes": path.stat().st_size}
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
    """quick_check on the live database; result and timestamp are kept in kv for the health view."""
    t = time.time()
    res = connect().execute("PRAGMA quick_check").fetchone()[0]
    fk = connect().execute("PRAGMA foreign_key_check").fetchall()
    info = {"ts": t, "ok": res == "ok" and not fk, "result": res, "foreign_key_violations": len(fk), "seconds": round(time.time() - t, 2)}
    kv_set("db:last_integrity", json.dumps(info))
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
                                                          "rerank_applied", "rerank_fallback", "fetch_blocked")}
    ev["events"] = {r["kind"]: r["n"] for r in conn.execute("SELECT kind, COUNT(*) n FROM validation_events GROUP BY kind").fetchall()}
    try:
        du = _sh.disk_usage(str(settings.data_dir))
        disk = {"free_gb": round(du.free / 1e9, 1), "db_mb": round(settings.db_path.stat().st_size / 1e6, 1)}
    except OSError:
        disk = {}
    inv = invocation_counts()
    return {"db": {"integrity": _j("db:last_integrity"), "path": str(settings.db_path)},
            "invocations": {**inv, "ambiguous": inv.get("outcome_unknown", 0)},
            "backup": {"last_verified": _j("backup:last_verified"), "last_error": _j("backup:last_error")},
            "jobs": {**jobs_by, "stale_running": stale, "expired_leases": stale, "leased": leased,
                     "external_pending": jobs_by.get("external_pending", 0)},
            "structured_outputs": {"mismatches": ev["schema_mismatches"], "mismatches_recovered_by_retry": ev["schema_mismatch_recovered"],
                                   "fallbacks": ev["schema_fallbacks"], "unrecovered": ev["schema_failures"], "truncated": ev["output_truncated"],
                                   "refused": ev["output_refused"], "steady_state": "all zero"},
            "providers": _provider_health(),
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
        with tx() as conn:
            conn.execute(f"UPDATE projects SET {sets} WHERE id=?", (*fields.values(), project_id))
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


def add_project_sources(project_id: str, source_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", [(project_id, s) for s in source_ids])
        conn.executemany("UPDATE project_sources SET excluded=0 WHERE project_id=? AND source_id=? AND excluded=1", [(project_id, s) for s in source_ids])   # an explicit add lifts a removal
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))


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
        conn.executemany("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", [(project_id, s) for s in source_ids])
        conn.executemany("UPDATE project_sources SET excluded=1, priority=0 WHERE project_id=? AND source_id=?", [(project_id, s) for s in source_ids])


def add_project_collections(project_id: str, collection_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("INSERT OR IGNORE INTO project_collections VALUES (?,?)", [(project_id, c) for c in collection_ids])
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))


def remove_project_collections(project_id: str, collection_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("DELETE FROM project_collections WHERE project_id=? AND collection_id=?",
                         [(project_id, c) for c in collection_ids])


def add_project_note(project_id: str, content: str, citations: list | None = None, status: str = "approved",
                     source_id: str | None = None, importance: int | None = None) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO project_notes (project_id, content, citations, created_at, status, source_id, importance) VALUES (?,?,?,?,?,?,?)",
            (project_id, content, json.dumps(citations or []), now(), status, source_id, importance),
        )
        return row_to_dict(conn.execute("SELECT * FROM project_notes WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_project_notes(project_id: str, status: str | None = "approved") -> list[dict[str, Any]]:
    """Approved notes by default (what exports and the planner use). status=None returns all."""
    if status:
        rows = connect().execute("SELECT * FROM project_notes WHERE project_id=? AND status=? ORDER BY importance DESC, created_at DESC",
                                 (project_id, status)).fetchall()
    else:
        rows = connect().execute("SELECT * FROM project_notes WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    return [row_to_dict(r) for r in rows]  # type: ignore[misc]


def set_note_status(note_id: int, status: str) -> dict[str, Any] | None:
    with tx() as conn:
        conn.execute("UPDATE project_notes SET status=?, created_at=CASE WHEN ?='approved' THEN ? ELSE created_at END WHERE id=?",
                     (status, status, now(), note_id))
        return row_to_dict(conn.execute("SELECT * FROM project_notes WHERE id=?", (note_id,)).fetchone())


def replace_suggestions(project_id: str, source_id: str, notes: list[dict[str, Any]], provenance: dict[str, Any] | None = None) -> int:
    """Replace pending suggestions for (project, source); dismissed/approved ones are kept. Every note records the
    model/prompt that wrote it and the brief + source revisions it was written against."""
    prov = provenance or {}
    srev = prov.get("source_revision") or source_revision(source_id)
    brev = prov.get("brief_revision") or brief_revision(project_id)
    with tx() as conn:
        conn.execute("DELETE FROM project_notes WHERE project_id=? AND source_id=? AND status IN ('suggested','reserve')", (project_id, source_id))
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


def update_discovery(disc_id: int, url: str | None = None, start_with: list[dict[str, Any]] | None = None) -> None:
    sets, args = [], []
    if url:
        sets.append("url=?"); args.append(url)
    if start_with:
        sets.append("start_with=?"); args.append(json.dumps(start_with))
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
    with tx() as conn:
        cur = conn.execute("INSERT INTO project_facts (project_id, kind, content, origin, created_at) VALUES (?,?,?,?,?)",
                           (project_id, kind, content, origin, now()))
        return dict(conn.execute("SELECT * FROM project_facts WHERE id=?", (cur.lastrowid,)).fetchone())


def list_facts(project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT * FROM project_facts WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()]


def delete_fact(fact_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM project_facts WHERE id=?", (fact_id,))


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


def set_item_status(plan_id: str, key: str, status: str, note: str | None = None) -> None:
    with tx() as conn:
        conn.execute("""INSERT INTO plan_items (plan_id, key, status, note, updated_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(plan_id, key) DO UPDATE SET status=excluded.status,
                        note=COALESCE(excluded.note, plan_items.note), updated_at=excluded.updated_at""",
                     (plan_id, key, status, note, now()))


def add_plan_updates(plan_id: str, updates: list[dict[str, Any]]) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM plan_updates WHERE plan_id=? AND status='pending'", (plan_id,))
        conn.executemany("INSERT INTO plan_updates (plan_id, section, previous, proposed, reason, created_at) VALUES (?,?,?,?,?,?)",
                         [(plan_id, u.get("section", ""), u.get("previous"), u.get("proposed", ""), u.get("reason"), now()) for u in updates])


def set_update_status(update_id: int, status: str) -> dict[str, Any] | None:
    with tx() as conn:
        conn.execute("UPDATE plan_updates SET status=? WHERE id=?", (status, update_id))
        row = conn.execute("SELECT * FROM plan_updates WHERE id=?", (update_id,)).fetchone()
        return dict(row) if row else None


# --------------------------------------------------------- conversations

def save_message(conversation_id: str, role: str, content: str, citations: list | None = None,
                 title: str | None = None, project_id: str | None = None, meta: dict[str, Any] | None = None) -> None:
    with tx() as conn:
        t = now()
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conversation_id, project_id, title, t, t),
        )
        conn.execute("UPDATE conversations SET updated_at=?, title=COALESCE(title, ?) WHERE id=?", (t, title, conversation_id))
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations, created_at, meta) VALUES (?,?,?,?,?,?)",
            (conversation_id, role, content, json.dumps(citations) if citations is not None else None, t,
             json.dumps(meta) if meta else None),
        )


def get_messages(conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = connect().execute(
        "SELECT role, content, citations, created_at, meta FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return [row_to_dict(r) for r in reversed(rows)]  # type: ignore[misc]


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
        conn.execute("UPDATE batch_items SET status=?, raw=?, error=?, updated_at=? WHERE batch_id=? AND custom_id=?",
                     (status, json.dumps(raw, default=str) if raw is not None else None, error, now(), batch_id, custom_id))


def batch_items_materialized(job_id: str, source_id: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE batch_items SET status='materialized', updated_at=? WHERE job_id=? AND source_id=? AND status='succeeded'", (now(), job_id, source_id))


def batch_items_for_batch(batch_id: str) -> list[dict[str, Any]]:
    out = []
    for r in connect().execute("SELECT * FROM batch_items WHERE batch_id=? ORDER BY source_id, window_index", (batch_id,)).fetchall():
        d = row_to_dict(r); d["params"] = json.loads(d["params"] or "{}"); d["raw"] = json.loads(d["raw"]) if d.get("raw") else None
        out.append(d)
    return out

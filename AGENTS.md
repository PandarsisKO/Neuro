# Codex front door

This file is intentionally short. Do not duplicate Neuro Search architecture or process rules here.

Before changing this repository, read in order:

1. `HANDOFF.md` - working rules, delivery ritual, definition of done
2. `CLAUDE.md` - canonical architecture map and standing engineering rules; the filename does not make it Claude-only
3. `QUALITY-CONTRACT.md` - permanent QA, regression, and repository-hygiene rules
4. newest `STATE-OF-THE-APP-*.md` - current product/repo truth
5. the mission explicitly assigned to you
6. tests that gate the subsystem you will touch

Rules:

- Current code and tests outrank stale historical mission prose.
- Search for an existing implementation before adding a new path.
- Never create parallel ingestion, storage, job, provider, fetch, provenance, cost, research-state, or release infrastructure without explicit architectural approval.
- Never open the live SQLite DB from an external session; follow the safe measurement path in `CLAUDE.md`/`HANDOFF.md`.
- Follow the existing full test/Tier-1/release-check ritual before calling work done.
- Keep changes bounded to the assigned rung and record durable decisions in the repository, not only in chat.

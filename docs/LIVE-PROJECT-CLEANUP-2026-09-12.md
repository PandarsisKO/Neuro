# Live project cleanup — 2026-09-12

## Result

The running app was inspected through its authenticated `/api/projects` endpoint. Ten synthetic fixture projects were removed through `DELETE /api/projects/{project_id}`. Each request returned HTTP 200.

Removed fixture names:

- `G2 api` (2 entries)
- `G2` (2 entries)
- `G2 chat` (2 entries)
- `Article routing` (4 entries)

## Protected projects verified

The cleanup preserved the three user projects that were explicitly protected:

- `I want to start buying businesses and earning "passive" income.`
- `Real Estate Investment Strategy`

The app also still contains `Design beautiful and modern web apps with Claude and chatGPT`. The final live project count is three.

## Method and safety

- Observation and deletion used the running app's authenticated API only.
- The live SQLite database was not opened, copied, or edited.
- No repository files, `data/`, `VIDEOS/`, or `_to_delete/` contents were modified by the cleanup.
- The project delete endpoint is `neurosearch/api.py:1647`; it delegates to the existing `db.delete_project` implementation and returned success for all ten fixture IDs.

This is a live-environment cleanup record for Claude and Codex. It does not change the T1 measurement boundary or authorize the pending billable derived-vector backfill.

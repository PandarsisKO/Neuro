# R9 admission preflight — 2026-09-11

R9 is the next admitted speed rung after the R8 immediate evidence checkpoint. This preflight is intentionally non-invasive: it does not start a model server, download weights, or touch the live database.

The current machine has no `ollama`, `llama-cli`, or `llama-server` executable discoverable on `PATH`, and no standard Ollama model directory was present. Therefore the benchmark scorecard cannot honestly be run yet. The R9 decision remains open rather than being inferred from hardware assumptions.

When a runtime is available, use the three predeclared questions and thresholds in `SPEED-MISSION.md` §R9: embedding latency plus retrieval recall/MRR, short classification latency, and one 15k-token findings/claims prefill-versus-generation measurement. Record both passes and failures in this file and `HARDENING.md`; do not broaden the run into production work or re-embedding until the scorecard is complete.

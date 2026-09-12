# R9 reproducible local benchmark

These probes are disposable and use only the loopback Ollama service plus a temporary Neuro Search database. They never
open or query `data/neurosearch.db`, and they do not change provider routing, production settings, or stored corpus
embeddings.

From the repository root, with Ollama 0.33.3 serving on `127.0.0.1:11434`:

```sh
.venv/bin/python evals/r9/embedding_probe.py --model nomic-embed-text
.venv/bin/python evals/r9/embedding_probe.py --model bge-m3
MODEL=nomic-embed-text .venv/bin/python evals/r9/retrieval_probe.py > /tmp/r9-nomic-retrieval.json
MODEL=bge-m3 .venv/bin/python evals/r9/retrieval_probe.py > /tmp/r9-bge-retrieval.json
for model in llama3.1:8b qwen3:8b qwen3:14b gpt-oss:20b; do
  MODEL="$model" NUM_PREDICT=256 .venv/bin/python evals/r9/classification_probe.py
done
```

The frozen retrieval fixture is `tests/fixtures/golden/retrieval/` (version 1). R9(a) uses three warmups and fifteen
latency samples, then a full thirty-query retrieval run. R9(b) uses the same fixed scheduler item, temperature 0, three
warmups, fifteen samples, a 256-token output cap, and enum-valid JSON as the validity gate. A 64-token exploratory pass
was discarded because it truncated reasoning-model responses before the JSON object.

The admitted 2026-09-12 scorecard is `scorecard-2026-09-12.json`; the narrative decision and the R9(c) benchmark gate
are in `docs/R9-ADMISSION-2026-09-11.md`.

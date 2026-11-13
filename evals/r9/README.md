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
.venv/bin/python evals/r9/long_window_probe.py --model llama3.1:70b
.venv/bin/python evals/r9/long_window_probe.py --model gpt-oss:120b
```

The frozen retrieval fixture is `tests/fixtures/golden/retrieval/` (version 1). R9(a) uses three warmups and fifteen
latency samples, then a full thirty-query retrieval run. R9(b) uses the same fixed scheduler item, temperature 0, three
warmups, fifteen samples, a 256-token output cap, and enum-valid JSON as the validity gate. A 64-token exploratory pass
was discarded because it truncated reasoning-model responses before the JSON object.

The admitted 2026-09-12 scorecard is `scorecard-2026-09-12.json`; the narrative decision and the R9(c) benchmark gate
are in `docs/R9-ADMISSION-2026-09-11.md`.

The long-window probe uses the real `yt03_deal_walkthrough_long.json` fixture, truncates only at the declared character
budget (70,000 by default), sets a 32,768-token context and a 256-token output cap, and reports Ollama's actual
`prompt_eval_count`, `prompt_eval_duration`, `eval_duration`, and `total_duration`. It also records whether the response
is valid JSON with the required `findings` and `claims` arrays. The reported token count is the acceptance evidence;
adjust `--target-chars` and rerun if a model's tokenizer lands materially away from 15,000 tokens.

### Findings, Claims and throughput on the Mac

`research_probe.py` uses the production task prompts and schemas. The Findings
probe runs all eight applicable golden sources through the production
materializer and compares the result with the historical Findings baseline.
The Claims probe checks all 16 candidate IDs, both intended merges, text
qualifiers, requirement attribution, and whether a market quote describes a
single instance. Inspect the proposed evidence targets before admitting a model.

Run the probe from the repository root with the desired Ollama model already
installed. For single-server throughput, start a loopback test server with
`OLLAMA_NUM_PARALLEL=2`. The model architecture may still limit the server to one
slot. Run both throughput arms against the same server with the same context and
keep-alive, and confirm both slots actually ran in the server log. To compare
two independent runners, start a second loopback server and pass
`--second-port`. Both arms unload their models after the measurement.

```sh
PYTHONPATH=. .venv/bin/python evals/r9/research_probe.py gemma4:26b --mode findings --out /tmp/findings.json
PYTHONPATH=. .venv/bin/python evals/r9/research_probe.py gemma4:26b --mode throughput --workers 1 --out /tmp/serial.json
PYTHONPATH=. .venv/bin/python evals/r9/research_probe.py gemma4:26b --mode throughput --workers 2 --out /tmp/parallel.json
```

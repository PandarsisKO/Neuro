#!/usr/bin/env python3
"""R9(a) frozen retrieval run using local Ollama embeddings in a disposable database."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path


MODEL = os.environ.get("MODEL", "nomic-embed-text")
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="neuro-r9-retrieval-"))
os.environ["NEUROSEARCH_DATA_DIR"] = str(TEMP_ROOT)

from neurosearch import db, embeddings, retrieval_eval  # noqa: E402
from neurosearch.config import settings  # noqa: E402


def local_embed(texts: list[str]):
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/embed",
        data=json.dumps({"model": MODEL, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    import numpy as np

    return [np.asarray(vector, dtype=np.float32) / max(float(np.linalg.norm(vector)), 1e-12) for vector in payload["embeddings"]]


embeddings.embed_texts = local_embed
settings.fake_ai = False
db.init_db()
report = retrieval_eval.run(progress=lambda _message: None, label=f"hybrid (FTS + local {MODEL} vectors, RRF)")
report["embeddings"] = {
    "model": MODEL,
    "runtime": "ollama",
    "dimensions": report.get("embeddings", {}).get("dimensions"),
    "fake": False,
}
print(json.dumps(report, indent=2, sort_keys=True, default=str))

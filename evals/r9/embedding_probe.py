#!/usr/bin/env python3
"""R9(a) local Ollama embedding latency probe; no Neuro Search database access."""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request


TEXT = "What debt service coverage ratio do lenders want on a business acquisition loan?"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    def embed() -> tuple[float, int]:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/embed",
            data=json.dumps({"model": args.model, "input": TEXT}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        return time.perf_counter() - started, len(payload["embeddings"][0])

    for _ in range(3):
        embed()
    samples = [embed()[0] for _ in range(15)]
    _, dimensions = embed()
    ordered = sorted(samples)
    print(json.dumps({
        "model": args.model,
        "runtime": "ollama",
        "samples": len(samples),
        "dimensions": dimensions,
        "p50_seconds": round(statistics.median(samples), 6),
        "p90_seconds": round(ordered[round(0.9 * (len(ordered) - 1))], 6),
        "minimum_seconds": round(min(samples), 6),
        "maximum_seconds": round(max(samples), 6),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

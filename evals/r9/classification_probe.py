#!/usr/bin/env python3
"""R9(b) local Ollama classification latency and structured-validity probe."""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request


PROMPT = (
    'Classify this research item for a scheduler. Return JSON only with exactly two keys: "class" '
    '(one of "findings", "claims", "discard") and "priority" (one of "high", "normal", "low"). '
    "Do not explain. Item: A lender requires a debt service coverage ratio above 1.25 and asks for tax returns "
    "before approving an acquisition loan."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--num-predict", type=int, default=256)
    args = parser.parse_args()

    def call() -> tuple[float, bool]:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps({
                "model": args.model,
                "messages": [{"role": "user", "content": PROMPT}],
                "stream": False,
                "options": {"temperature": 0, "num_predict": args.num_predict},
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        elapsed = time.perf_counter() - started
        text = payload.get("message", {}).get("content", "").strip()
        try:
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            obj = json.loads(text)
            valid = obj.get("class") in {"findings", "claims", "discard"} and obj.get("priority") in {"high", "normal", "low"}
        except (TypeError, ValueError, IndexError):
            valid = False
        return elapsed, valid

    for _ in range(3):
        call()
    samples = [call() for _ in range(15)]
    ordered = sorted(elapsed for elapsed, _ in samples)
    print(json.dumps({
        "model": args.model,
        "runtime": "ollama",
        "num_predict": args.num_predict,
        "samples": len(samples),
        "valid_json": sum(1 for _, valid in samples if valid),
        "p50_seconds": round(statistics.median(ordered), 6),
        "p90_seconds": round(ordered[round(0.9 * (len(ordered) - 1))], 6),
        "minimum_seconds": round(min(ordered), 6),
        "maximum_seconds": round(max(ordered), 6),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

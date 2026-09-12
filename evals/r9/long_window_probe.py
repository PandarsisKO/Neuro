#!/usr/bin/env python3
"""R9(c) one-window local extraction timing probe against a disposable fixture file."""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEXT = ROOT / "tests" / "fixtures" / "golden" / "yt03_deal_walkthrough_long.json"
INSTRUCTION = (
    "Extract the most important findings and claims from this transcript window. Return JSON only with keys "
    "findings and claims, each an array of concise strings. Preserve qualifiers, uncertainty, and numbers. "
    "Do not add commentary. Transcript window:\n\n"
)


def transcript_text(path: Path, target_chars: int) -> str:
    payload = json.loads(path.read_text())
    text = "\n".join(str(segment.get("text", "")) for segment in payload.get("segments", []))
    return text[:target_chars]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--text-file", type=Path, default=DEFAULT_TEXT)
    parser.add_argument("--target-chars", type=int, default=70000)
    parser.add_argument("--num-predict", type=int, default=256)
    args = parser.parse_args()

    prompt = INSTRUCTION + transcript_text(args.text_file, args.target_chars)
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 32768, "num_predict": args.num_predict},
        }).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=1800) as response:
        payload = json.load(response)
    wall = time.perf_counter() - started

    def seconds(name: str) -> float | None:
        value = payload.get(name)
        return round(float(value) / 1_000_000_000, 6) if value is not None else None

    content = payload.get("message", {}).get("content", "")
    print(json.dumps({
        "model": args.model,
        "runtime": "ollama",
        "text_file": str(args.text_file.relative_to(ROOT)) if args.text_file.is_relative_to(ROOT) else str(args.text_file),
        "input_chars": len(prompt),
        "target_chars": args.target_chars,
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": payload.get("eval_count"),
        "load_seconds": seconds("load_duration"),
        "prefill_seconds": seconds("prompt_eval_duration"),
        "generation_seconds": seconds("eval_duration"),
        "reported_total_seconds": seconds("total_duration"),
        "wall_seconds": round(wall, 6),
        "response_chars": len(content),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

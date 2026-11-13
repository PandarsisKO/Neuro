#!/usr/bin/env python3
"""Score local models on the existing Findings and synthetic Claims fixtures."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
CLAIMS_FIXTURE = ROOT / "evals/release/chatgpt-plan-synthetic-claims-20261112.json"
FINDINGS_BASELINE = ROOT / "evals/baseline-findings-0.18.0-e2.2-5753ad6-sonnet-4-6.json"


def post(port, endpoint, body, timeout=240):
    req = Request(f"http://127.0.0.1:{port}/api/{endpoint}", json.dumps(body).encode(),
                  {"Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(req, timeout=timeout) as response:
        return json.load(response)


def chat(*, port, model, system, messages, schema, max_tokens, timeout=240, keep_alive=0):
    from neurosearch import schemas

    if isinstance(system, list):
        system = "\n".join(block["text"] for block in system)
    started = time.monotonic()
    raw = post(port, "chat", {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "format": schemas.get(schema),
        "think": False,
        "stream": False,
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0,
            "num_ctx": 32768 if schema == "findings-v2" else 8192,
            "num_predict": max_tokens,
        },
    }, timeout=timeout or 240)
    if raw["model"] != model:
        raise RuntimeError(f"Expected {model}, received {raw['model']}")
    event = {
        "prompt_tokens": raw["prompt_eval_count"],
        "output_tokens": raw["eval_count"],
        "wall_seconds": round(time.monotonic() - started, 2),
        "prefill_seconds": round(raw.get("prompt_eval_duration", 0) / 1e9, 2),
        "generation_seconds": round(raw.get("eval_duration", 0) / 1e9, 2),
        "stop": raw.get("done_reason"),
    }
    print(json.dumps(event), flush=True)
    return raw, event


ATTRIBUTION_PROMPT = """
For qualifiers.imposed_by, use the empty string when a candidate is an observation, reported outcome,
price quote, or hypothesis. A seller's asking price is a quote, not a buyer requirement.
Use lender_policy only when the passage states or describes a rule imposed by a lender. For a
manufacturer's instruction, keep the manufacturer in the claim and use unclear if the enum has
no matching category. Never substitute another kind of authority. For specific_instance, use true
for one source's specific listing, asking price or quote; a price from one supplier is not a market range.
Return every input ID exactly once, including duplicate candidates. Keep their IDs and use merge_into
to point to the retained candidate. Keep dates and constraints in the claim text."""


def claim_group(model, port, group, keep_alive=0, attribution_prompt=False):
    from neurosearch import claims, schemas

    prompt = {
        "brief": group["domain"],
        "goal": f'Evaluate evidence for {group["domain"].lower()}.',
        "questions": [], "existing_topics": [], "existing_targets": [],
        "candidates": group["input"],
    }
    system = claims.SYSTEM + (ATTRIBUTION_PROMPT if attribution_prompt else "")
    raw, event = chat(port=port, model=model, system=system,
                      messages=[{"role": "user", "content": json.dumps(prompt)}],
                      schema="claim-set-v1", max_tokens=5000, keep_alive=keep_alive)
    try:
        output = json.loads(raw["message"]["content"])
    except ValueError:
        return {"domain": group["domain"], "failures": ["invalid JSON"], "event": event}
    failures = schemas.validate("claim-set-v1", output)
    if event["stop"] == "length":
        failures.append("output exceeded the production token limit")
    if not failures:
        rows = output["claims"]
        expected = Counter(candidate["id"] for candidate in group["input"])
        received = Counter(row["id"] for row in rows)
        if received != expected:
            failures.append(f"expected {dict(expected)}, received {dict(received)}")
        merges = [(row["id"], row["merge_into"]) for row in rows if row.get("merge_into")]
        if len(merges) != 1 or set(merges[0]) != set(group["expected_twins"]):
            failures.append(f"wrong merges: {merges}")
        baseline = {row["id"]: row for row in group["result"]["claims"]}
        for row in rows:
            key = row["id"]
            if key not in baseline:
                continue
            text = re.sub(r"[\u2010-\u2015]", "-", re.sub(r"\s+", " ", row["text"]))
            for pattern in group["required_terms"][key]:
                if not re.search(pattern, text, re.IGNORECASE):
                    failures.append(f"{key} missing text pattern {pattern}")
            actual = row["qualifiers"]["imposed_by"]
            expected_imposer = baseline[key]["qualifiers"]["imposed_by"]
            allowed = (expected_imposer,) if expected_imposer else ("", "unclear")
            if actual not in allowed:
                failures.append(f"{key} imposed_by {actual!r}, expected {allowed!r}")
            if baseline[key]["claim_type"] == "market" and row["qualifiers"]["specific_instance"] is not True:
                failures.append(f"{key} lost specific_instance")
    return {"domain": group["domain"], "failures": failures, "event": event, "result": output}


def findings(model, port):
    from neurosearch import contracts, db, evals, ollama, providers
    from neurosearch.config import override

    db.init_db()
    with override(fake_ai=True):
        fixture = evals.load_golden()
    events = []
    original_contract = contracts.contract
    original_create = ollama.create

    def contract(task):
        current = original_contract(task)
        if task == "findings.extract":
            return replace(current, model=model, on_device_model=model, timeout=240)
        return current

    def create(**kwargs):
        raw, event = chat(port=port, **kwargs)
        events.append(event)
        return SimpleNamespace(
            provider="ollama",
            model=raw["model"],
            stop_reason="max_tokens" if event["stop"] == "length" else "end_turn",
            content=[SimpleNamespace(type="text", text=raw["message"]["content"])],
            usage=SimpleNamespace(input_tokens=event["prompt_tokens"], output_tokens=event["output_tokens"]),
            seconds=event["wall_seconds"],
        )

    contracts.contract = contract
    ollama.create = create
    try:
        with override(mac_profiles=True), providers.on_device():
            report = evals.run_findings(fixture["project_id"], fixture["sources"], fixture["manifest"],
                                        force=True, progress=lambda msg: print(msg, flush=True))
    finally:
        contracts.contract = original_contract
        ollama.create = original_create
        db.close_thread_connection()
    baseline = json.loads(FINDINGS_BASELINE.read_text())
    return {"report": report, "comparison": evals.findings_verdict(baseline, report), "events": events}


def throughput(model, ports, groups, workers):
    def keep(port, seconds):
        post(port, "generate", {"model": model, "keep_alive": seconds, "options": {"num_ctx": 8192}})

    preloaded = []
    try:
        for port in dict.fromkeys(ports):
            keep(port, 300)
            preloaded.append(port)
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(claim_group, model, port, group, 300) for port, group in zip(ports, groups)]
            results = [future.result() for future in futures]
        return {"workers": workers, "elapsed": round(time.monotonic() - start, 2), "groups": results}
    finally:
        for port in preloaded:
            keep(port, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--mode", choices=("claims", "findings", "throughput"), required=True)
    parser.add_argument("--port", type=int, default=18444)
    parser.add_argument("--second-port", type=int)
    parser.add_argument("--attribution-prompt", action="store_true", help="Test explicit qualifier instructions in Claims mode")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.attribution_prompt and args.mode != "claims":
        parser.error("--attribution-prompt is only supported in Claims mode")
    ports = (args.port, args.second_port or args.port)
    if any(not 1 <= port <= 65535 for port in ports):
        parser.error("Ollama ports must be between 1 and 65535")

    # Establish isolation before importing Neuro Search.
    with tempfile.TemporaryDirectory(prefix="ns-research-probe-") as data:
        os.environ.update(PYTHON_DOTENV_DISABLED="1", NEUROSEARCH_DATA_DIR=data,
                          NEUROSEARCH_AI_PROFILE="cloud", NEUROSEARCH_FAKE_AI="0")
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            os.environ.pop(key, None)
        groups = json.loads(CLAIMS_FIXTURE.read_text())["groups"]
        if args.mode == "findings":
            report = findings(args.model, args.port)
        elif args.mode == "claims":
            report = {"attribution_prompt": args.attribution_prompt,
                      "groups": [claim_group(args.model, args.port, group, attribution_prompt=args.attribution_prompt)
                                 for group in groups]}
        else:
            report = throughput(args.model, ports, groups, args.workers)
    report["model"] = args.model
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

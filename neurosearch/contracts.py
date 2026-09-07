"""Inference contracts — the Model Router's declarations (hardening ladder, Mission E1).

Every AI task is described here rather than at its call site: provider, configured model, thinking policy, output
budget, transport policy, execution class. Product code asks `providers.invoke(task, ...)`; the contract decides the
request. The initial table reproduces 0.17.3 behaviour EXACTLY (router-equivalence gate) so that a model migration
is a configuration experiment, not a refactor.

configured_model vs returned_model: the contract names a stable identifier (an alias such as `claude-sonnet-5` is
allowed); the ledger and provenance record whatever concrete identifier the provider actually returned.

Overrides for experiments (E2 shadow migration), without touching this file:
    NEUROSEARCH_TASK_MODEL_<TASK>=claude-sonnet-5          e.g. NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT
    NEUROSEARCH_TASK_THINKING_<TASK>=disabled|adaptive
    NEUROSEARCH_TASK_EFFORT_<TASK>=low|medium|high|xhigh|max
    NEUROSEARCH_TASK_MAX_TOKENS_<TASK>=8000
(<TASK> is the task name upper-cased with '.' → '_'.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any

from .config import settings

THINKING = ("disabled", "adaptive")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class InferenceContract:
    task: str
    provider: str                      # anthropic | openai
    model: str                         # configured model (alias allowed); provenance records the returned id
    thinking: str = "disabled"         # disabled | adaptive  (only sent to models that accept it — see adapters)
    effort: str | None = None          # low..max, only with adaptive thinking
    max_output_tokens: int = 4000
    timeout: float | None = None       # SDK default when None
    max_attempts: int = 3              # transport attempts per logical invocation (Neuro Search owns retries)
    backoff: tuple[float, ...] = (1.0, 4.0)
    interactive: bool = False          # user is waiting (latency class)
    batch_allowed: bool = False        # may be routed through a provider batch API (Rung G)
    fallback_allowed: bool = False     # may run on a fallback model/provider (Rung J)
    schema: str | None = None          # registry key in schemas.py → provider-enforced structured output + provenance schema_version; None = free text
    max_output_ceiling: int | None = None   # hard cap for the single truncation escalation (structured tasks); None = no escalation allowed
    quality_floor: float | None = None
    notes: str = ""

    def describe(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["backoff"] = list(self.backoff)
        return d


RANK_MODEL = "claude-sonnet-5"       # rank.relevance production model (E2.1)
FINDINGS_MODEL = "claude-sonnet-5"   # findings.extract production model (E2.2); every other task still follows settings.answer_model


def _m() -> str:
    return settings.answer_model


def _base() -> dict[str, InferenceContract]:
    m = _m()
    return {c.task: c for c in [
        InferenceContract("answer.chat", "anthropic", m, max_output_tokens=2000, max_attempts=2, backoff=(1.0,), interactive=True,
                          notes="RAG chat with project tools; web_search when the user asks"),
        InferenceContract("answer.repair", "anthropic", m, max_output_tokens=2000, max_attempts=2, backoff=(1.0,), interactive=True,
                          notes="one repair round after a citation validation failure"),
        # migrated E2.2 (0.18.0-e2.3): 4.6-vs-5 comparison on the Golden findings workload passed — thinking explicitly off,
        # same prompt (findings-18b5db69), same output budget; baseline + comparison artifacts kept under evals/
        InferenceContract("findings.extract", "anthropic", FINDINGS_MODEL, thinking="disabled", max_output_tokens=4000, max_output_ceiling=6000, batch_allowed=True, schema="findings-v2",
                          notes="per transcript window; quote validator gates the output; Sonnet 5 since E2.2"),
        # migrated E2.1 (0.18.0-e2.2): 4.6-vs-5 comparison on the frozen ranking fixture passed — thinking explicitly off,
        # same prompt (rank-f38f9a9c), same output budget; baseline + comparison artifacts kept under evals/
        InferenceContract("rank.relevance", "anthropic", RANK_MODEL, thinking="disabled", max_output_tokens=6000, max_output_ceiling=9000, batch_allowed=True, schema="rank-v2",
                          notes="Sonnet 5 since E2.1; NEUROSEARCH_TASK_MODEL_RANK_RELEVANCE overrides for experiments"),
        InferenceContract("discover.quick", "anthropic", m, max_output_tokens=3500, max_output_ceiling=5000, timeout=180.0, interactive=True, schema="discovery-v2",
                          notes="structured (F3); discover.verify stays on the citation-capable text/tool path — citations and output_config.format are incompatible"),
        InferenceContract("discover.verify", "anthropic", m, max_output_tokens=2500, timeout=180.0, interactive=True,
                          notes="uses the Anthropic web_search server tool; no fallback provider can serve it"),
        InferenceContract("planner.analysis", "anthropic", m, max_output_tokens=7000, timeout=600.0, interactive=True),
        InferenceContract("planner.build", "anthropic", m, max_output_tokens=16000, timeout=600.0, interactive=True),
        InferenceContract("planner.update", "anthropic", m, max_output_tokens=4000, max_output_ceiling=6000, timeout=600.0, schema="plan-update-v2",
                          notes="structured (F3): a parse failure is a typed failure, never an empty update list"),
        InferenceContract("export.synthesis", "anthropic", m, max_output_tokens=6000),
        InferenceContract("embed", "openai", settings.embedding_model, max_output_tokens=0, backoff=(1.0, 3.0)),
        InferenceContract("transcribe", "openai", settings.transcribe_model, max_output_tokens=0, max_attempts=2, backoff=(2.0,)),
    ]}


def _env(task: str, what: str) -> str | None:
    key = f"NEUROSEARCH_TASK_{what}_{task.upper().replace('.', '_')}"
    v = os.environ.get(key)
    return v.strip() if v else None


def contract(task: str) -> InferenceContract:
    """The contract for a task, with any per-task experiment overrides applied and validated."""
    base = _base()
    c = base.get(task)
    if c is None:
        c = InferenceContract(task, "anthropic", _m())
    over: dict[str, Any] = {}
    if _env(task, "MODEL"):
        over["model"] = _env(task, "MODEL")
    if _env(task, "THINKING"):
        over["thinking"] = _env(task, "THINKING")
    if _env(task, "EFFORT"):
        over["effort"] = _env(task, "EFFORT")
    if _env(task, "MAX_TOKENS"):
        over["max_output_tokens"] = int(_env(task, "MAX_TOKENS"))
    if _env(task, "SCHEMA"):                                    # "none" turns structured output off (rollback/experiment); else a registry key
        over["schema"] = None if _env(task, "SCHEMA").lower() == "none" else _env(task, "SCHEMA")
    c = replace(c, **over) if over else c
    validate(c)
    return c


def all_contracts() -> list[InferenceContract]:
    return [contract(t) for t in _base()]


class ContractError(ValueError):
    pass


def model_family(model: str) -> str:
    m = model.lower()
    if "sonnet-5" in m or "opus-5" in m or "fable-5" in m or "mythos-5" in m:
        return "claude-5"
    if "claude" in m:
        return "claude-4"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return "other"


def validate(c: InferenceContract) -> None:
    """Reject unsupported knobs loudly at contract time — quiet compatibility code is what makes migrations undebuggable."""
    if c.thinking not in THINKING:
        raise ContractError(f"{c.task}: thinking must be one of {THINKING}, got {c.thinking!r}")
    if c.effort is not None and c.effort not in EFFORTS:
        raise ContractError(f"{c.task}: effort must be one of {EFFORTS}, got {c.effort!r}")
    if c.effort is not None and c.thinking != "adaptive":
        raise ContractError(f"{c.task}: effort only applies with thinking='adaptive'")
    fam = model_family(c.model)
    if c.provider == "anthropic" and fam == "claude-4" and c.thinking == "adaptive":
        raise ContractError(f"{c.task}: {c.model} does not support adaptive thinking — use thinking='disabled' or a Claude 5 model")
    if c.provider == "anthropic" and fam == "claude-5" and c.max_output_tokens and c.max_output_tokens < 1024 and c.thinking == "adaptive":
        raise ContractError(f"{c.task}: with adaptive thinking max_output_tokens covers thinking + text; {c.max_output_tokens} is too small")
    if c.max_attempts < 1:
        raise ContractError(f"{c.task}: max_attempts must be ≥ 1")
    if c.max_output_ceiling is not None and c.max_output_ceiling < c.max_output_tokens:
        raise ContractError(f"{c.task}: max_output_ceiling {c.max_output_ceiling} is below max_output_tokens {c.max_output_tokens}")
    if c.schema:
        from . import schemas
        if c.provider != "anthropic":
            raise ContractError(f"{c.task}: structured output schemas are only supported on the anthropic provider")
        try:
            schemas.check_provider_compat(schemas.get(c.schema), c.schema)     # an unsupported schema fails here, never in a paid request
        except schemas.SchemaError as e:
            raise ContractError(f"{c.task}: {e}") from e


def request_params(c: InferenceContract) -> dict[str, Any]:
    """Provider request fields implied by the contract — the adapter for Claude 4 vs Claude 5.
    Claude 4.x: nothing extra (the 0.17.3 request shape, byte for byte).
    Claude 5: thinking is sent explicitly (adaptive is ON by default there, so 'disabled' must be stated), and effort
    goes in output_config. Sampling knobs (temperature/top_p/top_k) are never sent."""
    p: dict[str, Any] = {"max_tokens": c.max_output_tokens} if c.max_output_tokens else {}
    if c.provider == "anthropic" and model_family(c.model) == "claude-5":
        p["thinking"] = {"type": c.thinking}
        if c.effort:
            p["output_config"] = {"effort": c.effort}
    if c.schema and c.provider == "anthropic":
        from . import schemas
        p["output_config"] = {**p.get("output_config", {}), **schemas.output_config(c.schema)}   # provider-enforced shape (GA on 4.6 and 5)
    return p


def forbid_sampling_knobs(kw: dict[str, Any], c: InferenceContract) -> None:
    for k in ("temperature", "top_p", "top_k"):
        if k in kw:
            raise ContractError(f"{c.task}: {k} is not part of the inference contract (Claude 5 rejects non-default values; steer with the prompt instead)")

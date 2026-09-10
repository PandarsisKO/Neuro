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
FALLBACK_POLICIES = ("NO_FALLBACK", "VALIDATED")
FALLBACK_POLICY_VERSION = "fallback-policy-v1"    # recorded on every invocation and every AI artifact; bump when the policy semantics change
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
    # Rung J3 — fallback is an explicit contract INVARIANT. NO_FALLBACK: the requested model is the only model this task
    # may run on; any failure (transient, circuit open, auth, billing, refusal, schema) is a wait or a typed failure —
    # never a substitution. A future VALIDATED policy must name its candidates, prove schema/tools/thinking
    # compatibility, carry task validators and its own quality gate, and record the routing decision in provenance.
    fallback: str = "NO_FALLBACK"      # NO_FALLBACK (the only policy implemented) | VALIDATED (not implemented: rejected at validation)
    fallback_candidates: tuple[str, ...] = ()   # allowed alternate models — must be empty under NO_FALLBACK
    schema: str | None = None          # registry key in schemas.py → provider-enforced structured output + provenance schema_version; None = free text
    max_output_ceiling: int | None = None   # hard cap for the single truncation escalation (structured tasks); None = no escalation allowed
    quality_floor: float | None = None
    notes: str = ""
    # L1: may this task run on the LOCAL provider (Claude Code)? Only structured, single-turn, text-only tasks; streaming,
    # tool-using, embedding, transcription and batch-only tasks stay on their API. The API model stays pinned regardless.
    local_capable: bool = False
    # L1 correction (0.52.0): WHICH model the local provider runs for this task. It used to be
    # `settings.claude_code_model` for every task regardless of the contract — a global .env line silently
    # overriding a per-task, measured model choice. On Kyle's machine that meant `findings.extract`, pinned to
    # Sonnet 5 by the E2.2 comparison, was running on Haiku 4.5 for every local call (59% of them), with nothing
    # recording that it had. None = this contract's own model, so the default is no substitution at all. Declaring
    # a different local model is allowed and is a DECISION: it is recorded on every artifact and reported by
    # `neurosearch contracts` and `doctor`, because a cheaper model chosen deliberately is a legitimate trade and a
    # cheaper model arriving by accident is a silent quality regression.
    local_model: str | None = None
    # ---------------------------------------------------------------- the model decision engine (0.53.0)
    # Kyle: "we need a decision engine of some sort: haiku unless XYZ proven by ABC."
    #
    # THE RULE. Every task runs the CHEAPEST tier (contracts.TIERS, ordered by this repo's own price table),
    # unless the contract names a reason. There are exactly three admissible reasons and no others:
    #
    #   capability:<what>   the cheap tier cannot do what the task needs (a server tool, a schema feature, a
    #                       context length). A fact about the model, not a judgement about quality.
    #   evidence:<path>     a RECORDED comparison showing the cheaper tier failed this task's gate. Cites the
    #                       artifact under evals/ so anyone can re-read the verdict that bought the extra money.
    #   user:<who/why>      the owner looked at the trade and chose to spend. Legitimate — it is their product and
    #                       their judgement is real input — but it is the WEAKEST reason and is labelled as such:
    #                       an opinion, not a measurement, and the comparison would settle it. Recorded with who and
    #                       when so it can never be mistaken later for evidence.
    #   irreversible        the task writes ONCE into the corpus and no comparison exists yet. This is a DEBT,
    #                       not a verdict. It exists because the cost of being wrong is asymmetric: a re-runnable
    #                       task costs one re-run, while a corpus write costs the corpus AND full re-extraction
    #                       across every source — and (0.52.0) nothing can tell afterwards which model wrote what.
    #
    # A contract above the cheapest tier with no reason is a CONFIG ERROR, refused by validate() and by
    # release-check. That refusal is what makes this an engine rather than a comment: the expensive choice has to
    # justify itself in code, every time, or it does not ship.
    # reversible means the CONSEQUENCES are undoable, not that the call is cheap to repeat. rank.relevance is the
    # case that taught the difference (its own frozen tests caught it): re-ranking a collection costs pennies, but
    # by the time you re-rank, the twenty videos it chose are already downloaded, transcribed, embedded and
    # extracted into the corpus. A cheap model that silently decides which 20 of 400 videos become your library is
    # a corpus risk wearing a re-runnable disguise.
    reversible: bool = True            # are this output's CONSEQUENCES undoable without paying for them again?
    gate: str | None = None            # the mechanical check that fails loudly on a bad output (what makes cheap safe)
    tier_reason: str | None = None     # None = cheapest tier; otherwise capability:… | evidence:… | irreversible

    def model_for(self, executed_by: str) -> str:
        return (self.local_model or self.model) if executed_by == "local" else self.model

    def describe(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["backoff"] = list(self.backoff)
        d["fallback_candidates"] = list(self.fallback_candidates)
        d["fallback_policy_version"] = FALLBACK_POLICY_VERSION
        return d


CHEAP = "claude-haiku-4-5"           # the engine's default tier: every task runs here unless its contract names a reason
HELD_MODEL = "claude-sonnet-5"       # where an `irreversible` task waits — the cheapest tier ABOVE the default, which is
                                     # also the newer model that won both live comparisons. A held task must not sit on
                                     # claude-sonnet-4-6: that is dearer ($3/$15 vs $2/$10) AND older, which is drift, not caution.
RANK_MODEL = "claude-sonnet-5"       # rank.relevance production model (E2.1)
FINDINGS_MODEL = "claude-sonnet-5"   # findings.extract production model (E2.2); every other task still follows settings.answer_model
RERANK_MODEL = "claude-haiku-4-5"     # retrieval.rerank (I2 experiment): listwise reorder of the retrieved candidates; env NEUROSEARCH_TASK_MODEL_RETRIEVAL_RERANK
PREFILTER_MODEL = "claude-haiku-4-5"  # findings.prefilter (H1): the cheap conservative rejection filter — NEVER the extractor; env override NEUROSEARCH_TASK_MODEL_FINDINGS_PREFILTER


def _m() -> str:
    return settings.answer_model


def _base() -> dict[str, InferenceContract]:
    m = _m()
    return {c.task: c for c in [
        InferenceContract("answer.chat", "anthropic", HELD_MODEL, tier_reason="user:Kyle 2026-09-09 — the surface he reads most, and the citation validator catches fabrication, not blandness", max_output_tokens=4000, max_attempts=2, backoff=(1.0,), interactive=True,
                          reversible=True, gate="citation-validator (evidence.check_citations) + one repair round",
                          notes="RAG chat with project tools; web_search when the user asks"),
        InferenceContract("answer.repair", "anthropic", HELD_MODEL, tier_reason="user:Kyle 2026-09-09 — a repair REPLACES the whole answer, so it must not be cheaper than the answer it replaces", max_output_tokens=2000, max_attempts=2, backoff=(1.0,), interactive=True,
                          reversible=True, gate="citation-validator re-checks the repaired answer",
                          notes="one repair round after a citation validation failure"),
        # C0 Portable Answers (0.35.1): a shorter version of a FINISHED answer — never a new research pass; only the answer's own
        # citation markers may appear; evidence warnings are re-attached by the caller, never rewritten by the model
        InferenceContract("answer.share", "anthropic", CHEAP, max_output_tokens=1200, max_attempts=2, backoff=(1.0,), interactive=True,
                          reversible=True, gate="markers ⊆ the original's (strays removed and reported)",
                          notes="short/medium rewrite of a finished answer for sharing; markers ⊆ the original's"),
        # migrated E2.2 (0.18.0-e2.3): 4.6-vs-5 comparison on the Golden findings workload passed — thinking explicitly off,
        # same prompt (findings-18b5db69), same output budget; baseline + comparison artifacts kept under evals/
        InferenceContract("findings.extract", "anthropic", FINDINGS_MODEL, local_capable=True, reversible=False,
                          tier_reason="irreversible", gate="quote validator (every quote must appear verbatim in the transcript)", thinking="disabled", max_output_tokens=4000, max_output_ceiling=6000, batch_allowed=True, schema="findings-v2",
                          notes="per transcript window; quote validator gates the output; Sonnet 5 since E2.2"),
        # I2 (0.22.0): candidate-only listwise reranker — one attempt, short timeout, tiny output; any failure → the RRF ordering
        InferenceContract("retrieval.rerank", "anthropic", RERANK_MODEL, thinking="disabled", reversible=True,
                          gate="schema retrieval-rerank-v1; any failure falls back to the RRF ordering", max_output_tokens=120, max_output_ceiling=200, timeout=20.0,
                          max_attempts=1, backoff=(), interactive=True, schema="retrieval-rerank-v1",
                          notes="reorders the top RERANK_DEPTH retrieved chunks; never adds or removes candidates; off unless NEUROSEARCH_RETRIEVAL_RERANK=1"),
        # H1 (0.21.0): window pre-filter — three-way keep/uncertain/drop, fails open; small output, short timeout, no fallback
        InferenceContract("findings.prefilter", "anthropic", PREFILTER_MODEL, thinking="disabled", reversible=True,
                          gate="schema prefilter-v1; any failure → uncertain (fails open)", max_output_tokens=200, max_output_ceiling=300, timeout=60.0,
                          max_attempts=2, backoff=(1.0,), batch_allowed=True, schema="prefilter-v1",
                          notes="conservative rejection filter before findings.extract; any failure → uncertain (fail open); off unless NEUROSEARCH_FINDINGS_PREFILTER=1"),
        # migrated E2.1 (0.18.0-e2.2): 4.6-vs-5 comparison on the frozen ranking fixture passed — thinking explicitly off,
        # same prompt (rank-f38f9a9c), same output budget; baseline + comparison artifacts kept under evals/
        InferenceContract("rank.relevance", "anthropic", RANK_MODEL, local_capable=True, thinking="disabled", max_output_tokens=6000, max_output_ceiling=9000, batch_allowed=True, schema="rank-v2",
                          reversible=False, tier_reason="irreversible", gate="schema rank-v2",
                          notes="Sonnet 5 since E2.1; NEUROSEARCH_TASK_MODEL_RANK_RELEVANCE overrides for experiments"),
        # G4 (0.28.0): project-NEUTRAL "what can this source answer?" — lazy (only for plausible candidates), cached globally,
        # batch-allowed for opportunistic 50% enrichment; never required for library recall
        InferenceContract("library.profile", "anthropic", CHEAP, local_capable=True, thinking="disabled", max_output_tokens=1200, max_output_ceiling=1800, timeout=120.0,
                          reversible=True, gate="schema source-profile-v1; re-derivable per source at one call",
                          max_attempts=2, backoff=(1.0,), batch_allowed=True, schema="source-profile-v1",
                          notes="global source profile (topics, entities, document type, evidence class, temporal character, useful_for); authority = signals with basis, not a verdict"),
        # G5 (0.29.0): claim normalization + proposed evidence targets for a bounded group of $0 candidates; lazy, debounced,
        # idempotent by extraction_hash — never one call per finding
        InferenceContract("claims.extract", "anthropic", HELD_MODEL, local_capable=True, reversible=False,
                          tier_reason="irreversible", gate="schema claim-set-v1; idempotent by extraction_hash", thinking="disabled", max_output_tokens=5000, max_output_ceiling=8000, timeout=240.0,
                          max_attempts=2, backoff=(1.0,), batch_allowed=True, schema="claim-set-v1",
                          notes="normalise candidate Claims (qualifiers, type by evidence requirement, topic, freshness class, merges) + propose evidence targets"),
        InferenceContract("discover.quick", "anthropic", CHEAP, local_capable=True, max_output_tokens=3500, max_output_ceiling=5000, timeout=180.0, interactive=True, schema="discovery-v2",
                          reversible=True, gate="schema discovery-v2; every suggestion is reviewed before anything is acquired",
                          notes="structured (F3); discover.verify stays on the citation-capable text/tool path — citations and output_config.format are incompatible"),
        InferenceContract("discover.verify", "anthropic", CHEAP, max_output_tokens=2500, timeout=180.0, interactive=True,
                          reversible=True, gate="links are verified against the fetched page, never taken on the model's word",
                          notes="uses the Anthropic web_search server tool; no fallback provider can serve it"),
        InferenceContract("planner.analysis", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=7000, timeout=600.0, interactive=True),
        InferenceContract("planner.build", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=16000, timeout=600.0, interactive=True),
        # Planner V3 (F4, behind NEUROSEARCH_PLANNER_V3): one frozen analysis + four semantic components, all structured
        InferenceContract("planner.situation", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=6000, max_output_ceiling=9000, timeout=600.0, interactive=True, schema="situation-v3"),
        InferenceContract("planner.core", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=5000, max_output_ceiling=8000, timeout=600.0, interactive=True, schema="plan-core-v3"),
        InferenceContract("planner.execution", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=6000, max_output_ceiling=9000, timeout=600.0, interactive=True, schema="plan-execution-v3"),
        InferenceContract("planner.economics", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=6000, max_output_ceiling=9000, timeout=600.0, interactive=True, schema="plan-economics-v3"),
        InferenceContract("planner.actions", "anthropic", HELD_MODEL, reversible=True, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", max_output_tokens=5000, max_output_ceiling=8000, timeout=600.0, interactive=True, schema="plan-actions-v3"),
        InferenceContract("planner.update", "anthropic", HELD_MODEL, tier_reason="user:Kyle 2026-09-09 — the flagship deliverable, no mechanical gate, and the saving is under $2/month", local_capable=True, max_output_tokens=4000, max_output_ceiling=6000, timeout=600.0, schema="plan-update-v2",
                          reversible=True, gate="schema plan-update-v2; a parse failure is typed, never an empty update list",
                          notes="structured (F3): a parse failure is a typed failure, never an empty update list"),
        InferenceContract("export.synthesis", "anthropic", CHEAP, max_output_tokens=6000, reversible=True,
                          gate=None),
        InferenceContract("embed", "openai", settings.embedding_model, max_output_tokens=0, backoff=(1.0, 3.0)),
        InferenceContract("transcribe", "openai", settings.transcribe_model, max_output_tokens=0, max_attempts=2, backoff=(2.0,)),
    ]}


def _env(task: str, what: str) -> str | None:
    key = f"NEUROSEARCH_TASK_{what}_{task.upper().replace('.', '_')}"
    v = os.environ.get(key)
    return v.strip() if v else None


# ------------------------------------------------------------------ the tier ladder (a COST ladder, not a capability one)
#
# Ordered by this repo's own prices (usage.PRICES). Note that claude-sonnet-5 is CHEAPER than claude-sonnet-4-6
# ($2/$10 vs $3/$15) while being the newer model that won both live comparisons (E2.1 rank, E2.2 findings). A task
# still on 4.6 is therefore paying more for an older model — which is exactly the kind of drift a decision engine
# exists to make impossible to keep by accident.
TIERS = ("claude-haiku-4-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-opus")
REASON_KINDS = ("capability", "evidence", "irreversible", "user")
REASON_STRENGTH = {"capability": "fact", "evidence": "measured", "irreversible": "debt", "user": "opinion"}


def tier_of(model: str) -> int:
    m = str(model or "")
    for i, t in enumerate(TIERS):
        if m.startswith(t):
            return i
    return len(TIERS)          # unknown model: treated as the most expensive, so it must justify itself


def cheapest() -> str:
    return TIERS[0]


def policy_reason_ok(reason: str | None) -> bool:
    if reason is None:
        return True
    kind = reason.split(":", 1)[0]
    if kind not in REASON_KINDS:
        return False
    if kind == "irreversible":
        return reason == "irreversible"
    return len(reason.split(":", 1)) == 2 and bool(reason.split(":", 1)[1].strip())


def decision(c: InferenceContract) -> dict[str, Any]:
    """What the engine decides for one task, and why — in the words a human would use."""
    at = tier_of(c.model)
    cheap = tier_of(cheapest())
    if c.provider != "anthropic":
        return {"task": c.task, "model": c.model, "verdict": "n/a", "why": f"{c.provider} task — not on the Anthropic tier ladder"}
    if at <= cheap:
        return {"task": c.task, "model": c.model, "verdict": "cheapest",
                "why": "cheapest tier" + (f"; a bad output is caught by {c.gate}" if c.gate else "; no mechanical gate — a bad output is visible to the user, not to the tests")}
    if not c.tier_reason:
        return {"task": c.task, "model": c.model, "verdict": "UNJUSTIFIED",
                "why": f"above the cheapest tier ({cheapest()}) with no recorded reason"}
    kind, _, detail = c.tier_reason.partition(":")
    why = {"capability": f"the cheap tier cannot do what this needs: {detail}",
           "evidence": f"a recorded comparison says the cheap tier fails here: {detail}",
           "irreversible": "writes once into the corpus and has not been compared yet — a debt, not a verdict",
           "user": f"the owner chose to spend here: {detail}"}[kind]
    return {"task": c.task, "model": c.model, "verdict": kind, "strength": REASON_STRENGTH[kind], "why": why,
            "reversible": c.reversible, "gate": c.gate,
            "settled_by": None if kind in ("capability", "evidence") else "a recorded comparison would settle this"}


def policy_report() -> list[dict[str, Any]]:
    return [decision(c) for c in all_contracts()]


def policy_violations() -> list[str]:
    """Contracts spending above the cheapest tier without naming an admissible reason."""
    return _violations_for(all_contracts())


def _violations_for(cs: list[InferenceContract]) -> list[str]:
    bad = []
    for c in cs:
        d = decision(c)
        if d["verdict"] == "UNJUSTIFIED":
            bad.append(f"{c.task}: {c.model} is above {cheapest()} and names no reason")
        elif c.tier_reason and not policy_reason_ok(c.tier_reason):
            bad.append(f"{c.task}: tier_reason {c.tier_reason!r} is not one of {REASON_KINDS}")
        elif c.tier_reason == "irreversible" and c.reversible:
            bad.append(f"{c.task}: claims the 'irreversible' debt but is marked reversible")
    return bad


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


def same_model(configured: str, returned: str | None) -> bool:
    """A returned id is the configured alias or a dated snapshot of it (claude-sonnet-5 → claude-sonnet-5-2026xxxx).
    Lives here so `providers` can check a routing decision without importing the eval machinery."""
    if not returned:
        return True                                  # nothing reported: not evidence of a substitution
    if configured == "fake" or returned.startswith("fake"):
        return True
    return all(r.strip().startswith(configured) for r in returned.split(",") if r.strip())


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
    if c.fallback not in FALLBACK_POLICIES:
        raise ContractError(f"{c.task}: fallback policy must be one of {FALLBACK_POLICIES}, got {c.fallback!r}")
    if c.fallback == "NO_FALLBACK" and c.fallback_candidates:
        raise ContractError(f"{c.task}: NO_FALLBACK contradicts fallback_candidates {list(c.fallback_candidates)}")
    if c.fallback == "VALIDATED":
        raise ContractError(f"{c.task}: VALIDATED fallback is declared but not implemented — it needs candidates, compatibility checks, validators and its own quality gate before it can be enabled")
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

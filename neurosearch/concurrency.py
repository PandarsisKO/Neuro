"""R5 bounded unit execution with explicit parent context propagation."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import os
from typing import Any, Callable, Iterable, TypeVar

from . import db, jobs, logctx, providers

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ParentContext:
    job_id: str | None
    run_id: str | None
    policy: str
    log_fields: dict[str, Any]


def capture_parent() -> ParentContext:
    job_id, run_id = jobs.current_job()
    return ParentContext(job_id, run_id, providers.current_policy(), logctx.get())


def limit_for(task: str) -> int:
    """Small independent bounds for local and paid interactive execution; external batches own their own bound."""
    target, _ = providers.route(task)
    name, default = (("NEUROSEARCH_LOCAL_UNIT_CONCURRENCY", 2) if target == "local"
                     else ("NEUROSEARCH_API_UNIT_CONCURRENCY", 3))
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        value = default
    return max(1, min(value, 4))


def _run(parent: ParentContext, fn: Callable[[T], R], item: T, estimate: Callable[[T], float] | None) -> tuple[bool, Any, tuple[str | None, str | None]]:
    with jobs.bound_current(parent.job_id, parent.run_id), providers.policy_context(parent.policy), logctx.context(**parent.log_fields):
        providers.reset_job_route()
        try:
            if estimate is None:
                value = fn(item)
            else:
                from . import usage
                with usage.reserve(estimate(item)):
                    value = fn(item)
            return True, value, providers.job_route()
        except BaseException as exc:  # returned so the parent can merge routing before re-raising
            return False, exc, providers.job_route()
        finally:
            db.close_thread_connection()


def bounded_map(fn: Callable[[T], R], items: Iterable[T], *, max_workers: int,
                completed: Callable[[int, R], None] | None = None,
                estimate: Callable[[T], float] | None = None) -> list[R]:
    """Run at most ``max_workers`` units and return results in input order.

    Only one bounded wave is admitted at a time. After the first failure, queued futures are cancelled and no new
    unit is submitted. Calls already at the provider safe boundary may finish and persist their durable R4 unit.
    """
    seq = list(items)
    if not seq:
        return []
    if max_workers <= 1 or len(seq) == 1:
        out = []
        for index, item in enumerate(seq):
            value = fn(item)
            out.append(value)
            if completed:
                completed(index, value)
        return out
    parent = capture_parent()
    results: list[Any] = [None] * len(seq)
    next_index = 0
    pending: dict[Future, int] = {}
    first_error: BaseException | None = None
    pool = ThreadPoolExecutor(max_workers=min(max_workers, len(seq)), thread_name_prefix="neuro-unit")
    try:
        while next_index < len(seq) and len(pending) < max_workers:
            pending[pool.submit(_run, parent, fn, seq[next_index], estimate)] = next_index
            next_index += 1
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                ok, value, route = future.result()
                providers.merge_job_route(*route)
                if ok:
                    results[index] = value
                    if completed:
                        completed(index, value)
                elif first_error is None:
                    first_error = value
            if first_error is not None:
                for future in pending:
                    future.cancel()
                done_after_failure, _ = wait(pending)
                for future in done_after_failure:
                    if future.cancelled():
                        continue
                    ok, value, route = future.result()
                    providers.merge_job_route(*route)
                    if ok:
                        index = pending[future]
                        results[index] = value
                        if completed:
                            completed(index, value)
                pending.clear()
                break
            while next_index < len(seq) and len(pending) < max_workers:
                pending[pool.submit(_run, parent, fn, seq[next_index], estimate)] = next_index
                next_index += 1
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if first_error is not None:
        raise first_error
    return results

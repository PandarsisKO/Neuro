"""Fake Message Batches (Rung G). Lives beside fake_ai so the fake's own durable state file (fake_batches.json in the
data dir) is the only thing it ever reads — the fakes must never see eval expectations.

Results are produced by the SAME interactive fake (`_Msgs.create`) so interactive-vs-batch equivalence is real, not
staged; they are returned out of order and mapped by custom_id like the provider does. Knobs:
  NEUROSEARCH_FAKE_BATCH_READY_AFTER=N      the batch ends after N retrieves (default 1)
  NEUROSEARCH_FAKE_BATCH_FAIL_ONCE=a,b       custom_ids containing a substring fail (errored) the FIRST time they are submitted
  NEUROSEARCH_FAKE_BATCH_EXPIRE_ONCE=a,b     same, but as 'expired'
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from .fake_ai import _Blk


def _to_dict(msg: Any) -> Any:
    if isinstance(msg, _Blk):
        return {k: _to_dict(v) for k, v in msg.__dict__.items()}
    if isinstance(msg, list):
        return [_to_dict(i) for i in msg]
    return msg


def _from_dict(d: Any) -> Any:
    if isinstance(d, dict):
        return _Blk(**{k: _from_dict(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_from_dict(x) for x in d]
    return d


class FakeBatches:
    def __init__(self, msgs: Any) -> None:
        self._msgs = msgs

    def _path(self):
        from .config import settings
        return settings.data_dir / "fake_batches.json"

    def _load(self) -> dict[str, Any]:
        p = self._path()
        return json.loads(p.read_text()) if p.exists() else {"batches": {}, "seen": {}}

    def _save(self, d: dict[str, Any]) -> None:
        self._path().write_text(json.dumps(d, default=str))

    def create(self, requests: list[dict[str, Any]], _client_ref: str | None = None, **kw: Any) -> Any:
        d = self._load()
        bid = f"msgbatch_fake{len(d['batches']) + 1:05d}"
        ids = [r["custom_id"] for r in requests]
        assert len(set(ids)) == len(ids), "custom_id must be unique within a batch"
        assert all(len(i) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids), "custom_id: ≤64 chars of [A-Za-z0-9_-]"
        fail = [x for x in os.environ.get("NEUROSEARCH_FAKE_BATCH_FAIL_ONCE", "").split(",") if x]
        expire = [x for x in os.environ.get("NEUROSEARCH_FAKE_BATCH_EXPIRE_ONCE", "").split(",") if x]
        results = []
        for r in requests:                          # results are computed now but only visible once the batch 'ends'
            cid = r["custom_id"]
            first = d["seen"].get(cid, 0) == 0
            d["seen"][cid] = d["seen"].get(cid, 0) + 1
            if first and any(x in cid for x in fail):
                results.append({"custom_id": cid, "result": {"type": "errored", "error": {"type": "api_error", "message": "simulated batch item failure"}}})
            elif first and any(x in cid for x in expire):
                results.append({"custom_id": cid, "result": {"type": "expired"}})
            else:
                msg = self._msgs.create(**r["params"])
                results.append({"custom_id": cid, "result": {"type": "succeeded", "message": _to_dict(msg)}})
        results.reverse()                           # out of order, like the provider
        d["batches"][bid] = {"created_at": time.time(), "client_ref": _client_ref, "checks": 0, "ready_after": int(os.environ.get("NEUROSEARCH_FAKE_BATCH_READY_AFTER", "1")),
                             "cancelled": False, "results": results, "n": len(requests), "results_reads": 0}
        self._save(d)
        return _Blk(id=bid, processing_status="in_progress", request_counts=_Blk(processing=len(requests), succeeded=0, errored=0, canceled=0, expired=0), created_at=d["batches"][bid]["created_at"])

    def _counts(self, b: dict[str, Any]) -> Any:
        c = {"succeeded": 0, "errored": 0, "canceled": 0, "expired": 0, "processing": 0}
        ended = b["cancelled"] or b["checks"] >= b["ready_after"]
        for r in b["results"]:
            t = "canceled" if b["cancelled"] and r["result"]["type"] == "succeeded" and b.get("cancel_drops", 0) else r["result"]["type"]
            c[t if ended else "processing"] += 1
        return _Blk(**c)

    def retrieve(self, batch_id: str) -> Any:
        d = self._load()
        b = d["batches"].get(batch_id)
        if not b:
            raise KeyError(batch_id)
        b["checks"] += 1
        self._save(d)
        ended = b["cancelled"] or b["checks"] >= b["ready_after"]
        return _Blk(id=batch_id, processing_status="ended" if ended else "in_progress", request_counts=self._counts(b), created_at=b["created_at"],
                    cancel_initiated_at=b.get("cancelled_at"))

    def results(self, batch_id: str) -> Any:
        d = self._load()
        b = d["batches"][batch_id]
        assert b["cancelled"] or b["checks"] >= b["ready_after"], "results are only available once the batch has ended"
        b["results_reads"] += 1
        self._save(d)
        for r in b["results"]:
            res = r["result"]
            if b["cancelled"] and res["type"] == "succeeded" and r.get("drop_on_cancel"):
                res = {"type": "canceled"}
            yield _Blk(custom_id=r["custom_id"], result=_Blk(type=res["type"], message=_from_dict(res["message"]) if res["type"] == "succeeded" else None,
                                                             error=_Blk(**res["error"]) if res.get("error") else None))

    def cancel(self, batch_id: str) -> Any:
        d = self._load()
        b = d["batches"][batch_id]
        b["cancelled"] = True; b["cancelled_at"] = time.time()
        # everything after the first KEEP items is 'not yet processed' when cancelled: those become canceled, the prefix
        # stays succeeded (two, so a multi-window source can be among the survivors either way)
        keep = int(os.environ.get("NEUROSEARCH_FAKE_BATCH_KEEP_ON_CANCEL", "2"))
        for i, r in enumerate(b["results"]):
            if i >= keep and r["result"]["type"] == "succeeded":
                r["drop_on_cancel"] = True
        self._save(d)
        return self.retrieve(batch_id)

    def list(self, limit: int = 20, **kw: Any) -> Any:
        d = self._load()
        items = [_Blk(id=bid, processing_status="ended" if (b["cancelled"] or b["checks"] >= b["ready_after"]) else "in_progress", created_at=b["created_at"],
                      request_counts=self._counts(b), _client_ref=b.get("client_ref")) for bid, b in sorted(d["batches"].items(), key=lambda kv: -kv[1]["created_at"])[:limit]]
        return _Blk(data=items)

    def find_by_ref(self, client_ref: str) -> str | None:
        for bid, b in self._load()["batches"].items():
            if b.get("client_ref") == client_ref and not b["cancelled"]:
                return bid
        return None


def _to_dict(msg: Any) -> dict[str, Any]:
    def conv(x: Any) -> Any:
        if isinstance(x, _Blk):
            return {k: conv(v) for k, v in x.__dict__.items()}
        if isinstance(x, list):
            return [conv(i) for i in x]
        return x
    return conv(msg)


def _from_dict(d: Any) -> Any:
    if isinstance(d, dict):
        return _Blk(**{k: _from_dict(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_from_dict(x) for x in d]
    return d



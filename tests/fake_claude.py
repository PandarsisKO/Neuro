"""Compatibility shim: the fake now lives in neurosearch.fake_ai (it is a product feature, NEUROSEARCH_FAKE_AI=1)."""
from neurosearch.fake_ai import PLAN, UPDATES, Anthropic, OpenAI, _Blk, _Msgs, _Stream  # noqa: F401

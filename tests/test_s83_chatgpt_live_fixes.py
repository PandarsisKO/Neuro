"""S83: three failures seen live in ChatGPT on 2026-09-22 (EA-9 9B–F), fixed at the adapter.

1. Files. ChatGPT turns an attachment into {download_url, file_id} only for a parameter published in OpenAI's exact
   "openai/fileParams" shape: an inline object declaring download_url, file_id, mime_type, file_name with only the first
   two required. While `file`/`files` were generic objects, ChatGPT sent a bare "file_…" string and the original was lost.
2. Capabilities. ChatGPT's first open_project sent `file_transport: true`; the strict v1 schema refused the read.
3. Wording. ChatGPT labelled the imperative tool text ("Never…", "Do NOT…", "ONLY…") as "Suspicious Instruction" on
   every write. The rules are enforced by the server, so the published text only describes the interface.
"""
from __future__ import annotations

import asyncio
import json
import re

from neurosearch import mcp_external as m

EXPECTED_FILE = {
    "type": "object",
    "properties": {"download_url": {"type": "string"}, "file_id": {"type": "string"},
                   "mime_type": {"type": "string"}, "file_name": {"type": "string"}},
    "required": ["download_url", "file_id"],
    "additionalProperties": False,
}


def _tools():
    return {t.name: t for t in asyncio.run(m.server.list_tools())}


def test_file_params_are_published_in_openais_exact_shape():
    t = _tools()
    f = dict(t["attach_file"].input_schema["properties"]["file"]); f.pop("description", None)
    assert f == EXPECTED_FILE
    fs = t["sync_conversation_to_project"].input_schema["properties"]["files"]
    assert fs["type"] == "array" and fs["items"] == EXPECTED_FILE
    for name in ("attach_file", "sync_conversation_to_project"):
        assert "$ref" not in json.dumps(t[name].input_schema) and "$defs" not in t[name].input_schema
    assert t["attach_file"].meta == {"openai/fileParams": ["file"]}
    assert t["sync_conversation_to_project"].meta == {"openai/fileParams": ["files"]}


def test_file_param_still_validates_and_maps_to_a_signed_url_ref():
    p = m.FileParam(download_url="https://files.example/x", file_id="file_1", mime_type="text/plain", file_name="q.txt")
    d = m._file_dict(p)
    assert d == {"download_url": "https://files.example/x", "file_id": "file_1", "mime_type": "text/plain", "file_name": "q.txt"}
    assert m._file_dict(m.FileParam(download_url="u", file_id="f")) ["mime_type"] == ""


def test_capabilities_accept_what_chatgpt_actually_sends():
    assert m._caps({"file_transport": True}) == {"file_transport": ["signed_url"]}
    assert m._caps({"file_transport": False}) == {"file_transport": ["none"]}
    assert m._caps({"file_transport": "signed_url"}) == {"file_transport": ["signed_url"]}
    assert m._caps({"file_transport": ["signed_url", "bogus"]}) == {"file_transport": ["signed_url"]}
    assert m._caps({"vision": "true", "unknown_thing": 1}) == {"vision": True}
    assert m._caps(None) is None


def test_published_text_describes_rather_than_commands():
    directive = re.compile(r"\b(NEVER|Never|ONLY|Do NOT|do NOT|MUST|YOU)\b")
    texts = [m.server.instructions or ""] + [t.description or "" for t in _tools().values()]
    offenders = [x[:80] for x in texts if directive.search(x)]
    assert not offenders, offenders

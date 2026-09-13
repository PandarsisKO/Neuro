"""T3 Tier-0 extraction: deterministic, span-preserving and model-free."""

from neurosearch import t3


def _records(text, kind=None):
    rows = t3.extract(text)["records"]
    return [r for r in rows if kind is None or r["kind"] == kind]


def test_t3_extracts_exact_numeric_spans_without_identifier_component_noise():
    text = "The total is $1,200.50, or 12.5 percent, over 3 days and 20 pages."
    rows = t3.extract(text)["records"]
    assert [(r["kind"], r["raw"], text[r["start"]:r["end"]]) for r in rows if r["kind"] in {"money", "percentage", "duration", "unit"}] == [
        ("money", "$1,200.50", "$1,200.50"),
        ("percentage", "12.5 percent", "12.5 percent"),
        ("duration", "3 days", "3 days"),
        ("unit", "20 pages", "20 pages"),
    ]
    assert not _records(text, "number")


def test_t3_reuses_canonical_identifier_normalization_and_preserves_offsets():
    text = "Read SOP 50 10 8, ISBN 978-0-13-468599-1 and DOI 10.1234/ABC-7; then use https://example.com."
    identifiers = _records(text, "identifier")
    assert [r["raw"] for r in identifiers] == ["SOP 50 10 8", "ISBN 978-0-13-468599-1", "10.1234/ABC-7"]
    assert identifiers[0]["attributes"]["scheme"] == "sop"
    assert identifiers[0]["normalized"] == "sop5010"
    assert identifiers[1]["attributes"]["scheme"] == "isbn"
    assert identifiers[1]["normalized"] == "9780134685991"
    assert identifiers[2]["normalized"] == "10.1234/abc-7"
    assert _records(text, "url")[0]["raw"] == "https://example.com"


def test_t3_does_not_promote_phone_shaped_digits_to_isbn():
    assert not _records("Call 215-555-1797 or 2155551797.", "identifier")


def test_t3_sentence_cues_can_overlap_and_are_not_collapsed():
    text = "Is the risk higher than expected? Never skip this step unless approved."
    kinds = {(r["kind"], r["raw"]) for r in t3.extract(text)["records"]}
    assert ("question", "Is the risk higher than expected?") in kinds
    assert ("comparative", "Is the risk higher than expected?") in kinds
    assert ("procedure", "Never skip this step unless approved.") in kinds
    assert ("warning", "Never skip this step unless approved.") in kinds
    assert ("exception", "Never skip this step unless approved.") in kinds


def test_t3_url_trims_sentence_punctuation_and_entity_requires_a_cue():
    text = "See https://example.com/path. Company called OpenAI shipped it. Company called Code Crafters shipped it. OpenAI shipped it."
    assert _records(text, "url")[0]["end"] == text.index(".", text.index("/path"))
    entities = _records(text, "entity")
    assert [r["raw"] for r in entities] == ["OpenAI", "Code Crafters"]
    assert all(r["attributes"]["cue"] == "company called" for r in entities)


def test_t3_output_is_stable_sorted_and_versioned():
    text = "2026-09-13: 5% is less than 10%."
    first = t3.extract(text)
    second = t3.extract(text)
    assert first == second
    assert first["extractor_version"] == t3.EXTRACTOR_VERSION
    keys = [(r["start"], r["end"], r["kind"], r["normalized"]) for r in first["records"]]
    assert keys == sorted(keys)


def test_t3_custom_version_does_not_change_extraction_content():
    text = "Use 4 hours."
    default = t3.extract(text)
    custom = t3.extract(text, extractor_version="future-test")
    assert custom["extractor_version"] == "future-test"
    assert custom["records"] == default["records"]


def test_t3_empty_or_non_text_input_fails_closed():
    assert t3.extract("") == {"extractor_version": t3.EXTRACTOR_VERSION, "records": []}
    assert t3.extract(None)["records"] == []

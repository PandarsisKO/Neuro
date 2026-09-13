"""Tests for pure T3 manifest validation and scoring."""

from neurosearch import t3, t3_review


def _record(text, kind="number", start=0, end=1, normalized="7"):
    return {"kind": kind, "raw": text[start:end], "normalized": normalized, "start": start, "end": end, "attributes": {}}


def test_validate_records_accepts_sorted_exact_half_open_spans():
    text = "7 days"
    records = [_record(text, end=1)]
    assert t3_review.validate_records(text, records) == []


def test_validate_records_catches_raw_offset_duplicate_and_order_errors():
    text = "7 8"
    first = _record(text, end=1)
    duplicate = dict(first)
    bad = _record(text, start=2, end=3, normalized="8")
    bad["raw"] = "wrong"
    assert "record[1] duplicate key" in t3_review.validate_records(text, [first, duplicate, bad])
    assert "record[2] raw does not match text offsets" in t3_review.validate_records(text, [first, duplicate, bad])


def test_score_records_requires_exact_kind_value_and_offsets():
    predicted = [_record("7", normalized="7")]
    gold = [_record("7", normalized="seven")]
    result = t3_review.score_records(predicted, gold)
    assert result["overall"]["tp"] == 0 and result["overall"]["fp"] == 1 and result["overall"]["fn"] == 1


def test_score_manifest_keeps_pending_rows_out_of_metrics():
    text = "7"
    row = {"predicted": [_record(text)], "gold": [_record(text)]}
    pending = {"predicted": [_record(text)], "gold": None}
    result = t3_review.score_manifest([row, pending])
    assert result["labeled_rows"] == 1 and result["pending_rows"] == 1 and result["overall"]["tp"] == 1


def test_extractor_records_validate_through_review_helper():
    text = "Budget $5,000."
    records = t3.extract(text)["records"]
    assert t3_review.validate_records(text, records) == []

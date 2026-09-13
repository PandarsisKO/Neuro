"""Adversarial boundary cases for T3's conservative admission layer."""

from neurosearch import t3


def _rows(text, kind):
    return [r for r in t3.extract(text)["records"] if r["kind"] == kind]


def test_t3_rejects_phone_zip_and_address_fragments_as_identifiers_or_durations():
    text = "Call 215-555-1797, ZIP 18052, or visit 2, Second Street."
    assert not _rows(text, "identifier")
    assert not _rows(text, "duration")


def test_t3_rejects_bare_cues_without_their_admitted_semantics():
    text = "The project has risk, but the result is better. Do the work."
    assert not _rows(text, "warning")
    assert not _rows(text, "exception")
    assert not _rows(text, "question")
    assert _rows(text, "comparative")
    assert _rows(text, "procedure")


def test_t3_numeric_boundaries_do_not_double_count_money_percent_or_duration():
    text = "Budget $12,345.67, margin 12.5%, and a 3.5 hours window."
    assert [(r["kind"], r["raw"]) for r in t3.extract(text)["records"] if r["kind"] in {"money", "percentage", "duration", "number"}] == [
        ("money", "$12,345.67"),
        ("percentage", "12.5%"),
        ("duration", "3.5 hours"),
    ]


def test_t3_number_does_not_capture_decimal_fraction_component():
    rows = _rows("Use a 1.00 scale and 900.", "number")
    assert [r["raw"] for r in rows] == ["1.00", "900"]


def test_t3_identifier_gate_keeps_explicit_isbn_and_rejects_ambiguous_digits():
    text = "ISBN 978-0-13-468599-1; possible book code 0134685991; phone 2155551797."
    rows = _rows(text, "identifier")
    assert len(rows) == 1
    assert rows[0]["raw"] == "ISBN 978-0-13-468599-1"
    assert rows[0]["attributes"]["scheme"] == "isbn"


def test_t3_entity_cue_stops_at_punctuation_and_requires_capitalized_name():
    text = "Company called Beacon Labs. Company called generic tool. Beacon Labs shipped."
    rows = _rows(text, "entity")
    assert [r["raw"] for r in rows] == ["Beacon Labs"]
    assert text[rows[0]["start"] : rows[0]["end"]] == "Beacon Labs"


def test_t3_url_trailing_delimiters_are_outside_the_span():
    text = "Read https://example.com/path), then https://example.org/end;"
    assert [r["raw"] for r in _rows(text, "url")] == [
        "https://example.com/path",
        "https://example.org/end",
    ]


def test_t3_empty_lines_and_markdown_labels_do_not_create_spurious_records():
    text = "\n[Plan: baseline → redesign]\n\n"
    assert t3.extract(text)["records"] == []

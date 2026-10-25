"""Value normalization: the same money, id, date or status reads the same
whether it came from a sentence or a payload field."""

from __future__ import annotations

import pytest

from stoa.detectr.values import Value, extract_values, normalize_number, normalize_status, values_conflict, values_from_payload


def types(text):
    return [(v.type, v.canonical) for v in extract_values(text)]


@pytest.mark.parametrize("raw,expected", [
    ("1,250.50", "1250.5"), ("1.250,50", "1250.5"), ("15.00", "15"), ("150", "150"), ("0.0", "0"),
    ("1 250", "1250"), ("-42.10", "-42.1"), ("abc", None), ("", None),
])
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


def test_money_formats_share_one_canonical_amount():
    for text in ("$150", "150 USD", "USD 150", "$ 150.00", "150 dollars", "€150"):
        found = [v for v in extract_values(text) if v.type == "money"]
        assert found and found[0].canonical == "150", text
    assert extract_values("€1.250,50")[0].extra["currency"] == "EUR"
    assert extract_values("1,250.50 USD")[0].extra["currency"] == "USD"


def test_ids_with_prefixes_and_reference_nouns():
    assert ("id", "APR-4471") in types("approval APR-4471 was granted")
    assert ("id", "8812") in types("a refund on order 8812")
    assert ("id", "4471") in types("ticket #4471")
    assert ("id", "PI_3NKABC12345") in types("charge pi_3NkAbc12345 settled")
    assert ("id", "550E8400-E29B-41D4-A716-446655440000") in types("ref 550e8400-e29b-41d4-a716-446655440000")


def test_dates_durations_and_weekdays():
    assert ("date", "2026-10-24") in types("on 2026-10-24T09:00:00Z")
    assert ("date", "2026-10-24") in types("on 24/10/2026")
    assert ("date", "2026-10-24") in types("on 10/24/2026")
    assert ("date", "2026-10-24") in types("on 24 October 2026") and ("date", "2026-10-24") in types("October 24, 2026")
    ambiguous = extract_values("on 03/04/2026")[0]
    assert ambiguous.canonical == "2026-03-04" and ambiguous.extra["alternate"] == "2026-04-03"
    assert ("duration", "P2D") in types("will arrive in 2 days")
    assert ("duration", "P3BD") in types("within 3 to 5 business days")
    assert ("duration", "PT48H") in types("takes 48 hours")
    assert ("weekday", "friday") in types("by Friday")
    assert ("weekday", "tomorrow") in types("arrives tomorrow")


def test_statuses_fold_synonyms_but_keep_real_differences():
    assert normalize_status("processed") == normalize_status("completed") == "completed"
    assert normalize_status("canceled") == normalize_status("cancelled")
    assert normalize_status("in progress") == "pending"
    assert normalize_status("pending") != normalize_status("processed")
    assert normalize_status("flying") is None


def test_payload_fields_decide_ambiguous_types():
    values = {(v.type, v.canonical, v.field) for v in values_from_payload(
        {"status": "pending", "amount": 15.00, "order_id": 8812, "approval_id": "APR-4471", "eta": "2026-10-28", "count": 3,
         "items": [{"sku": "AB-12", "price": "$9.99"}]})}
    assert ("status", "pending", "status") in values
    assert ("money", "15", "amount") in values
    assert ("id", "8812", "order_id") in values
    assert ("id", "APR-4471", "approval_id") in values
    assert ("date", "2026-10-28", "eta") in values
    assert ("number", "3", "count") in values
    assert ("money", "9.99", "items[0].price") in values
    assert values_from_payload("plain text with $12")[0].canonical == "12"
    assert values_from_payload(None) == []


def test_money_and_numbers_compare_on_one_key():
    said = extract_values("$150")[0]
    returned = values_from_payload({"amount": 150})[0]
    assert said.key() == returned.key()
    assert values_conflict(said, returned) is None
    assert values_conflict(said, values_from_payload({"amount": 15.0})[0]) == "numerical"


def test_conflict_subcategories():
    a, b = Value("id", "APR-4471", "APR-4471"), Value("id", "APR-4472", "APR-4472")
    assert values_conflict(a, b) == "identifier"
    assert values_conflict(Value("status", "completed", "processed"), Value("status", "pending", "pending")) == "status"
    assert values_conflict(Value("date", "2026-10-24", "x"), Value("date", "2026-10-25", "y")) == "temporal"
    assert values_conflict(Value("date", "2026-03-04", "x", extra={"alternate": "2026-04-03"}), Value("date", "2026-04-03", "y")) is None
    assert values_conflict(Value("money", "10", "x", extra={"currency": "USD"}), Value("money", "10", "y", extra={"currency": "EUR"})) == "numerical"
    assert values_conflict(Value("id", "X", "X"), Value("status", "pending", "pending")) is None


def test_negated_sentence_still_yields_values_not_judgements():
    # Value extraction never decides truth; negation is the claim layer's job.
    assert ("id", "4471") in types("I was not able to process the refund for ticket #4471.")


def test_extraction_is_deterministic_and_non_overlapping():
    text = "Refund of $150 for order 8812 (APR-4471) processed on 2026-10-24, arrives in 2 days."
    first = extract_values(text)
    assert first == extract_values(text)
    spans = sorted((v.start, v.end) for v in first)
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))

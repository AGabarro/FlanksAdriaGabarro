import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.parser import ParseResult, parse_csv

SAMPLE = Path(__file__).parent / "data" / "test_data.csv"


@pytest.fixture(scope="module")
def parsed() -> ParseResult:
    with SAMPLE.open(newline="", encoding="utf-8") as handle:
        return parse_csv(handle)


def by_id(result: ParseResult, transaction_id: str):
    return [t for t in result.valid if t.transaction_id == transaction_id]


def only(result: ParseResult, transaction_id: str):
    matches = by_id(result, transaction_id)
    assert len(matches) == 1, f"expected exactly one {transaction_id}"
    return matches[0]


def first(result: ParseResult, transaction_id: str):
    matches = by_id(result, transaction_id)
    assert matches, f"no row with {transaction_id}"
    return matches[0]

def test_every_row_is_either_valid_or_rejected(parsed):
    assert len(parsed.valid) == 11
    assert len(parsed.rejected) == 6
    assert len(parsed.valid) + len(parsed.rejected) == 17


def test_a_missing_column_is_a_file_level_error_not_a_row_level_one():
    broken = io.StringIO("transaction_id,amount\nD2023-05-22N1AxxxSAN,-10.00\n")
    with pytest.raises(ValueError, match="missing required columns"):
        parse_csv(broken)

def test_a_quoted_comma_decimal_is_not_split_into_two_fields(parsed):
    assert first(parsed, "D2023-06-17N14A4bc8cb2SAN").amount == Decimal("-423.48")


def test_a_quoted_thousands_separator_survives(parsed):
    transaction = only(parsed, "D2023-08-10N15A4bc8cb2SAN")
    assert transaction.amount == Decimal("2848.45")
    assert transaction.balance == Decimal("37717.87")


def test_a_comma_inside_a_description_survives(parsed):
    assert only(parsed, "D2023-09-24N27A8e62e4aSAB").description == "Transfer to Maria, rent"

def test_currencies_are_folded_to_iso_codes(parsed):
    assert {t.currency for t in parsed.valid} == {"EUR", "GBP", "USD"}


def test_every_date_layout_in_the_fixture_is_parsed(parsed):
    assert first(parsed, "D2023-06-17N14A4bc8cb2SAN").operation_date == date(2023, 6, 17)
    assert only(parsed, "D2023-08-10N15A4bc8cb2SAN").operation_date == date(2023, 8, 10)
    assert only(parsed, "D2025-08-16N16A4bc8cb2SAN").operation_date == date(2025, 8, 16)
    assert only(parsed, "D2023-09-14N17A8e62e4aSAB").value_date == date(2023, 9, 14)


def test_a_currency_symbol_glued_to_the_amount_is_stripped(parsed):
    assert only(parsed, "D2025-08-16N16A4bc8cb2SAN").amount == Decimal("-22.15")

def test_a_blank_description_is_kept_as_null_not_rejected(parsed):
    assert only(parsed, "D2023-09-16N19A8e62e4aSAB").description is None

def test_a_blank_operation_date_is_recovered_from_the_transaction_id(parsed):
    transaction = only(parsed, "D2023-09-17N20A8e62e4aSAB")
    assert transaction.operation_date == date(2023, 9, 17)
    assert transaction.date_recovered_from_id is True

def test_rows_with_a_real_date_are_not_flagged_as_recovered(parsed):
    assert first(parsed, "D2023-05-22N13A4bc8cb2SAN").date_recovered_from_id is False

def test_rejects_point_at_the_right_line_numbers(parsed):
    assert {r.line for r in parsed.rejected} == {10, 11, 12, 13, 16, 17}


@pytest.mark.parametrize(
    ("line", "expected_reason"),
    [
        (10, "missing amount"),
        (11, "unknown currency"),
        (12, "unparseable date"),
        (13, "unparseable amount"),
        (16, "expected 13 fields, found 3"),
        (17, "missing currency"),
    ],
)
def test_each_reject_carries_a_usable_reason(parsed, line, expected_reason):
    rejected = next(r for r in parsed.rejected if r.line == line)
    assert any(expected_reason in reason for reason in rejected.reasons)


def test_a_malformed_amount_is_reported_as_malformed_not_missing(parsed):
    """The distinction that step 3 found broken: '12..34' is bad data, not a gap."""
    rejected = next(r for r in parsed.rejected if r.line == 13)
    assert not any("missing amount" in reason for reason in rejected.reasons)


def test_a_reject_still_reports_its_transaction_id(parsed):
    rejected = next(r for r in parsed.rejected if r.line == 11)
    assert rejected.transaction_id == "D2023-09-19N22A8e62e4aSAB"

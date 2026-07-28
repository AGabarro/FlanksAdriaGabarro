from datetime import date
from decimal import Decimal

import pytest

from app.normalize import (
    date_from_transaction_id,
    normalize_currency,
    parse_amount,
    parse_date,
)

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EUR", "EUR"),
        ("€", "EUR"),
        ("eur", "EUR"),
        ("Euro", "EUR"),
        ("GBP", "GBP"),
        ("USD", "USD"),
        ("usd", "USD"),
        ("£", "GBP"),
        ("US$", "USD"),
    ],
)
def test_normalize_currency_folds_every_real_spelling(raw, expected):
    assert normalize_currency(raw) == expected


def test_normalize_currency_tolerates_surrounding_whitespace():
    assert normalize_currency("  eur  ") == "EUR"


@pytest.mark.parametrize("raw", ["", "   "])
def test_normalize_currency_blank_is_absent_not_an_error(raw):
    assert normalize_currency(raw) is None


def test_normalize_currency_rejects_unknown_code():
    with pytest.raises(ValueError, match="unknown currency"):
        normalize_currency("BTC")


def test_error_message_names_the_offending_value():
    with pytest.raises(ValueError, match="BTC"):
        normalize_currency("BTC")

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-467.62", Decimal("-467.62")),
        ("-423,48", Decimal("-423.48")),
        ("37,717.87", Decimal("37717.87")),
        ("21606,88", Decimal("21606.88")),
        ("-€22.15", Decimal("-22.15")),
        ("€2554.54", Decimal("2554.54")),
        ("-999,9", Decimal("-999.9")),
        ("-9999", Decimal("-9999")),
        ("2,848.45", Decimal("2848.45")),
    ],
)
def test_parse_amount_handles_every_real_format(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_amount_keeps_the_sign_when_a_symbol_follows_it():
    assert parse_amount("-€22.15") < 0


@pytest.mark.parametrize("raw", ["", "   "])
def test_parse_amount_blank_is_absent_not_an_error(raw):
    assert parse_amount(raw) is None


@pytest.mark.parametrize("raw", ["abc", "-", "€", "EUR", "12..34"])
def test_parse_amount_rejects_values_with_no_parseable_number(raw):
    with pytest.raises(ValueError, match="unparseable amount"):
        parse_amount(raw)


def test_parse_amount_returns_decimal_not_float():
    assert isinstance(parse_amount("-467.62"), Decimal)


def test_parse_amount_arithmetic_is_exact():
    assert parse_amount("0.10") + parse_amount("0.20") == Decimal("0.30")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2023-05-22", date(2023, 5, 22)),   # real: ISO, the majority
        ("17/06/2023", date(2023, 6, 17)),   # real: day-first with slashes
        ("10-08-2023", date(2023, 8, 10)),   # real: day-first with dashes
        ("Aug 16 2025", date(2025, 8, 16)),  # real: abbreviated month name
        ("2023/09/14", date(2023, 9, 14)),   # real: ISO with slashes (value_date)
    ],
)
def test_parse_date_handles_every_real_format(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10-08-2023", date(2023, 8, 10)),
        ("06/07/2023", date(2023, 7, 6)),
    ],
)
def test_parse_date_is_day_first_where_both_readings_are_valid(raw, expected):
    """The only genuinely ambiguous case: both components <= 12. Day-first is not
    a guess -- in the file the first component reaches 31 while the second never
    exceeds 12, so month-first is impossible."""
    assert parse_date(raw) == expected


def test_parse_date_does_not_let_iso_swallow_a_day_first_value():
    """Guards the ordering of _DATE_FORMATS: '%Y-%m-%d' is tried first, and must
    fail on '10-08-2023' (it would read day=2023) rather than mis-parse it."""
    assert parse_date("10-08-2023").year == 2023


@pytest.mark.parametrize("raw", ["", "   "])
def test_parse_date_blank_is_absent_not_an_error(raw):
    assert parse_date(raw) is None


@pytest.mark.parametrize("raw", ["not a date", "32/01/2023", "2023-13-01", "22-05"])
def test_parse_date_rejects_impossible_dates(raw):
    with pytest.raises(ValueError, match="unparseable date"):
        parse_date(raw)

def test_date_from_transaction_id_extracts_the_encoded_date():
    assert date_from_transaction_id("D2023-05-22N13A4bc8cb2SAN") == date(2023, 5, 22)


def test_date_from_transaction_id_tolerates_a_single_digit_sequence():
    """Both 'N13A' and 'N3A' occur in the file."""
    assert date_from_transaction_id("D2024-06-09N6A9c9c3d9SAN") == date(2024, 6, 9)


@pytest.mark.parametrize(
    "transaction_id",
    [
        "",
        "NOT-AN-ID",
        "D2023-02-30N1Ax5f2a1bSAN",
    ],
)
def test_date_from_transaction_id_returns_none_instead_of_raising(transaction_id):
    assert date_from_transaction_id(transaction_id) is None

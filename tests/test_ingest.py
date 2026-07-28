from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import String, select

from app import models
from app.db import create_all, reset_engine, session_scope
from app.ingest import ingest_file
from app.parser import parse_csv

SAMPLE = Path(__file__).parent / "data" / "test_data.csv"
REAL_CSV = Path(__file__).parents[1] / "data" / "flanks_test_transactions.csv"


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    reset_engine()
    create_all()
    yield
    reset_engine()


@pytest.fixture
def report(database):
    return ingest_file(SAMPLE)


def stored_transactions() -> list[models.Transaction]:
    with session_scope() as session:
        return list(session.scalars(select(models.Transaction)))

def test_every_row_is_accounted_for(report):
    assert report.total_rows == 17
    assert report.inserted == 9
    assert report.exact_duplicates == 1
    assert report.conflicting_duplicates == 1
    assert report.rejected == 6
    assert report.accounted_for() == report.total_rows


def test_the_database_holds_exactly_the_inserted_rows(report):
    assert len(stored_transactions()) == report.inserted


def test_accounts_are_derived_from_the_transactions(report):
    assert report.accounts_upserted == 2
    with session_scope() as session:
        accounts = list(session.scalars(select(models.Account)))
    assert {a.account_id for a in accounts} == {"A4bc8cb2", "A8e62e4a"}
    assert {a.entity for a in accounts} == {"santander", "sabadell"}


def test_dates_recovered_are_counted_not_hidden(report):
    assert report.dates_recovered == 1


def test_conflicting_duplicates_are_named_in_the_report(report):
    assert report.conflicting_ids == ("D2023-06-17N14A4bc8cb2SAN",)


def test_first_seen_wins_for_a_conflicting_duplicate(report):
    with session_scope() as session:
        transaction = session.get(models.Transaction, "D2023-06-17N14A4bc8cb2SAN")
    assert transaction.amount == Decimal("-423.48")


def test_an_exact_duplicate_is_skipped_without_being_flagged(report):
    assert report.exact_duplicates == 1
    assert "D2023-05-22N13A4bc8cb2SAN" not in report.conflicting_ids


def test_only_one_row_per_transaction_id_reaches_the_database(report):
    ids = [t.transaction_id for t in stored_transactions()]
    assert len(ids) == len(set(ids))


def test_every_rejected_row_carries_its_reasons(report):
    reasons = [reason for row in report.rejected_rows for reason in row.reasons]
    assert "missing amount" in reasons
    assert "missing currency" in reasons
    assert all(row.reasons for row in report.rejected_rows)


def test_rejected_rows_keep_their_line_numbers(report):
    assert {row.line for row in report.rejected_rows} == {10, 11, 12, 13, 16, 17}


def test_rejected_rows_are_not_persisted(report):
    stored = {t.transaction_id for t in stored_transactions()}
    assert "D2023-09-19N22A8e62e4aSAB" not in stored  # unknown currency BTC


def test_a_second_ingest_inserts_nothing_and_says_so(report):
    second = ingest_file(SAMPLE)
    assert second.inserted == 0
    assert second.already_present == 9
    assert second.accounted_for() == second.total_rows
    assert len(stored_transactions()) == 9


def test_normalisation_reaches_the_stored_row(report):
    with session_scope() as session:
        transaction = session.get(models.Transaction, "D2023-08-10N15A4bc8cb2SAN")
    assert transaction.amount == Decimal("2848.45")
    assert transaction.balance == Decimal("37717.87")
    assert transaction.currency == "EUR"


def test_the_report_renders_without_blowing_up(report):
    rendered = report.render()
    assert "transactions inserted    9" in rendered
    assert "D2023-06-17N14A4bc8cb2SAN" in rendered


def _overflowing_columns(table, records) -> list[str]:
    limits = {
        column.name: column.type.length
        for column in table.columns
        if isinstance(column.type, String) and column.type.length
    }
    return [
        f"{name}: needs {len(value)}, column allows {limit}"
        for record in records
        for name, limit in limits.items()
        if isinstance(value := getattr(record, name, None), str) and len(value) > limit
    ]


def test_declared_column_widths_fit_the_real_file():
    with REAL_CSV.open(newline="", encoding="utf-8") as handle:
        parsed = parse_csv(handle)

    assert _overflowing_columns(models.Transaction.__table__, parsed.valid) == []
    assert _overflowing_columns(models.Account.__table__, parsed.valid) == []

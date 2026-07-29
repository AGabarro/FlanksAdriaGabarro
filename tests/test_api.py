from decimal import Decimal

from app.ingest import ingest_file
from tests.conftest import SAMPLE

SANTANDER = "A4bc8cb2"  # 4 transactions, all EUR
SABADELL = "A8e62e4a"  # 5 transactions: 3 EUR, 1 GBP, 1 USD

def test_filtering_by_account_returns_only_that_account(client):
    rows = client.get("/transactions", params={"account_id": SANTANDER}).json()
    assert len(rows) == 4
    assert {row["account_id"] for row in rows} == {SANTANDER}


def test_the_date_range_is_inclusive_at_both_ends(client):
    rows = client.get(
        "/transactions",
        params={"account_id": SABADELL, "from": "2023-09-14", "to": "2023-09-16"},
    ).json()
    assert [row["operation_date"] for row in rows] == [
        "2023-09-14",
        "2023-09-15",
        "2023-09-16",
    ]


def test_money_is_serialised_as_a_string_so_no_cent_is_lost(client):
    rows = client.get("/transactions", params={"account_id": SANTANDER}).json()
    amount = next(r["amount"] for r in rows if r["transaction_id"].startswith("D2023-06-17"))
    assert amount == "-423.48"
    assert isinstance(amount, str)


def test_an_unknown_account_is_404(client):
    assert client.get("/transactions", params={"account_id": "nope"}).status_code == 404


def test_a_known_account_with_nothing_in_range_is_an_empty_list(client):
    response = client.get(
        "/transactions",
        params={"account_id": SANTANDER, "from": "1990-01-01", "to": "1990-12-31"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_a_reversed_date_range_is_rejected(client):
    response = client.get("/transactions", params={"from": "2024-01-01", "to": "2023-01-01"})
    assert response.status_code == 400


def test_a_mixed_currency_account_gets_one_row_per_currency(client):
    """No FX rate is invented, so three currencies stay three rows."""
    body = client.get("/transactions/summary", params={"account_id": SABADELL}).json()
    assert [t["currency"] for t in body["totals"]] == ["EUR", "GBP", "USD"]


def test_balance_always_equals_credits_plus_debits(client):
    body = client.get("/transactions/summary").json()
    for total in body["totals"]:
        assert Decimal(total["credits"]) + Decimal(total["debits"]) == Decimal(
            total["balance"]
        )


def test_the_second_identical_summary_request_is_a_cache_hit(client):
    first = client.get("/transactions/summary", params={"account_id": SABADELL})
    second = client.get("/transactions/summary", params={"account_id": SABADELL})
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()


def test_ingesting_again_invalidates_the_cache(client):
    client.get("/transactions/summary", params={"account_id": SABADELL})
    assert client.get(
        "/transactions/summary", params={"account_id": SABADELL}
    ).headers["X-Cache"] == "HIT"

    ingest_file(SAMPLE)

    assert client.get(
        "/transactions/summary", params={"account_id": SABADELL}
    ).headers["X-Cache"] == "MISS"

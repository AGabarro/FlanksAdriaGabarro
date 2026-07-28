import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, TextIO

from app.normalize import (
    date_from_transaction_id,
    normalize_currency,
    parse_amount,
    parse_date,
)

COLUMNS = (
    "transaction_id",
    "account_id",
    "entity",
    "iban",
    "balance",
    "amount",
    "currency",
    "category",
    "category_code",
    "transaction_type",
    "operation_date",
    "value_date",
    "description",
)

_EXTRA_FIELDS = "__extra__"


@dataclass(frozen=True, slots=True)
class Transaction:
    transaction_id: str
    account_id: str
    entity: str | None
    iban: str | None
    operation_date: date
    value_date: date | None
    amount: Decimal
    currency: str
    balance: Decimal | None
    description: str | None
    category: str | None
    category_code: str | None
    transaction_type: str | None
    date_recovered_from_id: bool


@dataclass(frozen=True, slots=True)
class RejectedRow:
    line: int
    transaction_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParseResult:
    valid: list[Transaction]
    rejected: list[RejectedRow]


def parse_csv(stream: TextIO) -> ParseResult:
    reader = csv.DictReader(stream, restkey=_EXTRA_FIELDS, restval=None)
    missing = set(COLUMNS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    result = ParseResult(valid=[], rejected=[])
    for row in reader:
        transaction, reasons = _parse_row(row)
        if transaction is not None:
            result.valid.append(transaction)
        else:
            result.rejected.append(
                RejectedRow(
                    line=reader.line_num,
                    transaction_id=(row.get("transaction_id") or "").strip(),
                    reasons=tuple(reasons),
                )
            )
    return result


def _parse_row(row: dict[str, str | None]) -> tuple[Transaction | None, list[str]]:
    field_count_error = _check_field_count(row)
    if field_count_error:
        return None, [field_count_error]

    text = {column: (row[column] or "").strip() for column in COLUMNS}
    reasons: list[str] = []

    def normalized[T](fn: Callable[[str], T | None], column: str) -> T | None:
        try:
            return fn(text[column])
        except ValueError as exc:
            reasons.append(str(exc))
            return None

    amount = normalized(parse_amount, "amount")
    balance = normalized(parse_amount, "balance")
    currency = normalized(normalize_currency, "currency")
    operation_date = normalized(parse_date, "operation_date")
    value_date = normalized(parse_date, "value_date")

    transaction_id = text["transaction_id"]
    if not transaction_id:
        reasons.append("missing transaction_id")
    if not text["account_id"]:
        reasons.append("missing account_id")
    if amount is None and not text["amount"]:
        reasons.append("missing amount")
    if currency is None and not text["currency"]:
        reasons.append("missing currency")

    date_recovered_from_id = False
    if operation_date is None and not text["operation_date"]:
        operation_date = date_from_transaction_id(transaction_id)
        date_recovered_from_id = operation_date is not None
        if operation_date is None:
            reasons.append("missing operation_date, and none encoded in transaction_id")

    if reasons:
        return None, reasons

    assert amount is not None and currency is not None and operation_date is not None
    return (
        Transaction(
            transaction_id=transaction_id,
            account_id=text["account_id"],
            entity=text["entity"] or None,
            iban=text["iban"] or None,
            operation_date=operation_date,
            value_date=value_date,
            amount=amount,
            currency=currency,
            balance=balance,
            description=text["description"] or None,
            category=text["category"] or None,
            category_code=text["category_code"] or None,
            transaction_type=text["transaction_type"] or None,
            date_recovered_from_id=date_recovered_from_id,
        ),
        [],
    )


def _check_field_count(row: dict[str, str | None]) -> str | None:
    if row.get(_EXTRA_FIELDS) is not None:
        surplus = len(row[_EXTRA_FIELDS])
        return f"expected {len(COLUMNS)} fields, found {len(COLUMNS) + surplus}"
    absent = [column for column in COLUMNS if row.get(column) is None]
    if absent:
        return f"expected {len(COLUMNS)} fields, found {len(COLUMNS) - len(absent)}"
    return None

from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from app import models
from app.cache import summary_cache
from app.db import create_all, session_scope


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(
    title="Flanks transactions API",
    description="Reads the normalised transactions loaded by `python -m app.ingest`.",
    lifespan=lifespan,
)


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    account_id: str
    operation_date: date
    value_date: date | None
    amount: Decimal
    currency: str
    balance: Decimal | None
    description: str | None
    category: str | None
    category_code: str | None
    transaction_type: str | None


def _require_known_account(session: Session, account_id: str | None) -> None:
    if account_id is not None and session.get(models.Account, account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account_id {account_id!r}")


def _validated_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400, detail=f"'from' ({date_from}) is after 'to' ({date_to})"
        )


def _filters(
    account_id: str | None, date_from: date | None, date_to: date | None
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if account_id is not None:
        conditions.append(models.Transaction.account_id == account_id)
    if date_from is not None:
        conditions.append(models.Transaction.operation_date >= date_from)
    if date_to is not None:
        conditions.append(models.Transaction.operation_date <= date_to)
    return conditions


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    session: SessionDep,
    account_id: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[models.Transaction]:
    _validated_range(date_from, date_to)
    _require_known_account(session, account_id)

    query = (
        select(models.Transaction)
        .where(*_filters(account_id, date_from, date_to))
        .order_by(models.Transaction.operation_date, models.Transaction.transaction_id)
    )
    return list(session.scalars(query))


class CurrencyTotals(BaseModel):
    currency: str
    transactions: int
    credits: Decimal
    debits: Decimal
    balance: Decimal
    latest_reported_balance: Decimal | None
    latest_operation_date: date | None


class SummaryOut(BaseModel):
    account_id: str | None
    totals: list[CurrencyTotals]


def _totals_by_currency(session: Session, conditions: list[ColumnElement[bool]]):
    credited = func.sum(case((models.Transaction.amount > 0, models.Transaction.amount)))
    debited = func.sum(case((models.Transaction.amount < 0, models.Transaction.amount)))

    query = (
        select(
            models.Transaction.currency,
            func.count().label("transactions"),
            func.coalesce(credited, 0).label("credits"),
            func.coalesce(debited, 0).label("debits"),
            func.sum(models.Transaction.amount).label("balance"),
        )
        .where(*conditions)
        .group_by(models.Transaction.currency)
        .order_by(models.Transaction.currency)
    )
    return session.execute(query).all()


def _latest_reported_balances(
    session: Session, conditions: list[ColumnElement[bool]]
) -> dict[str, tuple[Decimal | None, date | None]]:
    ranked = (
        select(
            models.Transaction.currency,
            models.Transaction.balance,
            models.Transaction.operation_date,
            func.row_number()
            .over(
                partition_by=models.Transaction.currency,
                order_by=(
                    models.Transaction.operation_date.desc(),
                    models.Transaction.transaction_id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(*conditions)
        .subquery()
    )
    rows = session.execute(
        select(ranked.c.currency, ranked.c.balance, ranked.c.operation_date).where(
            ranked.c.rank == 1
        )
    ).all()
    return {row.currency: (row.balance, row.operation_date) for row in rows}


@app.get("/transactions/summary", response_model=SummaryOut)
def summarise_transactions(
    session: SessionDep,
    response: Response,
    account_id: Annotated[str | None, Query()] = None,
) -> SummaryOut:
    _require_known_account(session, account_id)

    summary, was_hit = summary_cache.get_or_compute(
        account_id, lambda: _compute_summary(session, account_id)
    )
    response.headers["X-Cache"] = "HIT" if was_hit else "MISS"
    return summary


def _compute_summary(session: Session, account_id: str | None) -> SummaryOut:
    conditions = _filters(account_id, None, None)
    latest = _latest_reported_balances(session, conditions)

    totals = []
    for row in _totals_by_currency(session, conditions):
        reported_balance, reported_on = latest.get(row.currency, (None, None))
        totals.append(
            CurrencyTotals(
                currency=row.currency,
                transactions=row.transactions,
                credits=row.credits,
                debits=row.debits,
                balance=row.balance,
                latest_reported_balance=reported_balance,
                latest_operation_date=reported_on,
            )
        )
    return SummaryOut(account_id=account_id, totals=totals)

from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
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


def _known_account(session: Session, account_id: str) -> bool:
    return session.get(models.Account, account_id) is not None


def _validated_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=400, detail=f"'from' ({date_from}) is after 'to' ({date_to})"
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    session: SessionDep,
    account_id: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> list[models.Transaction]:
    _validated_range(date_from, date_to)

    if account_id is not None and not _known_account(session, account_id):
        raise HTTPException(status_code=404, detail=f"unknown account_id {account_id!r}")

    query = select(models.Transaction)
    if account_id is not None:
        query = query.where(models.Transaction.account_id == account_id)
    if date_from is not None:
        query = query.where(models.Transaction.operation_date >= date_from)
    if date_to is not None:
        query = query.where(models.Transaction.operation_date <= date_to)

    query = query.order_by(
        models.Transaction.operation_date, models.Transaction.transaction_id
    )
    return list(session.scalars(query))

from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(18, 2)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    # 65 chars in the file ('A' + a 64-char hex digest), so 64 is one short.
    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    iban: Mapped[str | None] = mapped_column(String(34))
    entity: Mapped[str | None] = mapped_column(String(64))

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id"), nullable=False
    )

    operation_date: Mapped[date] = mapped_column(nullable=False)
    value_date: Mapped[date | None]

    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[Decimal | None] = mapped_column(MONEY)

    description: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[str | None] = mapped_column(String(64))
    category_code: Mapped[str | None] = mapped_column(String(32))
    transaction_type: Mapped[str | None] = mapped_column(String(32))

    account: Mapped[Account] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_account_operation_date", "account_id", "operation_date"),
    )

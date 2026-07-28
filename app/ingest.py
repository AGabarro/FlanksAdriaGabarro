import argparse
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import create_all, session_scope
from app.parser import ParseResult, RejectedRow, Transaction, parse_csv

DEFAULT_CSV = Path("data/flanks_test_transactions.csv")


@dataclass(frozen=True, slots=True)
class IngestReport:
    total_rows: int
    accounts_upserted: int
    inserted: int
    exact_duplicates: int
    conflicting_duplicates: int
    already_present: int
    dates_recovered: int
    conflicting_ids: tuple[str, ...]
    rejected_rows: tuple[RejectedRow, ...]

    @property
    def rejected(self) -> int:
        return len(self.rejected_rows)

    def accounted_for(self) -> int:
        return (
            self.inserted
            + self.exact_duplicates
            + self.conflicting_duplicates
            + self.already_present
            + self.rejected
        )

    def render(self) -> str:
        lines = [
            f"rows read                {self.total_rows}",
            f"accounts upserted        {self.accounts_upserted}",
            f"transactions inserted    {self.inserted}",
            f"duplicates (exact)       {self.exact_duplicates}",
            f"duplicates (conflicting) {self.conflicting_duplicates}",
            f"already in database      {self.already_present}",
            f"rejected                 {self.rejected}",
            f"dates recovered from id  {self.dates_recovered}",
            f"accounted for            {self.accounted_for()} / {self.total_rows}",
        ]
        if self.conflicting_ids:
            lines.append("\nconflicting duplicates (kept first seen):")
            lines += [f"  {tid}" for tid in self.conflicting_ids]
        if self.rejected_rows:
            lines.append("\nrejected rows:")
            lines += [
                f"  line {row.line}: {row.transaction_id or '<no id>'} -- {'; '.join(row.reasons)}"
                for row in self.rejected_rows
            ]
        return "\n".join(lines)


def _same_stored_data(left: Transaction, right: Transaction) -> bool:
    normalise = lambda t: replace(t, date_recovered_from_id=False)  # noqa: E731
    return normalise(left) == normalise(right)


def deduplicate(
    transactions: list[Transaction],
) -> tuple[dict[str, Transaction], int, list[str]]:
    kept: dict[str, Transaction] = {}
    exact = 0
    conflicting: list[str] = []
    for transaction in transactions:
        seen = kept.get(transaction.transaction_id)
        if seen is None:
            kept[transaction.transaction_id] = transaction
        elif _same_stored_data(seen, transaction):
            exact += 1
        else:
            conflicting.append(transaction.transaction_id)
    return kept, exact, conflicting


def _upsert_accounts(session: Session, transactions: list[Transaction]) -> int:
    accounts: dict[str, models.Account] = {}
    for transaction in transactions:
        account = accounts.get(transaction.account_id)
        if account is None:
            accounts[transaction.account_id] = models.Account(
                account_id=transaction.account_id,
                iban=transaction.iban,
                entity=transaction.entity,
            )
            continue
        account.iban = account.iban or transaction.iban
        account.entity = account.entity or transaction.entity

    for account in accounts.values():
        session.merge(account)
    return len(accounts)


def persist(parsed: ParseResult, total_rows: int) -> IngestReport:
    kept, exact, conflicting = deduplicate(parsed.valid)

    with session_scope() as session:
        accounts_upserted = _upsert_accounts(session, list(kept.values()))
        session.flush()

        existing = set(session.scalars(select(models.Transaction.transaction_id)))

        inserted = 0
        for transaction in kept.values():
            if transaction.transaction_id in existing:
                continue
            session.add(
                models.Transaction(
                    transaction_id=transaction.transaction_id,
                    account_id=transaction.account_id,
                    operation_date=transaction.operation_date,
                    value_date=transaction.value_date,
                    amount=transaction.amount,
                    currency=transaction.currency,
                    balance=transaction.balance,
                    description=transaction.description,
                    category=transaction.category,
                    category_code=transaction.category_code,
                    transaction_type=transaction.transaction_type,
                )
            )
            inserted += 1

    return IngestReport(
        total_rows=total_rows,
        accounts_upserted=accounts_upserted,
        inserted=inserted,
        exact_duplicates=exact,
        conflicting_duplicates=len(conflicting),
        already_present=len(kept) - inserted,
        dates_recovered=sum(t.date_recovered_from_id for t in kept.values()),
        conflicting_ids=tuple(conflicting),
        rejected_rows=tuple(parsed.rejected),
    )


def ingest_file(csv_path: Path) -> IngestReport:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        parsed = parse_csv(handle)
    total_rows = len(parsed.valid) + len(parsed.rejected)
    return persist(parsed, total_rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the transactions CSV into Postgres.")
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args(argv)

    if not args.csv_path.exists():
        parser.error(f"no such file: {args.csv_path}")

    create_all()
    print(ingest_file(args.csv_path).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

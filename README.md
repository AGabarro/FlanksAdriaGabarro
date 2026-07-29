# Flanks Technical Test — Transaction Ingest & API

Messy bank-transaction CSV → normalised → Postgres → REST API, with an in-memory
cache on the aggregation.

Python 3.14 · FastAPI · SQLAlchemy 2.0 · Postgres 16

## Running it

```bash
docker compose up --build
```

Database starts → CSV loads → API serves on <http://localhost:8000> (`/docs`).
Ordering is compose health and exit conditions, not sleeps: the API waits for the
loader to exit 0, so it can't serve an empty database.

```bash
curl "localhost:8000/transactions?account_id=<id>&from=2023-01-01&to=2023-03-31"
curl "localhost:8000/transactions/summary?account_id=<id>"
```

97 tests, no container needed (throwaway SQLite per test):

```bash
pip install -r requirements.txt && pytest
```

Every ingest run prints:

```
rows read 537 · inserted 519 · duplicates 6 exact + 4 conflicting · rejected 8
accounted for 537 / 537
```

Every row lands in exactly one bucket — if one were dropped silently, that line
wouldn't balance. Rejects are listed with file line number and reason.

## Schema

```sql
accounts      (account_id PK, iban, entity)
transactions  (transaction_id PK, account_id FK → accounts,
               operation_date, value_date, amount NUMERIC(18,2), currency,
               balance NUMERIC(18,2), description, category, category_code,
               transaction_type)
INDEX ON transactions (account_id, operation_date)
```

| Decision | Why |
|---|---|
| Separate `accounts` | `account_id → iban → entity` is 100% consistent across all 537 rows (checked). 7 rows instead of 537 copies that can drift |
| `currency` on `transactions` | one account holds EUR, USD and GBP — genuinely per-transaction, and it's what forces the summary to group |
| `NUMERIC(18,2)` + `Decimal` | exact from CSV through to JSON, where Pydantic emits a **string** — JSON numbers are IEEE doubles and would undo the chain |
| `transaction_id` as PK | uniqueness enforced by the database, not only application code |
| Index `(account_id, operation_date)` | matches both endpoints' filter order, usable left-to-right |

**Trade-offs:** no `categories` table — correct, not worth it at 537 rows.
`category_code` and `transaction_type` are opaque codes with no lookup provided,
so they're stored as given.

## Duplicates and malformed rows

Read with the stdlib `csv` module: quoted fields contain commas (`"-423,48"`,
`"TRANSFERENCIA, RECIBIDA"`), so `line.split(",")` would corrupt rows silently.

**Malformed.** Each field separates *missing* (blank → `None`) from *malformed*
(raises; the message becomes the reject reason). A row is rejected only when
something required is unusable — here 8, all missing an amount, each with its line
number. Blank `description` → `NULL`. Ragged rows are detected, never padded.

**Duplicates.** 12 duplicated ids, and the point is that normalisation runs *first*:

| Raw | As values | |
|---|---|---|
| `-423,48` vs `-423.48` | both `-423.48` | same transaction |
| `-22.15` vs `-€22.15` | both `-22.15` | same transaction |
| `-468.66` vs `-468.67` | differ | genuine conflict |

9 conflicts as text, **4** as values — deduplicating on raw text would have
quarantined five rows that never needed a human.

Policy: exact duplicates skipped and counted; conflicts **keep first seen** with
the id logged; ids already stored are skipped, so re-running ingest is a no-op —
which matters, since a restarted container re-runs the loader. First-seen because
it's deterministic: the file has no timestamp to prefer a later row by.

## Ambiguities, and the calls I made

| Question | Decision |
|---|---|
| `10-08-2023` — day or month first? | **Day-first.** Measured: the first component reaches 31, the second never exceeds 12 |
| 5 rows have no `operation_date` | Recovered from the date encoded in `transaction_id` — 532 agree, 0 disagree across the file. Counted in the report; never applied to a date that was present but malformed |
| Mixed currencies in one account | **Grouped, not summed.** Summing needs an FX rate, and inventing one fabricates data |
| "Total balance" | `balance` is **not** a running balance: `balance[i]-balance[i-1] == amount[i]` holds 5 times in 517 pairs. So it means credits + debits, which always reconciles; the raw column ships as `latest_reported_balance` |
| Unknown account vs no results | `404` vs `200 []` — collapsing them would hide a typo'd id |

## Cache

`/transactions/summary` (`GROUP BY` + window function) is the cached endpoint.
In-process `TTLCache`, 60s, keyed on `account_id`, with `X-Cache: HIT | MISS` on
every response. It can't survive a restart — a dict in the process, by
construction. Ingest clears it after committing, but only in-process: under
compose the loader is a separate container, so there the TTL is the real bound.

## Before production

| | |
|---|---|
| **Alembic** | `create_all()` doesn't alter existing tables, so a schema change currently needs the database dropped |
| **Quarantine conflicts** | keep-first discards the losing row. A conflicts table with the raw line and a review status would let someone actually resolve `-468.66` vs `-468.67` |
| **Shared cache invalidation** | Redis pub/sub or a version token, so a separate loader invalidates immediately instead of leaving the TTL as the bound |
| **Pagination** | unbounded list endpoint. Left out rather than added silently truncating |
| **Per-entity format hints** | the decimal separator is *inferred* ("rightmost wins") — correct for this file, but it would misread `1,234` |

Also: auth, `POSTGRES_PASSWORD` from a secret, and Postgres in CI — SQLite ignores
`VARCHAR` limits and hid a real column-width bug until Postgres rejected it.

## Layout

```
app/  normalize.py  pure functions over strings — no I/O, no app imports
      parser.py     csv.reader + validation → (valid, rejected with reasons)
      ingest.py     parse → deduplicate → persist → report
      models.py · db.py · cache.py · main.py
```

Flat on purpose. `normalize → parser → ingest` is the split that earns its place:
it's what makes the messy-data logic testable without a database.

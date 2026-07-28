import re
from datetime import date, datetime
from decimal import Decimal

_CURRENCY_ALIASES = {
    "EUR": "EUR",
    "€": "EUR",
    "EURO": "EUR",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "GBP": "GBP",
    "£": "GBP",
}

_AMOUNT_NOISE = re.compile(r"[€£$\sA-Za-z]")

_THOUSANDS_SEPARATORS = re.compile(r"[.,]")

_AMOUNT_SHAPE = re.compile(r"^[+-]?\d+(?:[.,]\d+)*$")

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%b %d %Y",
)

_ID_DATE = re.compile(r"^D(\d{4}-\d{2}-\d{2})N")


def normalize_currency(raw: str) -> str | None:
    """Fold the nine spellings in the file onto three ISO 4217 codes."""
    text = raw.strip().upper()
    if not text:
        return None
    try:
        return _CURRENCY_ALIASES[text]
    except KeyError:
        raise ValueError(f"unknown currency {raw!r}") from None


def parse_amount(raw: str) -> Decimal | None:
    stripped = raw.strip()
    if not stripped:
        return None

    text = _AMOUNT_NOISE.sub("", stripped)
    if not _AMOUNT_SHAPE.match(text):
        raise ValueError(f"unparseable amount {raw!r}")

    last_separator = max(text.rfind("."), text.rfind(","))
    if last_separator >= 0:
        whole = _THOUSANDS_SEPARATORS.sub("", text[:last_separator])
        text = f"{whole}.{text[last_separator + 1:]}"

    return Decimal(text)


def parse_date(raw: str) -> date | None:
    text = raw.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date {raw!r}")


def date_from_transaction_id(transaction_id: str) -> date | None:
    match = _ID_DATE.match(transaction_id.strip())
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None

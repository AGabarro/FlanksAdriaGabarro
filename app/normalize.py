import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

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

# Currency symbols and stray letters that turn up glued to an amount
# (six rows look like "-€22.15"). Also strips the non-breaking space.
_AMOUNT_NOISE = re.compile(r"[€£$\sA-Za-z]")

_THOUSANDS_SEPARATORS = re.compile(r"[.,]")

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
    text = _AMOUNT_NOISE.sub("", raw.strip())
    if not text:
        return None

    last_separator = max(text.rfind("."), text.rfind(","))
    if last_separator >= 0:
        whole = _THOUSANDS_SEPARATORS.sub("", text[:last_separator])
        text = f"{whole}.{text[last_separator + 1:]}"

    try:
        return Decimal(text)
    except InvalidOperation:
        raise ValueError(f"unparseable amount {raw!r}") from None


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
    """Recover the operation date encoded in the id, or ``None`` if it isn't there.

    Used only to fill the five rows with an empty ``operation_date``: the id
    carries the same date, and it agrees with ``operation_date`` in all 532 rows
    where both are present, which is what makes it trustworthy enough to use.
    """
    match = _ID_DATE.match(transaction_id.strip())
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None

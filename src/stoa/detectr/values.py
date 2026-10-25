"""Structured values inside text and payloads: money, numbers, ids, dates,
durations, statuses, emails.

Both the ledger index and claim extraction use this module, so a value the
agent states and a value a tool returned normalize the same way before they
are compared. Everything here is deterministic and dependency free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

VALUE_TYPES = ("money", "number", "id", "date", "duration", "weekday", "status", "email")

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "A$": "AUD", "C$": "CAD"}
CURRENCY_CODES = ("USD", "EUR", "GBP", "JPY", "INR", "AUD", "CAD", "CHF", "SGD", "HKD", "NZD", "SEK", "NOK", "DKK")

# Statuses the agent or a tool may name. The right-hand side is the canonical
# form; two statuses with the same canonical form are not a contradiction.
DEFAULT_STATUS_SYNONYMS: dict[str, str] = {
    "pending": "pending", "in progress": "pending", "in_progress": "pending", "processing": "pending",
    "awaiting": "pending", "queued": "pending", "scheduled": "pending", "submitted": "pending",
    "approved": "approved", "authorized": "approved", "authorised": "approved", "granted": "approved",
    "processed": "completed", "completed": "completed", "complete": "completed", "succeeded": "completed",
    "success": "completed", "successful": "completed", "done": "completed", "settled": "completed",
    "paid": "completed", "issued": "completed",
    "declined": "declined", "denied": "declined", "rejected": "declined", "refused": "declined",
    "failed": "failed", "failure": "failed", "error": "failed", "errored": "failed",
    "cancelled": "cancelled", "canceled": "cancelled", "voided": "cancelled", "reversed": "cancelled",
    "refunded": "refunded",
    "shipped": "shipped", "dispatched": "shipped", "in transit": "shipped",
    "delivered": "delivered",
    "active": "active", "enabled": "active", "open": "open", "closed": "closed", "inactive": "inactive",
    "disabled": "inactive", "suspended": "suspended", "blocked": "suspended", "frozen": "suspended",
    "verified": "verified", "unverified": "unverified", "expired": "expired",
}

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


@dataclass(frozen=True)
class Value:
    """One normalized value. ``canonical`` is what comparisons use; ``raw`` is
    the text as written; ``field`` is the payload key it came from, when
    any; ``start``/``end`` are character offsets in the source text."""

    type: str
    canonical: str
    raw: str
    field: str | None = None
    start: int | None = None
    end: int | None = None
    extra: dict = dc_field(default_factory=dict, compare=False, hash=False)

    @property
    def numeric(self) -> Decimal | None:
        if self.type in ("money", "number"):
            try:
                return Decimal(self.canonical)
            except InvalidOperation:
                return None
        return None

    def key(self) -> str:
        """Comparison key. Money and plain numbers share a key so that 150
        in a tool result supports "$150" in a sentence."""
        if self.type in ("money", "number"):
            return f"num:{self.canonical}"
        return f"{self.type}:{self.canonical}"


# --- normalizers -------------------------------------------------------------


def normalize_number(text: str) -> str | None:
    """'1,250.50' -> '1250.5'; '15.00' -> '15'; '1.250,50' (EU) -> '1250.5'."""
    cleaned = text.strip().replace(" ", "").replace(" ", "")
    if not cleaned:
        return None
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("+-")
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative:
        value = -value
    text_value = format(value.normalize(), "f")
    if text_value in ("-0", "0.0"):
        text_value = "0"
    return text_value


def normalize_status(text: str, synonyms: dict[str, str] | None = None) -> str | None:
    table = synonyms or DEFAULT_STATUS_SYNONYMS
    key = text.strip().lower().replace("-", " ").replace("_", " ")
    if key in table:
        return table[key]
    key2 = key.replace(" ", "_")
    return table.get(key2)


def normalize_id(text: str) -> str:
    return text.strip().lstrip("#").upper()


def _iso_date(year: int, month: int, day: int) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if year < 100:
        year += 2000
    return f"{year:04d}-{month:02d}-{day:02d}"


# --- patterns ------------------------------------------------------------------

_NUM = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY_RE = re.compile(
    rf"(?P<sym>A\$|C\$|[$€£¥₹])\s?(?P<amt>{_NUM})(?:\s?(?P<code1>[A-Z]{{3}}))?"
    rf"|(?P<amt2>{_NUM})\s?(?P<code2>USD|EUR|GBP|JPY|INR|AUD|CAD|CHF|SGD|HKD|NZD|SEK|NOK|DKK|dollars|euros|pounds)\b"
    rf"|\b(?P<code3>USD|EUR|GBP|JPY|INR|AUD|CAD|CHF|SGD|HKD|NZD|SEK|NOK|DKK)\s?(?P<amt3>{_NUM})(?![\w.,])",
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_RE = re.compile(
    r"\b(?:[A-Z]{2,6}[-_]?\d{3,}(?:[-_][A-Z0-9]+)*"       # APR-4471, INV_20931, TX-99-AB
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # uuid
    r"|[a-z]{2,5}_[A-Za-z0-9]{8,}"                           # stripe style: pi_3Nk..., ch_1Hx...
    r"|[A-Z0-9]{10,}"                                       # bare long codes
    r"|#\d{3,})\b",
)
_REF_NUM_RE = re.compile(
    r"\b(?P<noun>order|ticket|case|invoice|account|acct|customer|ref(?:erence)?|txn|transaction|payment|refund|claim|id|number|no\.?)\s*(?:#|number|no\.?)?\s*(?P<num>[A-Z]*\d{3,}[A-Z0-9-]*)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b")
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\b")
_TEXT_DATE_RE = re.compile(
    r"\b(?:(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m1>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+(?P<y1>\d{4})"
    r"|(?P<m2>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y2>\d{4}))\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"\b(?:(?:within|in|after|takes?|up to|about|around|approximately|next)\s+)?(?P<n>\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an)\s*(?:to\s*(?P<n2>\d+)\s*)?[- ]?(?P<unit>business days?|working days?|days?|hours?|hrs?|weeks?|months?|minutes?|mins?)\b",
    re.IGNORECASE,
)
_WEEKDAY_RE = re.compile(r"\b(?:by|on|before|until|next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\b(tomorrow|today|tonight|end of (?:the )?(?:day|week|month))\b", re.IGNORECASE)
_STATUS_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in DEFAULT_STATUS_SYNONYMS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_PLAIN_NUM_RE = re.compile(rf"(?<![\w.-])(?P<n>{_NUM})(?![\w.-])")
_WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _unit_iso(n: int, unit: str) -> str:
    u = unit.lower()
    if u.startswith("business") or u.startswith("working"):
        return f"P{n}BD"
    if u.startswith("day"):
        return f"P{n}D"
    if u.startswith("hour") or u.startswith("hr"):
        return f"PT{n}H"
    if u.startswith("week"):
        return f"P{n}W"
    if u.startswith("month"):
        return f"P{n}M"
    return f"PT{n}M"


def extract_values(text: str, *, status_synonyms: dict[str, str] | None = None) -> list[Value]:
    """Every typed value in ``text``, left to right, without overlaps.
    Money wins over numbers, reference numbers win over bare numbers,
    dates win over everything they cover."""
    if not text:
        return []
    found: list[Value] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in taken)

    def add(value: Value) -> None:
        if value.start is None or value.end is None or free(value.start, value.end):
            found.append(value)
            if value.start is not None and value.end is not None:
                taken.append((value.start, value.end))

    for m in _EMAIL_RE.finditer(text):
        add(Value("email", m.group(0).lower(), m.group(0), start=m.start(), end=m.end()))
    for m in _ISO_DATE_RE.finditer(text):
        iso = _iso_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            add(Value("date", iso, m.group(0), start=m.start(), end=m.end()))
    for m in _TEXT_DATE_RE.finditer(text):
        day = int(m.group("d1") or m.group("d2"))
        month = _MONTHS[(m.group("m1") or m.group("m2"))[:3].lower()]
        year = int(m.group("y1") or m.group("y2"))
        iso = _iso_date(year, month, day)
        if iso:
            add(Value("date", iso, m.group(0), start=m.start(), end=m.end()))
    for m in _SLASH_DATE_RE.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # US first when it parses, else EU. Ambiguous forms record both.
        iso = _iso_date(y, a, b) if a <= 12 else _iso_date(y, b, a)
        if iso:
            extra = {}
            if a <= 12 and b <= 12 and a != b:
                extra["alternate"] = _iso_date(y, b, a)
            add(Value("date", iso, m.group(0), start=m.start(), end=m.end(), extra=extra))
    for m in _MONEY_RE.finditer(text):
        amount_text = m.group("amt") or m.group("amt2") or m.group("amt3")
        number = normalize_number(amount_text)
        if number is None:
            continue
        code = m.group("code1") or m.group("code2") or m.group("code3")
        if code:
            code = {"dollars": "USD", "euros": "EUR", "pounds": "GBP"}.get(code.lower(), code.upper())
        currency = code or CURRENCY_SYMBOLS.get(m.group("sym") or "", None)
        add(Value("money", number, m.group(0), start=m.start(), end=m.end(), extra={"currency": currency}))
    for m in _REF_NUM_RE.finditer(text):
        num = m.group("num")
        add(Value("id", normalize_id(num), num, start=m.start("num"), end=m.end("num"), extra={"noun": m.group("noun").lower()}))
    for m in _ID_RE.finditer(text):
        raw = m.group(0)
        if raw.isdigit() and not raw.startswith("#"):
            continue
        add(Value("id", normalize_id(raw), raw, start=m.start(), end=m.end()))
    for m in _DURATION_RE.finditer(text):
        n_text = m.group("n").lower()
        n = _WORD_NUMBERS.get(n_text)
        if n is None:
            try:
                n = int(n_text)
            except ValueError:
                continue
        extra = {}
        if m.group("n2"):
            extra["upper"] = _unit_iso(int(m.group("n2")), m.group("unit"))
        add(Value("duration", _unit_iso(n, m.group("unit")), m.group(0), start=m.start(), end=m.end(), extra=extra))
    for m in _WEEKDAY_RE.finditer(text):
        word = (m.group(1) or m.group(2)).lower()
        add(Value("weekday", word.replace("the ", ""), m.group(0), start=m.start(), end=m.end()))
    for m in _STATUS_RE.finditer(text):
        canonical = normalize_status(m.group(1), status_synonyms)
        if canonical:
            add(Value("status", canonical, m.group(1), start=m.start(), end=m.end()))
    for m in _PLAIN_NUM_RE.finditer(text):
        number = normalize_number(m.group("n"))
        if number is None:
            continue
        add(Value("number", number, m.group("n"), start=m.start(), end=m.end()))
    found.sort(key=lambda v: (v.start if v.start is not None else -1, v.end if v.end is not None else -1))
    return found


# --- payloads --------------------------------------------------------------------

_MONEY_FIELDS = ("amount", "total", "price", "fee", "balance", "refund", "limit", "cost", "value", "sum", "charge", "credit", "debit")
_ID_FIELDS = ("id", "ref", "reference", "number", "no", "code", "key", "token", "approval", "order", "account", "iban", "sku")
_STATUS_FIELDS = ("status", "state", "outcome", "result", "decision", "stage")
_DATE_FIELDS = ("date", "at", "on", "eta", "due", "expires", "expiry", "deadline", "created", "updated", "timestamp", "ts", "time")


def _field_hint(name: str) -> str | None:
    lowered = name.lower()
    parts = re.split(r"[._\-\s]+", lowered)
    tail = parts[-1] if parts else lowered
    if tail in _STATUS_FIELDS:
        return "status"
    if tail in _MONEY_FIELDS or lowered.endswith("_amount") or lowered.endswith("amount"):
        return "money"
    if tail in _DATE_FIELDS or lowered.endswith("_at") or lowered.endswith("_date"):
        return "date"
    if tail in _ID_FIELDS or lowered.endswith("_id") or lowered.endswith("id"):
        return "id"
    return None


def _walk(payload: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                yield from _walk(value, path)
            else:
                yield path, value
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            path = f"{prefix}[{i}]"
            if isinstance(item, (dict, list)):
                yield from _walk(item, path)
            else:
                yield path, item


def values_from_payload(payload: Any, *, status_synonyms: dict[str, str] | None = None) -> list[Value]:
    """Typed values from a parsed payload, one or more per leaf field. The
    field name decides the type when the value alone is ambiguous: an
    ``amount`` of 15 is money, an ``order_id`` of 8812 is an id, a
    ``status`` of ``pending`` is a status."""
    out: list[Value] = []
    if payload is None:
        return out
    if not isinstance(payload, (dict, list)):
        return extract_values(str(payload), status_synonyms=status_synonyms)
    for path, leaf in _walk(payload):
        if leaf is None or isinstance(leaf, bool):
            continue
        hint = _field_hint(path)
        if isinstance(leaf, (int, float)):
            number = normalize_number(repr(leaf) if isinstance(leaf, float) else str(leaf))
            if number is None:
                continue
            if hint == "id":
                out.append(Value("id", normalize_id(str(leaf)), str(leaf), field=path))
            elif hint == "money":
                out.append(Value("money", number, str(leaf), field=path))
            else:
                out.append(Value("number", number, str(leaf), field=path))
            continue
        text = str(leaf)
        if hint == "status":
            canonical = normalize_status(text, status_synonyms)
            if canonical:
                out.append(Value("status", canonical, text, field=path))
                continue
        if hint == "id":
            stripped = text.strip()
            if stripped and " " not in stripped:
                out.append(Value("id", normalize_id(stripped), stripped, field=path))
                continue
        if hint == "money":
            number = normalize_number(re.sub(r"[^\d.,-]", "", text)) if re.search(r"\d", text) else None
            if number is not None:
                currency = None
                for sym, code in CURRENCY_SYMBOLS.items():
                    if sym in text:
                        currency = code
                for code in CURRENCY_CODES:
                    if code in text.upper():
                        currency = code
                out.append(Value("money", number, text, field=path, extra={"currency": currency}))
                continue
        for value in extract_values(text, status_synonyms=status_synonyms):
            out.append(Value(value.type, value.canonical, value.raw, field=path, start=value.start, end=value.end, extra=value.extra))
    return out


def values_conflict(a: Value, b: Value) -> str | None:
    """Why two values for the same field disagree: 'numerical',
    'identifier', 'temporal', 'status', or None when they agree or are not
    comparable."""
    if a.type in ("money", "number") and b.type in ("money", "number"):
        na, nb = a.numeric, b.numeric
        if na is None or nb is None:
            return None
        ca, cb = a.extra.get("currency"), b.extra.get("currency")
        if na == nb and (not ca or not cb or ca == cb):
            return None
        return "numerical"
    if a.type != b.type:
        return None
    if a.type == "id":
        return None if a.canonical == b.canonical else "identifier"
    if a.type in ("date", "duration", "weekday"):
        if a.canonical == b.canonical or a.canonical == b.extra.get("alternate") or b.canonical == a.extra.get("alternate"):
            return None
        return "temporal"
    if a.type == "status":
        return None if a.canonical == b.canonical else "status"
    return None if a.canonical == b.canonical else a.type

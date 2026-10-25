"""Claims: what the agent said and did, one typed statement at a time.

Every ``tool_call`` entry is an action claim. Every ``agent_output`` entry is
split into sentences and clauses, each classified as action, result,
commitment, reasoning or factual, with its structured values, and with
negation, hedging and conditionality marked so the checks can read "I was
not able to process the refund" as the opposite of a phantom action.

Two extractors share one interface. The rule-based one is the default and
is deterministic. The model-based one is optional, cached by output hash,
and is never called on the synchronous path.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Callable, Protocol

from .ledger import Ledger, LedgerEntry
from .values import Value, extract_values, values_from_payload

CLAIM_TYPES = ("factual", "action", "result", "commitment", "reasoning")


@dataclass
class Claim:
    id: str
    span_id: str | None
    trajectory_id: str
    type: str
    text: str
    entry_id: str
    seq: int
    char_span: tuple[int, int] | None = None
    structured_values: list[Value] = dc_field(default_factory=list)
    depends_on: list[str] = dc_field(default_factory=list)
    consumed_by: list[str] = dc_field(default_factory=list)
    negated: bool = False
    hedged: bool = False
    conditional: bool = False
    tool_name: str | None = None
    source: str = "agent_output"
    extractor: str = "rules"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "span_id": self.span_id, "trajectory_id": self.trajectory_id, "type": self.type, "text": self.text,
            "entry_id": self.entry_id, "seq": self.seq, "char_span": list(self.char_span) if self.char_span else None,
            "structured_values": [{"type": v.type, "canonical": v.canonical, "raw": v.raw, "field": v.field} for v in self.structured_values],
            "depends_on": list(self.depends_on), "consumed_by": list(self.consumed_by), "negated": self.negated,
            "hedged": self.hedged, "conditional": self.conditional, "tool_name": self.tool_name, "source": self.source,
            "extractor": self.extractor,
        }


class ClaimExtractor(Protocol):
    name: str
    sync_capable: bool

    def extract(self, ledger: Ledger) -> list[Claim]: ...


# --- sentence and clause splitting ---------------------------------------------------

_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "no.", "approx.", "vs.", "mr.", "ms.", "dr.", "inc.", "ltd.", "st.")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n+")
_CLAUSE_SPLIT = re.compile(
    r",?\s+\b(?=(?:and|but|so|then)\s+(?:it\s+|you\s+|they\s+|we\s+|the\s+\w+\s+)?(?:will|won't|shall|should|would|can|could|may|might|is going to|are going to|'ll)\b)"
    r"|,?\s+\b(?=(?:and|but)\s+(?:I|I've|I have|we|we've)\s)"
    r"|;\s+",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of each sentence, abbreviations kept whole."""
    if not text:
        return []
    out: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        candidate = text[start:m.start()]
        tail = candidate.lower().rstrip()
        if any(tail.endswith(a) for a in _ABBREVIATIONS):
            continue
        if candidate.strip():
            out.append((start, m.start()))
        start = m.end()
    if text[start:].strip():
        out.append((start, len(text)))
    return [(s + (len(text[s:e]) - len(text[s:e].lstrip())), e - (len(text[s:e]) - len(text[s:e].rstrip()))) for s, e in out]


def split_clauses(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Clauses of one sentence. A sentence splits where a conjunction opens
    a future-tense clause ("and will arrive in 2 days"), where a new
    first-person statement starts, or at a semicolon."""
    segment = text[start:end]
    cuts = [m.start() for m in _CLAUSE_SPLIT.finditer(segment)]
    if not cuts:
        return [(start, end)]
    bounds = [0] + cuts + [len(segment)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        piece = segment[a:b]
        lead = len(piece) - len(piece.lstrip(" ,;"))
        trail = len(piece) - len(piece.rstrip(" ,;"))
        if piece.strip(" ,;"):
            out.append((start + a + lead, start + b - trail))
    return out


# --- classification -----------------------------------------------------------------

ACTION_VERBS = (
    "issued", "processed", "cancelled", "canceled", "refunded", "sent", "updated", "created", "scheduled", "submitted",
    "escalated", "transferred", "charged", "credited", "closed", "opened", "reset", "changed", "applied", "approved",
    "flagged", "logged", "filed", "placed", "completed", "confirmed", "booked", "verified", "deleted", "removed", "added",
    "moved", "paid", "released", "unlocked", "blocked", "disabled", "enabled", "activated", "deactivated", "upgraded",
    "downgraded", "renewed", "extended", "waived", "reversed", "notified", "emailed", "messaged", "forwarded", "assigned",
    "reopened", "resolved", "marked", "recorded", "registered", "set up", "signed up", "enrolled", "ordered", "shipped",
    "dispatched", "generated", "initiated", "triggered", "executed", "run", "ran", "started", "stopped", "paused",
    "resumed", "terminated", "revoked", "granted", "linked", "unlinked", "merged", "split", "adjusted", "corrected",
    "fixed", "restored", "replaced", "reissued", "reinstated",
)
ACTION_BASES = (
    "issue", "process", "cancel", "refund", "send", "update", "create", "schedule", "submit", "escalate", "transfer",
    "charge", "credit", "close", "open", "reset", "change", "apply", "approve", "flag", "log", "file", "place", "complete",
    "confirm", "book", "verify", "delete", "remove", "add", "move", "pay", "release", "unlock", "block", "disable", "enable",
    "activate", "deactivate", "upgrade", "downgrade", "renew", "extend", "waive", "reverse", "notify", "email", "message",
    "forward", "assign", "reopen", "resolve", "mark", "record", "register", "set up", "sign up", "enroll", "order", "ship",
    "dispatch", "generate", "initiate", "trigger", "execute", "run", "start", "stop", "pause", "resume", "terminate",
    "revoke", "grant", "link", "unlink", "merge", "adjust", "correct", "fix", "restore", "replace", "reissue", "reinstate",
    "locate", "find", "retrieve", "access", "pull up", "look up", "modify", "void", "waive",
)
_VERBS = "|".join(sorted((re.escape(v) for v in ACTION_VERBS), key=len, reverse=True))
_BASES = "|".join(sorted((re.escape(v) for v in ACTION_BASES), key=len, reverse=True))
_ADV = r"(?:not|never|just|now|already|also|successfully|manually|personally|then|yet)"
_SUBJECT_NOUNS = (
    r"(?:refund|order|payment|ticket|account|transfer|request|case|card|subscription|appointment|invoice|claim|dispute|"
    r"charge|credit|balance|address|email|password|plan|booking|reservation|shipment|delivery|limit|flag|hold|freeze|"
    r"profile|record|file|report|alert|notification|transaction|verification|application|loan|policy|quote|coverage)"
)
_ACTION_PATTERNS = [
    # negated infinitives: "I was not able to update", "couldn't locate", "failed to send"
    re.compile(rf"\b(?:unable to|not able to|couldn't|could not|failed to|didn't|did not|wasn't able to|weren't able to|haven't been able to|hasn't been able to|have not been able to|has not been able to|can't|cannot|won't be able to|will not be able to|refused to|declined to|neglected to|forgot to)\s+(?:yet\s+)?({_BASES})\b", re.IGNORECASE),
    re.compile(rf"\bI\s*(?:'ve|have|'d|had|went ahead and|gone ahead and|{_ADV})?(?:\s+{_ADV})*\s+({_VERBS})\b", re.IGNORECASE),
    re.compile(rf"\b(?:we|our team|the system|the agent)\s*(?:'ve|have|'d|had|{_ADV})?(?:\s+{_ADV})*\s+({_VERBS})\b", re.IGNORECASE),
    re.compile(rf"\b(?:has|have|had|was|were|'ve|got|gets|been)\s+(?:{_ADV}\s+|been\s+)*({_VERBS})\b", re.IGNORECASE),
    re.compile(rf"\b(?:the|your|this|that|his|her|their)\s+{_SUBJECT_NOUNS}(?:\s+\S+){{0,4}}?\s+(?:has been|have been|was|were|is now|are now|got|is|are)\s+(?:now\s+|already\s+|successfully\s+)*({_VERBS})\b", re.IGNORECASE),
    re.compile(rf"^\s*(?:done[.:,!]?\s*)?({_VERBS})\b(?:\s+(?:the|your|a|an)\b)", re.IGNORECASE),
    re.compile(rf"\b(?:consider it|that's|that is)\s+({_VERBS})\b", re.IGNORECASE),
]
_FUTURE = re.compile(
    r"\b(?:will|won't|shall|'ll|you'll|we'll|it'll|they'll|going to|gonna|is covered|are covered|is guaranteed|are guaranteed|"
    r"guarantee[sd]?|promise[sd]?|ensure[sd]?|is eligible|are eligible|qualif(?:y|ies) for|expect(?:ed)? to|be able to|"
    r"within the next|by (?:end of|the end of|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"in the next|for the next|over the next|no later than|at no (?:extra )?cost|free of charge|for free|is on its way|are on their way|is on the way|"
    r"(?:for|on|this coming|next) (?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month))\b",
    re.IGNORECASE,
)
_REASONING = re.compile(r"\b(?:because|therefore|since|hence|thus|as a result|that's why|which means|so that|due to|given that|this means|consequently|the reason)\b", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(?:not|n't|never|no longer|unable|cannot|can't|couldn't|wasn't|weren't|isn't|aren't|haven't|hasn't|hadn't|didn't|"
    r"don't|doesn't|won't|wouldn't|failed to|fail to|unsuccessful|without|declined to|refused to|yet to|still need to|"
    r"was not able|were not able|am not able|is not able|have not been able|has not been able|neither|nor)\b"
    r"|\bno\s+(?:refund|payment|charge|change|changes|action|transfer|order|record|match|results?)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(
    r"\b(?:should|might|may|could|likely|unlikely|probably|possibly|perhaps|typically|usually|normally|generally|"
    r"approximately|around|about|roughly|estimated?|expect(?:ed)?|appears?|seems?|I think|I believe|as far as I can tell|"
    r"to my knowledge|it looks like|in most cases|tends? to|up to|at least|at most)\b",
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(r"\b(?:if|unless|once|provided that|as long as|in case|assuming|should you|when you|after you|depending on|subject to|whether)\b", re.IGNORECASE)
_QUESTION = re.compile(r"\?\s*$")
_TRACKED = re.compile(rf"\b{_SUBJECT_NOUNS}s?\b|\b(?:status|state|outcome|stage)\b", re.IGNORECASE)
_STATUS_SUBJECT = re.compile(r"\b(?:status|state|outcome|stage)\s+(?:is|was|reads|shows|came back|returned|remains|is now|says)\b", re.IGNORECASE)
_PAST_RESULT = re.compile(r"\b(?:is|are|was|were|has|have|shows?|showed|returned|came back|reads?|stands? at|currently|now)\b", re.IGNORECASE)


def _flags(text: str) -> tuple[bool, bool, bool]:
    return bool(_NEGATION.search(text)), bool(_HEDGE.search(text)), bool(_CONDITIONAL.search(text))


def _action_verb(text: str) -> str | None:
    for pattern in _ACTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).lower()
    return None


def classify_clause(text: str) -> tuple[str, dict]:
    """(type, detail) for one clause. Commitments are judged before
    actions so "I have scheduled it and it will arrive Friday" splits into
    an action and a commitment rather than one action."""
    stripped = text.strip()
    detail: dict = {}
    if not stripped:
        return "factual", detail
    negated, hedged, conditional = _flags(stripped)
    detail.update(negated=negated, hedged=hedged, conditional=conditional)
    values = extract_values(stripped)
    detail["values"] = values
    verb = _action_verb(stripped)
    if verb:
        detail["verb"] = verb
    if _QUESTION.search(stripped):
        return "factual", detail
    if _REASONING.search(stripped):
        return "reasoning", detail
    if _STATUS_SUBJECT.search(stripped):
        return "result", detail
    future = _FUTURE.search(stripped)
    forward_time = any(v.type in ("duration", "weekday") for v in values)
    if future and not (verb and not forward_time and not re.search(r"\b(?:will|'ll|going to)\b", stripped, re.IGNORECASE)):
        return "commitment", detail
    if verb:
        return "action", detail
    if forward_time and not _PAST_RESULT.search(stripped):
        return "commitment", detail
    if values and any(v.type in ("money", "id", "date", "number") for v in values):
        return "result", detail
    # A status word on its own ("closed", "active") is a result only when a
    # tracked object is named; "our office is closed" is a plain fact.
    if any(v.type == "status" for v in values) and _TRACKED.search(stripped):
        return "result", detail
    return "factual", detail


# --- the rule-based extractor ----------------------------------------------------------

class RuleClaimExtractor:
    """Default extractor: deterministic, dependency free, runs inline."""

    name = "rules"
    sync_capable = True

    def __init__(self, *, status_synonyms: dict[str, str] | None = None) -> None:
        self.status_synonyms = status_synonyms

    def extract(self, ledger: Ledger) -> list[Claim]:
        claims: list[Claim] = []
        counter = 0

        def new_id() -> str:
            nonlocal counter
            counter += 1
            return f"c{counter:04d}"

        for entry in ledger.entries:
            if entry.kind == "tool_call":
                claims.append(self._action_from_call(ledger, entry, new_id()))
            elif entry.kind == "agent_output" and entry.content_captured:
                claims.extend(self._from_output(ledger, entry, new_id))
        link_claims(claims)
        return claims

    def _action_from_call(self, ledger: Ledger, entry: LedgerEntry, claim_id: str) -> Claim:
        args = entry.parsed if entry.parsed is not None else entry.raw_payload
        text = f"{entry.tool_name or 'tool'}({json.dumps(args, sort_keys=True, default=str) if args is not None else ''})"
        values = values_from_payload(args, status_synonyms=self.status_synonyms) if entry.content_captured else []
        return Claim(
            id=claim_id, span_id=entry.span_id, trajectory_id=ledger.trajectory_id, type="action", text=text,
            entry_id=entry.id, seq=entry.seq, structured_values=values, tool_name=entry.tool_name, source="tool_call",
        )

    def _from_output(self, ledger: Ledger, entry: LedgerEntry, new_id: Callable[[], str]) -> list[Claim]:
        text = entry.text_view if isinstance(entry.raw_payload, (dict, list)) else str(entry.raw_payload or "")
        out: list[Claim] = []
        for s_start, s_end in split_sentences(text):
            for c_start, c_end in split_clauses(text, s_start, s_end):
                clause = text[c_start:c_end]
                kind, detail = classify_clause(clause)
                values = [
                    Value(v.type, v.canonical, v.raw, field=v.field,
                          start=(v.start + c_start) if v.start is not None else None,
                          end=(v.end + c_start) if v.end is not None else None, extra=v.extra)
                    for v in detail.get("values", [])
                ]
                out.append(Claim(
                    id=new_id(), span_id=entry.span_id, trajectory_id=ledger.trajectory_id, type=kind, text=clause.strip(),
                    entry_id=entry.id, seq=entry.seq, char_span=(c_start, c_end), structured_values=values,
                    negated=detail.get("negated", False), hedged=detail.get("hedged", False),
                    conditional=detail.get("conditional", False), tool_name=detail.get("verb"), source="agent_output",
                ))
        return out


def link_claims(claims: list[Claim]) -> None:
    """Fill ``depends_on`` and ``consumed_by`` from shared values: a claim
    depends on earlier claims that carry one of its ids, amounts or dates,
    and those claims are consumed by it."""
    seen: dict[str, list[Claim]] = {}
    for claim in sorted(claims, key=lambda c: (c.seq, c.id)):
        keys = {v.key() for v in claim.structured_values if v.type in ("money", "number", "id", "date", "email")}
        for key in sorted(keys):
            for earlier in seen.get(key, []):
                if earlier.entry_id == claim.entry_id and earlier.source == claim.source:
                    continue
                if earlier.id not in claim.depends_on:
                    claim.depends_on.append(earlier.id)
                if claim.id not in earlier.consumed_by:
                    earlier.consumed_by.append(claim.id)
        for key in keys:
            seen.setdefault(key, []).append(claim)


# --- the optional model-based extractor -----------------------------------------------

_LLM_PROMPT_VERSION = "detectr-claims/1"
_LLM_INSTRUCTIONS = (
    "Split the agent message into atomic claims. Return JSON: a list of objects with "
    "\"text\" (verbatim substring), \"type\" (one of factual, action, result, commitment, reasoning), "
    "\"negated\", \"hedged\", \"conditional\" (booleans). Keep the order of the message. Message:\n\n"
)


class LLMClaimExtractor:
    """Structured-output extractor for prose the rules miss. ``complete`` is
    a callable taking the prompt and returning the model's text; results
    are cached by message hash. This extractor is never run on the
    synchronous path; the router only schedules it in the deferred lane."""

    name = "llm"
    sync_capable = False

    def __init__(self, complete: Callable[[str], str], *, cache_path: str | Path | None = None, fallback: ClaimExtractor | None = None) -> None:
        self._complete = complete
        self._cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, Any] = {}
        self._fallback = fallback or RuleClaimExtractor()
        if self._cache_path and self._cache_path.exists():
            try:
                self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._cache = {}

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{_LLM_PROMPT_VERSION}\n{text}".encode("utf-8")).hexdigest()

    def _save(self) -> None:
        if self._cache_path:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache, sort_keys=True), encoding="utf-8")

    def extract(self, ledger: Ledger) -> list[Claim]:
        claims: list[Claim] = []
        counter = 0
        for entry in ledger.entries:
            if entry.kind == "tool_call":
                counter += 1
                claims.append(self._fallback._action_from_call(ledger, entry, f"c{counter:04d}"))  # type: ignore[attr-defined]
                continue
            if entry.kind != "agent_output" or not entry.content_captured:
                continue
            text = entry.text_view
            key = self._key(text)
            rows = self._cache.get(key)
            if rows is None:
                try:
                    rows = json.loads(self._complete(_LLM_INSTRUCTIONS + text))
                    if not isinstance(rows, list):
                        rows = []
                except Exception:  # noqa: BLE001
                    rows = []
                self._cache[key] = rows
                self._save()
            cursor = 0
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                    continue
                kind = row.get("type") if row.get("type") in CLAIM_TYPES else "factual"
                position = text.find(row["text"], cursor)
                span = (position, position + len(row["text"])) if position >= 0 else None
                if span:
                    cursor = span[1]
                counter += 1
                claims.append(Claim(
                    id=f"c{counter:04d}", span_id=entry.span_id, trajectory_id=ledger.trajectory_id, type=kind, text=row["text"],
                    entry_id=entry.id, seq=entry.seq, char_span=span, structured_values=extract_values(row["text"]),
                    negated=bool(row.get("negated")), hedged=bool(row.get("hedged")), conditional=bool(row.get("conditional")),
                    source="agent_output", extractor="llm",
                ))
        link_claims(claims)
        return claims


def extract_claims(ledger: Ledger, extractor: ClaimExtractor | None = None) -> list[Claim]:
    return (extractor or RuleClaimExtractor()).extract(ledger)

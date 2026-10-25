"""Layer 0: deterministic checks over (claim, ledger). No models, no network.

RT009 phantom action, RT010 result fidelity, RT011 hallucinated promise,
RT012 argument grounding, RT013 stale grounding. Each check is a pure
function and returns verdicts that name the ledger entries they used, so a
finding can be audited back to the trace. Grounded verdicts are returned
too; fusion decides what becomes a finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import date
from decimal import Decimal

from .claims import Claim
from .ledger import GROUNDING_KINDS, Ledger, LedgerEntry
from .values import Value, normalize_status, values_conflict

LABELS = ("grounded", "unsupported", "contradicted", "unverifiable")
RULE_IDS = {"phantom": "RT009", "fidelity": "RT010", "promise": "RT011", "argument": "RT012", "stale": "RT013"}

# Argument classes worth grounding. Plain counts (page=1, limit=10) and free
# text are not checked: they are rarely hallucinated and often legitimate.
GROUNDED_ARG_TYPES = ("money", "id", "email", "date")


@dataclass
class Tolerances:
    """How close two values must be to count as the same."""

    money_abs: Decimal = Decimal("0.01")
    date_days: int = 1
    status_synonyms: dict[str, str] | None = None


@dataclass
class Verdict:
    claim_id: str
    label: str
    rule_id: str | None = None
    subcategory: str | None = None
    evidence: list[str] = dc_field(default_factory=list)
    detail: str = ""
    field: str | None = None
    value: str | None = None
    expected: str | None = None
    confidence: float = 1.0
    checker: str = "layer0"

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "label": self.label, "rule_id": self.rule_id, "subcategory": self.subcategory,
            "evidence": list(self.evidence), "detail": self.detail, "field": self.field, "value": self.value,
            "expected": self.expected, "confidence": self.confidence, "checker": self.checker,
        }


# --- matching helpers ---------------------------------------------------------------------

_STOP = {
    "the", "your", "a", "an", "has", "have", "had", "been", "is", "are", "was", "were", "now", "i", "ve", "we", "it", "its",
    "and", "to", "of", "for", "on", "in", "at", "by", "with", "this", "that", "you", "my", "our", "just", "already", "also",
    "successfully", "went", "ahead", "done", "consider", "all", "set", "as", "so", "be", "will", "from", "into", "out",
}
_VERB_SYNONYMS: dict[str, set[str]] = {
    "process": {"process", "issue", "execute", "submit", "pay", "refund", "run", "complete"},
    "issu": {"issue", "create", "refund", "send", "pay"},
    "refund": {"refund", "issue", "pay", "credit", "reverse"},
    "cancel": {"cancel", "void", "delete", "close", "revoke"},
    "updat": {"update", "set", "change", "modify", "edit", "patch", "put"},
    "chang": {"change", "update", "set", "modify", "edit"},
    "escalat": {"escalate", "assign", "route", "handoff", "transfer"},
    "clos": {"close", "resolve"}, "resolv": {"resolve", "close"},
    "sent": {"send", "email", "notify", "message", "mail"}, "send": {"send", "email", "notify", "message", "mail"},
    "email": {"email", "send", "notify", "mail"}, "notif": {"notify", "send", "email", "alert"},
    "charg": {"charge", "pay", "capture", "debit"}, "credit": {"credit", "refund", "adjust"},
    "transfer": {"transfer", "pay", "send", "move", "wire"}, "paid": {"pay", "transfer", "settle"}, "pay": {"pay", "transfer", "settle"},
    "book": {"book", "schedule", "create", "reserve"}, "schedul": {"schedule", "book", "create"},
    "submit": {"submit", "create", "file", "send"}, "approv": {"approve", "authorize"},
    "flag": {"flag", "mark", "report"}, "mark": {"mark", "update", "set", "flag", "tag"},
    "delet": {"delete", "remove"}, "remov": {"remove", "delete"}, "add": {"add", "create", "attach"},
    "creat": {"create", "add", "open", "new"}, "block": {"block", "freeze", "lock", "disable", "suspend"},
    "unlock": {"unlock", "enable", "unblock", "release"}, "releas": {"release", "unlock"},
    "waiv": {"waive", "adjust", "credit", "remove"}, "verif": {"verify", "check", "validate", "confirm"},
    "log": {"log", "record", "create", "note"}, "record": {"record", "log", "note"},
    "reset": {"reset"}, "disabl": {"disable", "block"}, "enabl": {"enable", "unlock"},
    "activat": {"activate", "enable"}, "deactivat": {"deactivate", "disable"}, "renew": {"renew", "extend"},
    "extend": {"extend", "renew"}, "revers": {"reverse", "refund", "void"}, "assign": {"assign", "route", "escalate"},
    "reopen": {"reopen", "open"}, "regist": {"register", "create", "enroll"}, "enrol": {"enroll", "register"},
    "order": {"order", "create", "place"}, "plac": {"place", "create", "order"}, "ship": {"ship", "dispatch", "send"},
    "dispatch": {"dispatch", "ship", "send"}, "generat": {"generate", "create"}, "initiat": {"initiate", "start", "create"},
    "trigger": {"trigger", "start", "run"}, "execut": {"execute", "run"}, "start": {"start", "initiate", "run"},
    "stop": {"stop", "cancel", "pause"}, "paus": {"pause", "stop", "suspend"}, "resum": {"resume", "unpause", "restart"},
    "terminat": {"terminate", "cancel", "close"}, "revok": {"revoke", "cancel", "delete"}, "grant": {"grant", "approve", "add"},
    "link": {"link", "attach", "connect"}, "merg": {"merge", "combine"}, "adjust": {"adjust", "update", "credit"},
    "correct": {"correct", "update", "fix"}, "fix": {"fix", "update", "correct"}, "restor": {"restore", "reinstate", "reactivate"},
    "replac": {"replace", "reissue"}, "reissu": {"reissue", "issue", "replace"}, "reinstat": {"reinstate", "restore", "reactivate"},
    "locat": {"lookup", "look", "find", "search", "get", "fetch"}, "find": {"find", "lookup", "search", "get"},
    "retriev": {"retrieve", "get", "fetch", "lookup"}, "look": {"lookup", "look", "search", "get"}, "pull": {"get", "fetch", "lookup"},
    "void": {"void", "cancel", "reverse"}, "confirm": {"confirm", "verify", "approve"}, "complet": {"complete", "finish", "process"},
    "upgrad": {"upgrade", "update", "change"}, "downgrad": {"downgrade", "update", "change"}, "forward": {"forward", "send", "route"},
    "messag": {"message", "send", "notify"}, "moved": {"move", "transfer"}, "mov": {"move", "transfer"},
}


def _stem(word: str) -> str:
    w = word.lower()
    for ending in ("ing", "ied", "ies", "ed", "es", "s"):
        if w.endswith(ending) and len(w) - len(ending) >= 3:
            return w[: -len(ending)]
    return w


def _tokens(text: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return [t for t in re.split(r"[^A-Za-z]+", spaced.lower()) if t and t not in _STOP]


def _same_token(a: str, b: str) -> bool:
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 4 and longer.startswith(shorter):
        return True
    # verification / verify, cancellation / cancel: a shared five-letter root
    return len(shorter) >= 6 and shorter[:5] == longer[:5]


def _verb_score(verb: str | None, tool_stems: set[str]) -> int:
    if not verb:
        return 0
    stem = _stem(verb)
    if any(_same_token(stem, ts) for ts in tool_stems):
        return 2
    for syn in _VERB_SYNONYMS.get(stem, set()) | _VERB_SYNONYMS.get(verb.lower(), set()):
        if any(_same_token(_stem(syn), ts) for ts in tool_stems):
            return 1
    return 0


def tool_matches_claim(tool_name: str | None, claim: Claim, *, require_verb: bool = False) -> int:
    """How strongly a tool name matches a clause. The verb the agent used
    ("issued", "escalated") is weighed against the tool's name and its
    synonyms; shared nouns ("refund", "ticket") add a little. With
    ``require_verb`` a noun alone is not enough: "your order" does not make
    orders.get evidence that a refund was issued."""
    if not tool_name:
        return 0
    tool_stems = {_stem(t) for t in _tokens(tool_name)}
    verb = claim.tool_name if claim.source == "agent_output" else None
    verb_score = _verb_score(verb, tool_stems)
    # State words ("verified", "approved") describe the object, not the tool.
    claim_stems = {_stem(t) for t in _tokens(claim.text) if not normalize_status(t)} - ({_stem(verb)} if verb else set())
    noun_score = sum(1 for cs in claim_stems if any(_same_token(cs, ts) for ts in tool_stems))
    if require_verb and verb_score == 0:
        # "has been completed", "is approved": the verb is a state word, so the
        # object noun ("refund" against refund.issue) decides instead.
        if not (verb and normalize_status(verb) and noun_score > 0):
            return 0
    return verb_score * 3 + noun_score


def _same_value(a: Value, b: Value, tol: Tolerances) -> bool:
    if values_conflict(a, b) is None and a.key() == b.key():
        return True
    if a.type in ("money", "number") and b.type in ("money", "number"):
        na, nb = a.numeric, b.numeric
        if na is not None and nb is not None and abs(na - nb) <= tol.money_abs:
            ca, cb = a.extra.get("currency"), b.extra.get("currency")
            return not ca or not cb or ca == cb
        return False
    if a.type == b.type == "date":
        try:
            da, db = date.fromisoformat(a.canonical), date.fromisoformat(b.canonical)
        except ValueError:
            return a.canonical == b.canonical
        if abs((da - db).days) <= tol.date_days:
            return True
        alt = a.extra.get("alternate") or b.extra.get("alternate")
        return bool(alt) and alt in (a.canonical, b.canonical)
    if a.type == b.type == "status":
        return a.canonical == b.canonical
    return a.type == b.type and a.canonical == b.canonical


def _value_class(v: Value) -> str:
    return "num" if v.type in ("money", "number") else v.type


def _field_tokens(path: str | None) -> set[str]:
    if not path:
        return set()
    return {_stem(t) for t in re.split(r"[^A-Za-z]+", re.sub(r"\[\d+\]", "", path).lower()) if t and t not in _STOP and t not in {"id"}}


def _field_affinity(claim_text: str, field_path: str | None) -> int:
    claim_stems = {_stem(t) for t in _tokens(claim_text)}
    return sum(1 for f in _field_tokens(field_path) if any(_same_token(f, c) for c in claim_stems))


def _successful(result: LedgerEntry | None) -> bool:
    return result is not None and result.meta.get("status", "ok") == "ok" and result.meta.get("enforcement") != "denied"


# --- RT009 phantom action -----------------------------------------------------------------

def check_phantom_action(claim: Claim, ledger: Ledger, entries: list[LedgerEntry] | None = None) -> Verdict | None:
    """An action the agent says it took must have a tool call with a
    successful result earlier in the ledger. Negated and conditional
    clauses are not claims of having acted."""
    if claim.type != "action" or claim.source != "agent_output" or claim.negated or claim.conditional:
        return None
    rows = entries if entries is not None else ledger.entries
    calls = [e for e in rows if e.kind == "tool_call" and e.seq < claim.seq]
    if not calls:
        return Verdict(claim.id, "contradicted", RULE_IDS["phantom"], "phantom", [], f"no tool was called before this claim: {claim.text!r}")
    scored = sorted(((tool_matches_claim(c.tool_name, claim, require_verb=True), c) for c in calls), key=lambda t: (-t[0], -t[1].seq))
    best_score = scored[0][0]
    if best_score == 0:
        return Verdict(claim.id, "contradicted", RULE_IDS["phantom"], "phantom", [c.id for c in calls[-3:]],
                       f"no tool call matches {claim.text!r}; tools called: {sorted({c.tool_name or 'tool' for c in calls})}")
    candidates = [c for score, c in scored if score == best_score]
    claim_keys = {v.key() for v in claim.structured_values if v.type in ("money", "id", "date")}
    if claim_keys and len(candidates) > 1:
        candidates.sort(key=lambda c: (-len(claim_keys & {v.key() for v in c.values}), -c.seq))
    failed: list[LedgerEntry] = []
    for call in candidates:
        result = ledger.result_for(call)
        if _successful(result):
            return Verdict(claim.id, "grounded", None, None, [call.id, result.id], f"{call.tool_name} ran and returned a result")
        if result is not None:
            failed.append(result)
    if failed:
        call = candidates[0]
        return Verdict(claim.id, "contradicted", RULE_IDS["phantom"], "failed_action", [call.id, failed[0].id],
                       f"{call.tool_name} was called but did not succeed (status {failed[0].meta.get('status')}); the agent says it did")
    call = candidates[0]
    return Verdict(claim.id, "contradicted", RULE_IDS["phantom"], "no_result", [call.id],
                   f"{call.tool_name} was called but no result came back before the claim")


# --- RT010 result fidelity -------------------------------------------------------------------

def _matched_results(claim: Claim, ledger: Ledger, entries: list[LedgerEntry]) -> list[LedgerEntry]:
    results = [e for e in entries if e.kind == "tool_result" and e.seq < claim.seq and e.content_captured]
    if not results:
        return []
    scored = [(tool_matches_claim(r.tool_name, claim), r) for r in results]
    best = max(s for s, _ in scored)
    if best > 0:
        return sorted((r for s, r in scored if s == best), key=lambda r: -r.seq)
    return sorted(results, key=lambda r: -r.seq)[:1]


def _local_nouns(claim: Claim, value: Value) -> set[str]:
    """The word a value hangs on: the reference noun the extractor saw
    ("order 8812" -> order), else the word just before it ("score of 12"
    -> score)."""
    if value.extra.get("noun"):
        return {_stem(str(value.extra["noun"]))}
    if value.start is not None and claim.char_span:
        offset = value.start - claim.char_span[0]
        if offset > 0:
            before = _tokens(claim.text[:offset])
            if before:
                return {_stem(t) for t in before[-2:]}
    return set()


def _target_field(claim: Claim, value: Value, same_class: list[tuple[LedgerEntry, Value]]) -> tuple[LedgerEntry, Value] | None:
    """Which result field the claim's value refers to, or None when that
    cannot be said with confidence. Statuses always refer to the object's
    status; a lone amount refers to a lone amount field; ids need a noun
    that names the field ("order 8812" against order_id)."""
    klass = _value_class(value)
    nouns = _local_nouns(claim, value)
    by_affinity = sorted(same_class, key=lambda t: (-len(nouns & _field_tokens(t[1].field)), -t[0].seq))
    if nouns & _field_tokens(by_affinity[0][1].field):
        return by_affinity[0]
    distinct_fields = {t[1].field for t in same_class}
    claim_same_class = [v for v in claim.structured_values if _value_class(v) == klass]
    if klass == "status":
        # One status word against one status field is a comparison; two status
        # words in a clause ("approved ... verified") need a noun to pick the field.
        if len(claim_same_class) == 1 and len(distinct_fields) == 1:
            return same_class[0]
        return None
    if klass in ("num", "date") and len(distinct_fields) == 1:
        return same_class[0]
    if klass == "id" and len(distinct_fields) == 1 and len(claim_same_class) == 1 and not value.extra.get("supported"):
        return same_class[0]
    return None


def check_result_fidelity(claim: Claim, ledger: Ledger, entries: list[LedgerEntry] | None = None, tol: Tolerances | None = None) -> list[Verdict]:
    """Values the agent states must match the field the tool returned."""
    tol = tol or Tolerances()
    if claim.source != "agent_output" or claim.type not in ("result", "factual", "action") or claim.negated:
        return []
    rows = entries if entries is not None else ledger.entries
    results = _matched_results(claim, ledger, rows)
    if not results:
        return []
    # Does the clause name the tool (its verb or object)? If not, the latest
    # result is only a fallback, and a value found anywhere the agent looked is grounded.
    claim_stems = {_stem(t) for t in _tokens(claim.text)}
    field_stems = {f for r in results for rv in r.values for f in _field_tokens(rv.field)}
    specific = max(tool_matches_claim(r.tool_name, claim) for r in results) > 0 or any(
        _same_token(c, f) for c in claim_stems for f in field_stems)
    grounding = [e for e in rows if e.kind in GROUNDING_KINDS and e.seq < claim.seq and e.content_captured and e.kind != "tool_result"]
    all_grounding = [e for e in rows if e.kind in GROUNDING_KINDS and e.seq < claim.seq and e.content_captured]
    verdicts: list[Verdict] = []
    for value in claim.structured_values:
        if value.type not in ("money", "number", "id", "date", "status"):
            continue
        klass = _value_class(value)
        if klass == "id":
            # An id the user or a document gave is not the agent's invention,
            # so it is never compared against an unrelated id field.
            value = Value(value.type, value.canonical, value.raw, field=value.field, start=value.start, end=value.end,
                          extra={**value.extra, "supported": bool(_supporting(value, grounding, tol))})
        same_class = [(r, rv) for r in results for rv in r.values if _value_class(rv) == klass]
        if not same_class:
            continue
        match = next(((r, rv) for r, rv in same_class if _same_value(value, rv, tol)), None)
        if match:
            verdicts.append(Verdict(claim.id, "grounded", None, None, [match[0].id], f"{value.raw!r} matches {match[1].field or 'the result'}",
                                    field=match[1].field, value=value.canonical))
            continue
        if not specific:
            # The clause names neither the tool nor one of its fields, so the
            # latest result cannot be said to be what the clause is about.
            elsewhere = _supporting(value, all_grounding, tol)
            if elsewhere:
                verdicts.append(Verdict(claim.id, "grounded", None, None, [elsewhere[-1].id], f"{value.raw!r} appears in {elsewhere[-1].kind} {elsewhere[-1].id}", value=value.canonical))
            continue
        target = _target_field(claim, value, same_class)
        if target is None:
            continue
        result, expected = target
        sub = values_conflict(value, expected) or {"num": "numerical", "id": "identifier", "date": "temporal", "status": "status"}[klass]
        verdicts.append(Verdict(claim.id, "contradicted", RULE_IDS["fidelity"], sub, [result.id],
                                f"the agent said {value.raw!r} but {result.tool_name or 'the tool'} returned {expected.raw!r} for {expected.field or 'that field'}",
                                field=expected.field, value=value.canonical, expected=expected.canonical))
    return verdicts


# --- RT011 hallucinated promise ------------------------------------------------------------------

def check_promise(claim: Claim, ledger: Ledger, entries: list[LedgerEntry] | None = None, tol: Tolerances | None = None) -> list[Verdict]:
    """A commitment needs a tool result, instruction, document or approval
    that carries the promised value or timeline."""
    tol = tol or Tolerances()
    if claim.type != "commitment" or claim.source != "agent_output":
        return []
    rows = entries if entries is not None else ledger.entries
    grounding = [e for e in rows if e.kind in GROUNDING_KINDS and e.seq < claim.seq and e.content_captured]
    checkable = [v for v in claim.structured_values if v.type in ("duration", "weekday", "date", "money", "number")]
    if not checkable:
        return [Verdict(claim.id, "unverifiable", None, "no_value", [], f"no checkable value in {claim.text!r}")]
    verdicts: list[Verdict] = []
    for value in checkable:
        support = [e for e in grounding if any(_same_value(value, ev, tol) for ev in e.values)]
        if not support and value.type == "duration" and value.extra.get("upper"):
            upper = Value("duration", value.extra["upper"], value.raw)
            support = [e for e in grounding if any(_same_value(upper, ev, tol) for ev in e.values)]
        if support:
            verdicts.append(Verdict(claim.id, "grounded", None, None, [support[-1].id], f"{value.raw!r} appears in {support[-1].kind} {support[-1].id}", value=value.canonical))
        else:
            verdicts.append(Verdict(claim.id, "unsupported", RULE_IDS["promise"], "promise", [], f"nothing the agent saw supports {value.raw!r} in {claim.text!r}", value=value.canonical))
    return verdicts


# --- RT012 argument grounding and RT013 stale grounding ----------------------------------------------

def _supporting(value: Value, grounding: list[LedgerEntry], tol: Tolerances) -> list[LedgerEntry]:
    return [e for e in grounding if any(_same_value(value, ev, tol) for ev in e.values)]


def _stale(value: Value, support: list[LedgerEntry], grounding: list[LedgerEntry], tol: Tolerances) -> tuple[LedgerEntry, Value] | None:
    """A later tool result for the same tool and field with a different
    value supersedes the entry that supports this one."""
    for entry in support:
        if entry.kind != "tool_result":
            continue
        fields = {ev.field for ev in entry.values if _same_value(value, ev, tol) and ev.field}
        for later in grounding:
            if later.seq <= entry.seq or later.kind != "tool_result" or later.tool_name != entry.tool_name:
                continue
            for lv in later.values:
                if lv.field in fields and _value_class(lv) == _value_class(value) and not _same_value(value, lv, tol):
                    if not any(_same_value(value, ev, tol) for ev in later.values):
                        return later, lv
    return None


def check_argument_grounding(claim: Claim, ledger: Ledger, entries: list[LedgerEntry] | None = None, tol: Tolerances | None = None,
                             schema: dict | None = None) -> list[Verdict]:
    """Every money, id, email and date argument of a tool call must trace to
    something the agent saw before the call. ``schema`` maps a tool name to
    ``{"required": [...], "fields": {name: type}}`` when the registry knows it."""
    tol = tol or Tolerances()
    if claim.type != "action" or claim.source != "tool_call":
        return []
    rows = entries if entries is not None else ledger.entries
    grounding = [e for e in rows if e.kind in GROUNDING_KINDS and e.seq < claim.seq and e.content_captured]
    verdicts: list[Verdict] = []
    spec = (schema or {}).get(claim.tool_name or "")
    if spec:
        present = {v.field.split(".")[0] for v in claim.structured_values if v.field}
        call_entry = next((e for e in rows if e.id == claim.entry_id), None)
        if call_entry is not None and isinstance(call_entry.parsed, dict):
            present = set(call_entry.parsed.keys())
            for name in spec.get("required") or []:
                if name not in present:
                    verdicts.append(Verdict(claim.id, "contradicted", RULE_IDS["argument"], "schema", [call_entry.id], f"{claim.tool_name} requires {name!r}, which is missing", field=name))
            for name, expected_type in (spec.get("fields") or {}).items():
                if name in call_entry.parsed and not _type_ok(call_entry.parsed[name], expected_type):
                    verdicts.append(Verdict(claim.id, "contradicted", RULE_IDS["argument"], "schema", [call_entry.id],
                                            f"{claim.tool_name}.{name} should be {expected_type}, got {type(call_entry.parsed[name]).__name__}", field=name))
    for value in claim.structured_values:
        if value.type not in GROUNDED_ARG_TYPES and not (value.type == "number" and value.field and _field_tokens(value.field) & {"amount", "total", "price", "fee", "balanc", "limit"}):
            continue
        support = _supporting(value, grounding, tol)
        if support:
            stale = _stale(value, support, grounding, tol)
            if stale:
                later, lv = stale
                verdicts.append(Verdict(claim.id, "contradicted", RULE_IDS["stale"], "stale", [support[-1].id, later.id],
                                        f"{claim.tool_name}.{value.field} uses {value.raw!r} from {support[-1].id}, but {later.tool_name} later returned {lv.raw!r}",
                                        field=value.field, value=value.canonical, expected=lv.canonical))
            else:
                verdicts.append(Verdict(claim.id, "grounded", None, None, [support[-1].id], f"{value.field} = {value.raw!r} appears in {support[-1].kind} {support[-1].id}",
                                        field=value.field, value=value.canonical))
            continue
        # Nothing matches. Does the ledger hold a different value for the same field?
        klass = _value_class(value)
        rivals = [(e, ev) for e in grounding for ev in e.values if _value_class(ev) == klass and ev.field and _field_tokens(ev.field) & _field_tokens(value.field)]
        if not rivals and value.type == "id":
            noun = _field_tokens(value.field)
            rivals = [(e, ev) for e in grounding for ev in e.values if ev.type == "id" and noun and _stem(str(ev.extra.get("noun", ""))) in noun]
        if rivals:
            rivals.sort(key=lambda t: -t[0].seq)
            entry, rival = rivals[0]
            sub = values_conflict(value, rival) or {"num": "numerical", "id": "identifier", "date": "temporal", "email": "email"}.get(klass, klass)
            verdicts.append(Verdict(claim.id, "contradicted", RULE_IDS["argument"], sub, [entry.id],
                                    f"{claim.tool_name}.{value.field} = {value.raw!r} conflicts with {rival.raw!r} in {entry.kind} {entry.id}",
                                    field=value.field, value=value.canonical, expected=rival.canonical))
        else:
            verdicts.append(Verdict(claim.id, "unsupported", RULE_IDS["argument"], "ungrounded", [],
                                    f"{claim.tool_name}.{value.field} = {value.raw!r} appears nowhere in what the agent saw", field=value.field, value=value.canonical))
    return verdicts


def _type_ok(value, expected: str) -> bool:
    table = {"string": str, "str": str, "number": (int, float), "integer": int, "int": int, "boolean": bool, "bool": bool, "object": dict, "array": list}
    want = table.get(str(expected).lower())
    if want is None:
        return True
    if want is int and isinstance(value, bool):
        return False
    return isinstance(value, want)


def check_stale_claim(claim: Claim, ledger: Ledger, entries: list[LedgerEntry] | None = None, tol: Tolerances | None = None) -> list[Verdict]:
    """A stated value that traces only to a superseded tool result."""
    tol = tol or Tolerances()
    if claim.source != "agent_output" or claim.type not in ("result", "factual", "action", "commitment") or claim.negated:
        return []
    rows = entries if entries is not None else ledger.entries
    grounding = [e for e in rows if e.kind in GROUNDING_KINDS and e.seq < claim.seq and e.content_captured]
    verdicts = []
    for value in claim.structured_values:
        if value.type not in ("money", "number", "id", "date", "status"):
            continue
        support = _supporting(value, grounding, tol)
        stale = _stale(value, support, grounding, tol) if support else None
        if stale:
            later, lv = stale
            verdicts.append(Verdict(claim.id, "contradicted", RULE_IDS["stale"], "stale", [support[-1].id, later.id],
                                    f"the agent said {value.raw!r}, which {support[-1].tool_name or support[-1].kind} returned earlier, but {later.tool_name} later returned {lv.raw!r}",
                                    field=lv.field, value=value.canonical, expected=lv.canonical))
    return verdicts


# --- all of Layer 0 -------------------------------------------------------------------------

def run_layer0(ledger: Ledger, claims: list[Claim], *, entries: list[LedgerEntry] | None = None, tol: Tolerances | None = None,
               schema: dict | None = None) -> list[Verdict]:
    """Every Layer 0 check over every claim. ``entries`` may be the chained
    entries of a multi-agent trajectory; the default is the ledger's own."""
    tol = tol or Tolerances()
    out: list[Verdict] = []
    for claim in claims:
        phantom = check_phantom_action(claim, ledger, entries)
        if phantom:
            out.append(phantom)
        fidelity = check_result_fidelity(claim, ledger, entries, tol)
        out.extend(fidelity)
        stale = check_stale_claim(claim, ledger, entries, tol)
        # A stale verdict replaces a fidelity contradiction on the same value: the
        # agent did not invent the number, it used an old one.
        promise = check_promise(claim, ledger, entries, tol)
        for s in stale:
            out = [v for v in out if not (v.claim_id == s.claim_id and v.rule_id == RULE_IDS["fidelity"] and v.value == s.value)]
            promise = [v for v in promise if not (v.label == "grounded" and v.value == s.value)]
            out.append(s)
        out.extend(promise)
        out.extend(check_argument_grounding(claim, ledger, entries, tol, schema))
    return out

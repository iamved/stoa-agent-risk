"""Evidence resolution: for one claim, the ledger entries that could support
or refute it, trimmed to a checker's token budget.

A text checker is fast and on-distribution when it sees the refund API
response, not six thousand tokens of trace. So evidence is ranked: the
tool result the claim is about, then entries that share one of its values,
then instructions and documents whose sentences share its words, then
approvals. Excerpts keep the sentences that matter and carry the entry hash
so they can be verified against the trace after redaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from .claims import Claim, split_sentences
from .layer0 import _stem, _tokens, tool_matches_claim
from .ledger import GROUNDING_KINDS, Ledger, LedgerEntry

RELATIONS = ("matched_result", "matched_call", "value_overlap", "instruction", "document", "approval", "handoff")


@dataclass
class Evidence:
    entry_id: str
    kind: str
    relation: str
    excerpt: str
    hash: str
    tool_name: str | None = None
    score: float = 0.0
    tokens: int = 0
    fields: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return {"entry_id": self.entry_id, "kind": self.kind, "relation": self.relation, "excerpt": self.excerpt, "hash": self.hash,
                "tool_name": self.tool_name, "score": self.score, "tokens": self.tokens, "fields": list(self.fields)}


def estimate_tokens(text: str) -> int:
    """Four characters per token, the usual rough budget."""
    return max(1, (len(text) + 3) // 4) if text else 0


def _overlap_sentences(text: str, stems: set[str], *, max_sentences: int = 3) -> str:
    """The sentences of ``text`` that share a stem with the claim, best first."""
    if not text:
        return ""
    scored = []
    for start, end in split_sentences(text):
        sentence = text[start:end]
        hits = sum(1 for t in _tokens(sentence) if _stem(t) in stems)
        if hits:
            scored.append((-hits, start, sentence))
    scored.sort()
    return " ".join(s for _, _, s in scored[:max_sentences])


def _trim(text: str, budget_tokens: int) -> str:
    limit = max(16, budget_tokens * 4)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def resolve_evidence(claim: Claim, ledger: Ledger, *, entries: list[LedgerEntry] | None = None, token_budget: int = 512,
                     max_items: int = 6) -> list[Evidence]:
    """Ranked evidence for ``claim`` within ``token_budget`` tokens in total."""
    rows = entries if entries is not None else ledger.entries
    before = [e for e in rows if e.seq < claim.seq and e.content_captured and e.kind in GROUNDING_KINDS + ("tool_call",)]
    if claim.source == "tool_call":
        before = [e for e in before if e.kind != "tool_call"]
    claim_keys = {v.key() for v in claim.structured_values}
    stems = {_stem(t) for t in _tokens(claim.text)}
    candidates: list[Evidence] = []
    for entry in before:
        shared_keys = claim_keys & {v.key() for v in entry.values}
        fields = sorted({v.field for v in entry.values if v.field and v.key() in claim_keys})
        tool_score = tool_matches_claim(entry.tool_name, claim) if entry.tool_name else 0
        if entry.kind == "tool_result" and (tool_score > 0 or shared_keys):
            relation, score = "matched_result", 10 + tool_score + 2 * len(shared_keys)
            excerpt = entry.text_view
        elif entry.kind == "tool_call" and (tool_score > 0 or shared_keys):
            relation, score = "matched_call", 6 + tool_score + len(shared_keys)
            excerpt = f"{entry.tool_name}: {entry.text_view}"
        elif shared_keys:
            relation, score = "value_overlap", 5 + len(shared_keys)
            excerpt = _overlap_sentences(entry.text_view, stems) or entry.text_view
        elif entry.kind == "system_prompt":
            excerpt = _overlap_sentences(entry.text_view, stems)
            if not excerpt:
                continue
            relation, score = "instruction", 3
        elif entry.kind == "retrieved_doc":
            excerpt = _overlap_sentences(entry.text_view, stems)
            if not excerpt:
                continue
            relation, score = "document", 3
        elif entry.kind == "approval":
            relation, score = "approval", 2
            excerpt = entry.text_view
        elif entry.kind == "handoff_in":
            excerpt = _overlap_sentences(entry.text_view, stems) or entry.text_view
            relation, score = "handoff", 2
        else:
            continue
        # Later entries win ties: the freshest result is the one the claim should reflect.
        candidates.append(Evidence(entry.id, entry.kind, relation, excerpt, entry.hash, entry.tool_name, score + entry.seq / 10000.0, 0, fields))
    candidates.sort(key=lambda e: -e.score)
    out: list[Evidence] = []
    remaining = token_budget
    for item in candidates:
        if len(out) >= max_items or remaining <= 0:
            break
        share = remaining if len(out) == 0 else max(remaining // 2, 32)
        item.excerpt = _trim(item.excerpt, min(share, remaining))
        item.tokens = estimate_tokens(item.excerpt)
        remaining -= item.tokens
        out.append(item)
    return out


def evidence_context(evidence: list[Evidence]) -> list[str]:
    """Context passages for a text checker, one per evidence item."""
    return [f"[{e.kind}{' ' + e.tool_name if e.tool_name else ''}] {e.excerpt}" for e in evidence if e.excerpt]

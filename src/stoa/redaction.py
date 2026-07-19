"""Secret redaction: raw secrets must never leave process memory.

Every detected secret is replaced with a short prefix plus a SHA-256
fingerprint before any snippet, report, annotation, or log line is built.
"""

from __future__ import annotations

import math
from hashlib import sha256

from .rules import SECRET_PATTERN


def redact_secret(secret: str) -> str:
    """Replace a secret with a stable, safe representation."""
    fingerprint = sha256(secret.encode()).hexdigest()[:12]
    prefix = secret[:6]
    return f"{prefix}…[REDACTED:{fingerprint}]"


def redact_line(line: str) -> str:
    """Redact every secret-shaped token in a line of source text."""
    return SECRET_PATTERN.sub(lambda match: redact_secret(match.group(0)), line)


def shannon_entropy(value: str) -> float:
    """Bits of entropy per character; low values indicate placeholders."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())

"""Signing keys for the trace chain, with an explicit *grade* per key.

Python's standard library has no Ed25519, and the SDK core must stay
stdlib-only. So a key is one of three grades, and every record names the
grade it was signed under:

- ``none``        no key configured. Records are still hash-chained, so an
                  edit or a deleted line is detectable, but anyone who can
                  edit the file can also recompute the chain.
- ``hmac-sha256`` a shared secret (stdlib ``hmac``). Tamper-evident to
                  everyone who holds the secret; the verifier needs it too.
- ``ed25519``     a private key via the optional ``cryptography`` package
                  (``pip install stoa-agent-risk[runtime]``). Publicly
                  verifiable: the public key travels in the trace header.

Key material comes from ``configure(signing_key=...)`` or the
``STOA_SIGNING_KEY`` environment variable, in one of these forms::

    hmac:<hex or base64 secret>
    ed25519:<64 hex chars, the private seed>
    file:<path>            a file whose first line is one of the above

Loading never raises into the customer's process: a bad key degrades to
grade ``none`` with one warning, matching the exporter's fail-open rule.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import warnings
from pathlib import Path

KEY_ENV = "STOA_SIGNING_KEY"
GRADES = ("none", "hmac-sha256", "ed25519")


class Signer:
    """What the chain needs from a key. ``sign``/``verify`` take the record
    hash as lowercase hex and return/accept the signature as hex."""

    grade = "none"
    fingerprint: str | None = None
    public_key_hex: str | None = None

    def sign(self, hash_hex: str) -> str | None:
        return None

    def verify(self, hash_hex: str, sig_hex: str | None) -> bool:
        return sig_hex is None


class HmacSigner(Signer):
    grade = "hmac-sha256"

    def __init__(self, secret: bytes) -> None:
        if not secret:
            raise ValueError("empty HMAC secret")
        self._secret = secret
        self.fingerprint = _fingerprint(b"hmac-sha256:" + hashlib.sha256(secret).digest())

    def sign(self, hash_hex: str) -> str:
        return hmac.new(self._secret, hash_hex.encode("ascii"), hashlib.sha256).hexdigest()

    def verify(self, hash_hex: str, sig_hex: str | None) -> bool:
        return bool(sig_hex) and hmac.compare_digest(self.sign(hash_hex), sig_hex)


class Ed25519Signer(Signer):
    grade = "ed25519"

    def __init__(self, seed: bytes) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self._key = Ed25519PrivateKey.from_private_bytes(seed)
        public = _ed25519_public_bytes(self._key.public_key())
        self.public_key_hex = public.hex()
        self.fingerprint = _fingerprint(b"ed25519:" + public)

    def sign(self, hash_hex: str) -> str:
        return self._key.sign(hash_hex.encode("ascii")).hex()

    def verify(self, hash_hex: str, sig_hex: str | None) -> bool:
        return Ed25519Verifier(bytes.fromhex(self.public_key_hex or "")).verify(hash_hex, sig_hex)


class Ed25519Verifier(Signer):
    """Verify-only: built from the public key the trace header carries."""

    grade = "ed25519"

    def __init__(self, public: bytes) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        self._key = Ed25519PublicKey.from_public_bytes(public)
        self.public_key_hex = public.hex()
        self.fingerprint = _fingerprint(b"ed25519:" + public)

    def verify(self, hash_hex: str, sig_hex: str | None) -> bool:
        if not sig_hex:
            return False
        try:
            self._key.verify(bytes.fromhex(sig_hex), hash_hex.encode("ascii"))
            return True
        except Exception:  # noqa: BLE001 - any failure is "not verified"
            return False


def _ed25519_public_bytes(public_key) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def _fingerprint(material: bytes) -> str:
    return hashlib.sha256(material).hexdigest()[:16]


def _decode_secret(text: str) -> bytes:
    text = text.strip()
    try:
        return bytes.fromhex(text)
    except ValueError:
        pass
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return text.encode("utf-8")


def parse_key(spec: str | None) -> Signer:
    """A ``Signer`` for a key spec, or the no-key signer. Raises
    ``ValueError`` on a malformed spec; callers that must not raise use
    :func:`load_signer`."""
    if not spec:
        return Signer()
    spec = spec.strip()
    scheme, _, rest = spec.partition(":")
    if scheme == "file":
        text = Path(rest).read_text(encoding="utf-8").splitlines()
        return parse_key(text[0] if text else "")
    if scheme == "hmac":
        return HmacSigner(_decode_secret(rest))
    if scheme == "ed25519":
        try:
            import cryptography  # noqa: F401
        except ImportError as exc:
            raise ValueError(
                "ed25519 signing needs the 'cryptography' package: "
                "pip install stoa-agent-risk[runtime]"
            ) from exc
        seed = bytes.fromhex(rest)
        if len(seed) != 32:
            raise ValueError("ed25519 seed must be 32 bytes (64 hex chars)")
        return Ed25519Signer(seed)
    raise ValueError(f"unknown signing key scheme {scheme!r}; expected hmac:, ed25519: or file:")


def load_signer(spec: str | None = None) -> Signer:
    """Fail-open key loading for the SDK: a bad or missing key means grade
    ``none`` and one warning, never an exception."""
    try:
        return parse_key(spec or os.environ.get(KEY_ENV))
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"stoa.runtime: signing key not usable ({exc}); traces are hash-chained "
            "but unsigned (grade none).",
            RuntimeWarning,
            stacklevel=2,
        )
        return Signer()


def verifier_for_header(header: dict, spec: str | None = None) -> Signer:
    """The signer a verifier should check a file against: ed25519 from the
    public key in the header; HMAC from the caller's secret; else none."""
    grade = header.get("key_grade") or "none"
    if grade == "ed25519" and header.get("signer_public_key"):
        try:
            return Ed25519Verifier(bytes.fromhex(header["signer_public_key"]))
        except Exception:  # noqa: BLE001
            return Signer()
    if grade == "hmac-sha256":
        signer = parse_key(spec or os.environ.get(KEY_ENV)) if (spec or os.environ.get(KEY_ENV)) else Signer()
        return signer
    return Signer()

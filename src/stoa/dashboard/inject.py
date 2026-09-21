"""Turn an envelope plus the compiled template into one HTML file.

Security properties, each covered by a test in ``tests/test_dashboard_pipeline.py``:

* **Safe embedding.** The envelope is serialized with ``<``, ``>``, ``&``,
  U+2028 and U+2029 escaped as ``\\uXXXX``, so no snippet can close the JSON
  script tag, open a comment, or break a JavaScript string. The placeholder
  token is replaced with :meth:`str.replace` exactly once; no regular
  expression ever runs over envelope-derived text.
* **Hash-pinned CSP.** Every inline ``<script>`` and ``<style>`` in the
  template is fixed at build time, so its SHA-256 is computed here and listed
  in a ``Content-Security-Policy`` meta tag with ``default-src 'none'`` and
  ``connect-src 'none'``. The data tag is ``application/json`` and never
  executes, so it is not (and need not be) allowed. No ``'unsafe-inline'``
  for scripts, ever, matching the legacy report.
* **Defense-in-depth redaction.** Snippets are already redacted by the
  scanner at match time; every string in the envelope is passed through the
  same redactor again before embedding, because the file is meant to be
  shared.
* **Determinism.** Same envelope and template produce byte-identical HTML.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from ..redaction import redact_line
from ..report_json import _atomic_write
from .template import load_template

PLACEHOLDER = "__STOA_DASHBOARD_DATA__"
_CHARSET_META = '<meta charset="utf-8" />'

# These run over the TEMPLATE only (fixed, built from this repository's own
# source), never over anything derived from a scanned repository.
_INLINE_SCRIPT = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.DOTALL | re.IGNORECASE)
_INLINE_STYLE = re.compile(r"<style\b[^>]*>(?P<body>.*?)</style>", re.DOTALL | re.IGNORECASE)
_SRC_ATTR = re.compile(r"\bsrc\s*=", re.IGNORECASE)
_JSON_TYPE = re.compile(r"""\btype\s*=\s*["']application/json["']""", re.IGNORECASE)


class DashboardError(RuntimeError):
    """The template does not have the shape the injector requires."""


def escape_json_for_script(document: object) -> str:
    """JSON text safe to place inside ``<script type="application/json">``."""
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def redact_document(value: object) -> object:
    """Deep copy with every string passed through the scanner's redactor."""
    if isinstance(value, str):
        return redact_line(value)
    if isinstance(value, list):
        return [redact_document(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_document(v) for k, v in value.items()}
    return value


def _sha256_source(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def inline_hashes(template: str) -> tuple[list[str], list[str]]:
    """(script hashes, style hashes) for every executable inline block."""
    scripts = []
    for match in _INLINE_SCRIPT.finditer(template):
        attrs = match.group("attrs")
        if _SRC_ATTR.search(attrs) or _JSON_TYPE.search(attrs):
            continue
        scripts.append(_sha256_source(match.group("body")))
    styles = [_sha256_source(m.group("body")) for m in _INLINE_STYLE.finditer(template)]
    return scripts, styles


def content_security_policy(template: str) -> str:
    scripts, styles = inline_hashes(template)
    script_src = " ".join(scripts) if scripts else "'none'"
    style_src = " ".join(styles) if styles else "'none'"
    return (
        "default-src 'none'; "
        f"script-src {script_src}; "
        f"style-src {style_src}; "
        "img-src data:; font-src data:; connect-src 'none'; "
        "base-uri 'none'; form-action 'none'"
    )


def render_dashboard(envelope: dict, template: str | None = None) -> str:
    """The finished HTML. Raises :class:`DashboardError` on a malformed template."""
    if template is None:
        template = load_template()
    if template.count(PLACEHOLDER) != 1:
        raise DashboardError(
            f"template must contain the data placeholder exactly once (found {template.count(PLACEHOLDER)})"
        )
    if template.count(_CHARSET_META) != 1:
        raise DashboardError("template must contain exactly one charset meta tag")
    if "Content-Security-Policy" in template:
        raise DashboardError("template must not carry its own Content-Security-Policy")

    meta = f'<meta http-equiv="Content-Security-Policy" content="{content_security_policy(template)}" />'
    html = template.replace(_CHARSET_META, _CHARSET_META + meta, 1)
    payload = escape_json_for_script(redact_document(envelope))
    return html.replace(PLACEHOLDER, payload, 1)


def write_dashboard(envelope: dict, output_path: Path, template: str | None = None) -> None:
    _atomic_write(Path(output_path), render_dashboard(envelope, template))


def write_dashboard_json(envelope: dict, output_path: Path) -> None:
    """The dashboard's data on its own, for a dashboard page to open from disk.

    Redacted exactly like the embedded copy, because it is just as shareable.
    Needs no template, so it works in a checkout that has not built the UI."""
    text = json.dumps(redact_document(envelope), ensure_ascii=False, indent=2) + "\n"
    _atomic_write(Path(output_path), text)


def is_envelope(document: dict) -> bool:
    return isinstance(document.get("schema"), str) and document["schema"].startswith("stoa-dashboard/")

# stoa-engine — Risk Underwriting Engine (Phase 1 MVP)

A standalone sidecar that converts a canonical **submission** JSON file into
carrier-ready **underwriting evidence packets** — clean, Stoa-branded PDFs plus
a performance workbook. It reads JSON in and writes files out. It does **not**
import from, or modify, any other Stoa code.

> **Scope.** This module formats Stoa's own risk-scan and simulation evidence
> into structured underwriting packets that a company's officers review, sign,
> and submit through normal broker channels. It renders **original** document
> layouts informed by publicly known industry formats; it does not reproduce
> any insurer's actual form, wording, branding, or trademarks, and it transmits
> nothing to anyone. All example data is for a **fictional** company and is
> watermarked as such on every page.

## Architecture

```
 submission.json ─▶ models.py (pydantic v2)  ── validate
        │
        ▼
   adapters.py  ──reads──▶ adapters/*.map.yaml   (declarative field maps, no logic)
        │  resolve(JSONPath) + evidence quadruple + completeness gaps
        ▼
   pipeline.py  ──orchestrates──▶ render/
        │                           ├─ pdf.py    (Jinja2 templates + WeasyPrint)
        │                           ├─ xlsx.py   (openpyxl, 3 sheets)
        │                           └─ evidence.py (submission copy + SHA-256 manifest)
        ▼
   ./packet/  packet_posture.pdf · packet_performance.pdf ·
              performance_data.xlsx · submission.json · manifest.json
```

Every layer is driven by one canonical schema. Business/carrier logic lives in
YAML, never in code.

## The evidence quadruple

Every posture answer carries `{value, evidence, confidence, scan_hash}`. This is
the product's explainability feature and is never dropped downstream.

| confidence      | meaning                                                        | tristate label            |
|-----------------|----------------------------------------------------------------|---------------------------|
| `confirmed`     | verified against scanned code evidence                         | Confirmed                 |
| `attested`      | human-declared; **no** code verification                      | Confirmed (attested)      |
| `not_confirmed` | evidence does not affirm the statement                         | Not confirmed             |
| `contradicted`  | a declaration conflicts with scanned evidence → **red banner** | Not confirmed             |
| `unknown`       | no evidence observed                                           | Unknown                   |

**Absence of evidence is always `unknown`, never a "no".** An `unknown` required
field is not silently dropped — it becomes a gap owned by `human`
(or `scan` when the field is code-derived).

## Install

Requires Python ≥ 3.11 and WeasyPrint's native libraries (pango, cairo,
gdk-pixbuf, libffi). On macOS: `brew install pango gdk-pixbuf libffi`.

```bash
make install        # creates .venv and installs the package (+ dev extras)
```

## Commands

```bash
stoa-engine export   --input examples/sample_submission.json --template posture|performance|all --out ./packet/
stoa-engine gaps     --input examples/sample_submission.json --template all
stoa-engine validate --input examples/sample_submission.json
```

- `export` renders the packet. `--template all` writes both PDFs plus the
  performance workbook, the submission copy, and the SHA-256 manifest.
- `gaps` prints the gap report (declared gaps + adapter completeness gaps).
- `validate` runs Pydantic validation only.

## Demo

```bash
make demo           # export the sample with --template all, then print gaps
```

Produces, in `./packet/`:

- `packet_posture.pdf` — posture questionnaire packet
- `packet_performance.pdf` — performance questionnaire packet
- `performance_data.xlsx` — 3 sheets (Performance Data · Covered Models · Aggregates)
- `submission.json` — the exact input, copied for audit
- `manifest.json` — SHA-256 of every output file

Each PDF has a cover page (evidence-class legend), a per-agent plain-English
one-pager for an underwriter, the pre-filled answers grouped by section with a
confidence badge and evidence ref per answer, and a review & sign-off page
splitting **code-verified** from **human-attested** fields.

## Adding a new template (YAML only)

1. Drop a new `adapters/<name>.map.yaml`. Each field:

   ```yaml
   - field_id: system.hitl
     section: "4 · AI system posture"
     label: "Human-in-the-loop review before actions take effect"
     source: "$.systems[*].posture.hitl"   # JSONPath; $.systems[*] expands per system
     required: true
     render: tristate                        # checkbox | text | currency | list | tristate
   ```

2. That's it — `stoa-engine export --template <name>` picks it up. No code change.
   The loader validates that every `required: true` field resolves or emits a gap.

## Tests

```bash
make test
```

Covers: schema round-trip on the sample; adapter completeness (every required
field resolves or is gapped); renderer smoke tests (files exist, xlsx has 3
sheets, each PDF > 5 pages, watermark present when `sample_data` is true, and the
manifest hashes every output).

## Non-goals (this MVP)

No registry integration, no web UI, no live simulator hookup, no filling of any
third party's PDF forms, and no transmission of anything to anyone. Read JSON →
write files.

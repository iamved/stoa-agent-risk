# Underwriting evidence

Insurers pricing AI risk send a questionnaire; the applicant fills it in by
hand and self-attests. Stoa can pre-fill it from evidence instead. The
**underwriting-evidence export** renders an AI Model Risk Assessment (modeled
on the Munich RE aiSure™ template) as a self-contained, offline HTML view
with a print-to-PDF button.

```bash
stoa export stoa-registry.json --underwriting \
  --underwriting-config applicant.toml \
  --out submission.html
```

It is also reachable from the **Generate underwriting evidence** button in the
[report](/docs/report).

## Where the fields come from

The technical sections are populated from the scan, not typed by hand:

| Questionnaire field | Sourced from |
|---|---|
| Robustness / adversarial testing | injection & output-handling findings (AI001 / AI002) |
| Code-quality checks | the scan running in CI with `stoa diff` drift gating |
| Agent inventory & critical findings | the registry |
| Post-deployment monitoring | observability evidence (a CTRL004 gap, or its absence) |
| Drift mitigation | capability drift tracked via [`stoa diff`](/docs/diff) |
| Insurance schedule inputs | elevated-exposure dimensions + economic-authority findings (DECL003 / RT002) |

## The applicant supplies their own numbers

Identity and real model-performance figures come from a small TOML the
applicant owns. When it is present, the form shows those figures as
**provided by the applicant**; with no config, it falls back to a clearly
labeled **sample** so placeholder numbers are never passed off as measured
data.

```toml
[identity]
company       = "Acme Payments Inc"
contact_name  = "Dana Okafor"
model_name    = "Acme Transaction-Risk Agent"
# … any identity field

[[performance]]
metric  = "Ground-truth accuracy"
value   = "98.1%"
cadence = "Monthly, held-out labeled set"
# … the applicant's own measured figures
```

A copy-paste template ships at
[`examples/underwriting-config.example.toml`](https://github.com/iamved/stoa-agent-risk/blob/main/examples/underwriting-config.example.toml).

## The workflow

```
enterprise runs stoa scan
   → fills applicant.toml (identity + real metrics)
   → stoa export --underwriting --underwriting-config applicant.toml
   → submission.html — their company, their numbers, scan-sourced technical fields
   → applicant confirms and signs the PDF
   → forwards it to the underwriter
```

The form carries a template attribution and an applicant-to-confirm note —
standard pre-filled-form hygiene, not a claim of audited data. Like every
Stoa output it renders fully offline and makes no network request.

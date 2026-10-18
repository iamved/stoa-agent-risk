# Ingesting an external audit chain (stub)

Not implemented. This note fixes how an external, signed audit record of
approvals and policy decisions (HumanOS and products like it) would map onto
`stoa-trace/1.1` so a later connector has nothing to invent.

## What maps where

| External record | Stoa span | Fields |
|---|---|---|
| An approval request raised before an action | `approval` with `attrs.granted = false`, `attrs.pending = true` | `approved_by` is the external actor reference, keyed, never in clear; `approval_method` names the external channel |
| The decision (granted or denied) | `approval` with `attrs.granted` set, `attrs.latency_ms` from request to decision | the span id is what the following `action` cites in `approval_span_id` |
| A verify-before-execute check | `action` with `enforcement` set (`allowed` or `denied`) and `attrs.policy_rules` naming the external rule ids | an external deny becomes `enforcement = "denied"` and the action carries `status = "error"` |
| A guardrail firing | `attrs.flags` on the affected span, using Stoa's flag names where one fits and the external name otherwise | the flag engine keeps computing its own flags beside them |
| A credential revocation | `agent_run` closing with `attrs.revoked = true` | subsequent spans for that agent are flagged `no_registry` until a scan re-admits it |

## Chain and signature

The external chain stays external. Each ingested record carries the
external record id in `attrs.external_ref` and the external signature
fingerprint in `attrs.external_signer`; Stoa's own chain (`prev_hash`,
`hash`, `sig`) covers the ingested span as written, so a verifier can
check both independently. Stoa never re-signs the external payload.

## What is out of scope

Sharing Stoa's data outward (a "trust snapshot" for insurers or partners)
is a separate decision with its own consent model; this stub covers reading
only.

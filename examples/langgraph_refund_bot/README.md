# Refund bot, traced

A LangGraph refund agent with three tools (`lookup_order`, `issue_refund`,
`send_email`) and an `interrupt()` before refunds above 500 EUR. The only
Stoa code is one callback handler passed in `config`.

```
make demo
```

runs a scan, five scripted sessions (one above the approval threshold, one
duplicate refund, one call to a tool the scan never listed), then
`stoa runtime verify` and `stoa runtime reconcile`, and prints the RT
findings the merge produced.

Without `langgraph` installed the same nodes run through a small in-file
sequencer that drives the handler the way LangGraph would, so the demo
works on a bare install; with it installed the real graph runs.

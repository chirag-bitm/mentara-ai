# Milestone 5.5 Phase D — fake provider and provider-neutral execution

Date: 2026-09-13

Status: COMPLETE. Included in the current Phase I automated gate.

## Outcome

Phase D completes the provider-neutral execution seam using a deterministic
`FakePredictionProvider`. The fake supports immediate and delayed results,
provider failures, cancellation-aware and cancellation-suppressing races, and
request inspection without network access or quota.

`PredictionProviderExecutor` converts one immutable runtime attempt into one
bounded provider request. `LikelyNextTurnPolicy` keeps trusted application
instructions separate from JSON-serialized untrusted active-turn and memory
content. It explicitly forbids answers, rationale, tools, search, actions,
policy changes, secrets and fact verification.

## Correctness boundaries

- A fake or real provider sees only `PredictionProviderRequest`; it cannot own
  the turn engine, transcript, memory, answer runtime or browser state.
- Provider execution cannot exceed the configured candidate or output-token
  ceilings. Wrong types, extra candidates and malformed domain output fail
  closed through sanitized provider-neutral categories.
- One attempt creates one provider call. There is no hidden retry.
- Cancellation saves work where possible; identity/revision/fingerprint/memory
  equality remains the authoritative stale-completion gate.
- Provider failures become prediction `failed` snapshots and do not escape into
  STT, conversation, memory or answer processing.

## Verification

Tests cover deterministic results, delayed completion, explicit failures,
timeouts, cancellation, cancellation suppression, rapid correction, topic
replacement, output bounds, request provenance, prompt injection separation,
one-active-call ownership and stale-result rejection. The current combined
gate passes 381 backend tests.

No dependency was added and no cloud call was made for Phase D verification.


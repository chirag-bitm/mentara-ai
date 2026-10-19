# Milestone 3 Phase B — Turn engine

## Status

Complete. The standalone turn engine and its single cancellable deadline runtime
are implemented and tested without WebSocket integration.

## Turn finalization policy

- Default merge window: 250 ms after the latest canonical final.
- Purpose: join immediately adjacent canonical finals when a provider splits one
  semantic prompt.
- A new partial from the same source inside the window continues the active turn
  and replaces the deadline.
- Source or speaker change finalizes an all-final previous turn immediately.
- Stop flushes an all-final pending turn immediately.
- Partial-only text is discarded on a terminal flush; M3 never fabricates a
  canonical final.
- The window is bounded to at most 2,000 ms by the policy contract.

## Determinism and replay

- The engine consumes only `CanonicalUtterance` values.
- Transcript sequences are used only for idempotence/provenance; turn sequence
  is independent.
- Duplicate/stale canonical events are ignored.
- Turn IDs derive from session ID plus allocated turn sequence.
- Finalized turns are immutable and retained in a snapshot.
- The active snapshot exposes evolving text, canonical provenance, continuity
  and its pending deadline for a future predictive consumer.

## Task lifecycle

`ConversationTurnRuntime` owns at most one deadline task. It can pause without
discarding engine state for browser resume, resume an overdue deadline, flush on
Stop, or cancel terminal state. Tests inject clock and sleeper behavior so timer
semantics do not depend on wall-clock sleeps.

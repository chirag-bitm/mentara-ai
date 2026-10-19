# Milestone 3 Phase A — Conversation domain contracts

## Status

Complete. This phase adds domain contracts and deterministic identity only. It
does not integrate the conversation layer into `/ws/transcribe`.

## Decisions

- Canonical transcript state remains authoritative and immutable to M3.
- Turn order is independent from transcript event sequence.
- Turn IDs are deterministic UUIDv5 values derived from Mentara session ID and
  turn sequence. Assistance IDs are derived from finalized turn IDs.
- A finalized turn records aligned canonical utterance IDs and their final
  transcript sequences for provenance.
- Timing is application-observed. No word-level or provider-fabricated speech
  timestamps are introduced.
- The latest source-final time, derived turn-final time and measured
  `transcript_final_to_turn_ms` are explicit.
- Finalized turns are frozen dataclasses. Active turns have a separate read-only
  contract with pending deadline visibility for a future predictive consumer.
- Continuity is explicitly `normal` or `degraded` and travels with both active
  and finalized turns.
- Assistance decisions use a small provider-neutral contract and do not invent
  probabilistic confidence.
- Detailed routing/topic classes remain out of M3.

## Added contracts

- `ActiveConversationTurn`
- `ConversationTurn`
- `ConversationSnapshot`
- `ContinuityQuality`
- `TurnFinalizationReason`
- `AssistanceDecision`
- `AssistanceKind`
- deterministic turn and detection ID derivation

## Compatibility

All additions live below `app.services.conversation`. Existing transcript,
provider, WebSocket and frontend contracts are unchanged in Phase A.

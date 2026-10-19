# Milestone 5 Phase A — provider-neutral memory domain

## Status

Complete. Phase A introduced a bounded, provider-neutral in-RAM conversation
memory domain without changing runtime composition.

## Contracts and invariants

- `ConversationMemory` accepts immutable finalized `ConversationTurn` values.
- Stable turn identity and logical session identity are validated before commit.
- Duplicate and stale observations do not change state or revision.
- A successful commit increments `memory_revision` exactly once.
- `MemorySnapshot`, entries and provenance are frozen, tuple-backed views.
- Verbatim conversation and reserved derived memory are always untrusted.
  `FUTURE_VERIFIED_CONTEXT` is a separate reserved source for M6.
- Each entry retains stable source-turn, source-utterance and transcript-sequence
  provenance plus continuity and deterministic bounded topic terms.

## Bounds

Defaults are 256 retained turns, 160,000 combined text characters and 4,000
characters per entry. Oldest entries are evicted deterministically until both
storage bounds hold. Eviction and forward sequence gaps remain explicit in the
snapshot and degrade continuity honestly.

## Verification

Thirteen focused domain tests cover first/many turns, duplicate/replay, stale and
cross-session input, invalid stable identity, identical text with distinct IDs,
revision behavior, immutable snapshots, both hard limits, eviction, continuity,
prompt injection, unverified claims, reset and logical deletion. The full
backend suite after Phase A passed 229 tests.

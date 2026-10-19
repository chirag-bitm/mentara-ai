# Milestone 5 Phase C — deterministic context planner

## Status

Complete. Phase C added a replaceable local `ContextPlanner` with no provider
call, embedding dependency or vector database.

## Selection policy

1. Always reserve budget for the current/source turn.
2. Include up to four immediately preceding retained turns for short follow-up
   resolution.
3. Score non-recent turns by exact overlap of normalized bounded topic terms.
4. Rank by overlap, then recency, cap at four and serialize selected older turns
   chronologically.
5. Apply the existing 2,000-character per-turn and 6,000-character total answer
   context ceilings.

No-match queries add no older context. The deterministic terms are retrieval
metadata only: they remain untrusted and are neither verified entities nor a
Conversation Radar implementation.

## Verification

Focused tests cover hard bounds, four common short-reference forms, long-range
named-topic return, no match, ranking/order, non-overlap, eviction continuity,
prompt injection provenance and unavailable source handling. The full backend
suite after Phase C passed 249 tests.

# Milestone 5.5 Phase E — additive browser events and minimal UI

Date: 2026-09-13

Status: COMPLETE. Target-Windows visual verification remains Phase J.

## Outcome

Phase E adds a minimal advisory `Likely next` surface only after backend
lifecycle semantics were stable. `prediction.snapshot` is additive to all M1–M5
events. It carries bounded candidates, operational readiness and content-free
metrics but does not alter transcript, conversation, memory or answer events.

The pure prediction reducer keeps one live prediction separate from
`answerOrder` and `answersById`. It accepts only a newer revision for the same
stable prediction/provenance, accepts a genuinely newer active turn, rejects
cross-session and stale replay, and immediately removes visible candidates on
invalidation. Runtime validation fails closed on malformed wire JSON.

## Browser and backpressure policy

- Prediction events are coalesced by stable prediction ID in the existing
  bounded outbound writer; newer revisions replace pending older revisions.
- Transcript/status/terminal answer events retain priority over prediction.
- Internal `memory_revision` is not exposed to the browser. A memory change is
  projected as the generic advisory invalidation `context_changed`.
- Socket close, Stop, start and unrecoverable error reset live prediction UI.
- Resume replays transcript/turn/answer truth but never replays or regenerates
  prediction merely because a browser reattached.
- Prediction state is never written to `localStorage`, `sessionStorage`,
  IndexedDB, disk or a database.

## Product boundary

The UI labels candidates as bounded guesses—not detected questions, verified
facts or answers. It does not offer promotion, answer generation or full
Conversation Radar behavior.

## Verification

The frontend gate passes 28 tests, ESLint, strict TypeScript and the production
build. Tests cover duplicates, stale revisions, newer-turn replacement,
cross-session rejection, provenance changes, invalidation, malformed payloads
and reset behavior. Backend event/outbound tests are included in the 381-test
combined backend gate.


# Milestone 5.5 Phase I — recovery, privacy and stress verification

Date: 2026-09-14

Status: COMPLETE. Phase J target-Windows/provider checkpoint is next.

## Outcome

Phase I closes the automated race, recovery, privacy and cost-bound matrix. No
new authority is given to prediction: it remains a logical-session-owned,
RAM-only side-car whose failure is isolated from all M1–M5 domains.

## Verified scenarios

- no active turn, first/identical/corrected/provider-final input, new turn and
  source/speaker/provenance changes;
- stable prediction identity, monotonic input revisions/attempts/snapshot
  revisions and stale completion rejection;
- 40-update correction coalescing, minimum-call interval, one active task,
  per-turn/per-session ceilings, timeout and no retry;
- malformed output, authentication/configuration/transient/rate-limit errors,
  cancellation and a prediction event-sink failure;
- memory-revision race, bounded context, bad snapshot/planner provenance,
  degraded continuity and STT rotation;
- Stop, reset, expiry, backend shutdown, browser disconnect/resume, no replay
  event/call and zero leaked prediction tasks;
- prompt-injection-shaped content, absence of speech/candidate bodies from
  normal logs and content-free sink error logging;
- prediction non-mutation of canonical transcript, finalized turns,
  ConversationMemory and authoritative Answer History;
- bounded outbound coalescing under a prediction revision flood;
- malformed frontend wire payload, stale/cross-session reducer rejection and no
  browser persistence;
- exact `PREDICTION_ENABLED=false` fallback with no provider construction,
  runtime task or browser event.

An enabled WebSocket integration test now proves a rate-limited predictor does
not interrupt canonical finalization, question detection, one authoritative
answer or later healthy transcription. A second integration test proves browser
resume replays no prediction and makes no new predictor call until a genuine
post-gap, normal-continuity active turn arrives.

## Automated gate

- Backend: 381 passed; two known dependency deprecation warnings.
- Frontend: 28 passed.
- Frontend ESLint: passed.
- Strict TypeScript: passed.
- Production build: passed.
- M5 300-turn/120-minute memory evaluation: all checks passed.
- M5.5 deterministic prediction evaluation: all checks passed.
- Speculative-generation decision gate: all checks passed; deferred.

The next step is one short target-Windows run that also executes the prepared
four-call non-sensitive Gemini benchmark. Closeout and the final sanitized ZIP
must wait for those actual results.


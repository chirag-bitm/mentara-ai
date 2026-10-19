# Milestone 3 Phase D — Runtime, replay and frontend integration

## Status

Complete. Runtime integration passed automated verification and the final
target-Windows checkpoint recorded in `MILESTONE_3_PHASE_E.md`.

## Runtime flow

The verified M2 transcript path remains authoritative. Each canonical utterance
is sent to the browser first, then observed by the downstream conversation
runtime:

```text
STTProvider
  -> TranscriptResult
  -> TranscriptAggregator
  -> CanonicalUtterance
  -> transcript.partial / transcript.final
  -> ConversationTurnRuntime
  -> ConversationTurnEngine
  -> turn.finalized
  -> AssistanceDetectionEngine
  -> question.detected (positive decisions only)
```

M3 never mutates canonical transcript history and never consumes raw Gemini
messages. It adds no provider or model call.

## Browser event contracts

`turn.finalized` contains stable turn identity/order, aligned source utterance
IDs and final transcript sequences, source/speaker metadata, application-observed
timing, finalization reason, continuity quality and transcript-to-turn latency.

`question.detected` contains stable detection identity, its source turn ID and
sequence, `question` or `request`, and turn-to-detection latency. It deliberately
does not repeat transcript text or expose invented confidence.

Existing `status`, `session.ready`, `transcript.partial`, `transcript.final`,
`error` and `pong` semantics are unchanged.

## Finalization and resilience behavior

- The default configurable merge window is 250 ms and is bounded to 0–2,000 ms.
- Consecutive canonical finals from the same source inside the window form one
  turn. Source/speaker change finalizes the previous all-final turn immediately.
- Stop drains provider results, then flushes an all-final pending turn before
  `stopped`. Partial-only state is cancelled rather than promoted to invented
  final text.
- Fatal provider failure marks pending derived state degraded, flushes an
  all-final turn, emits any positive detection, then emits the existing error.
- Browser disconnect cancels the browser-bound timer task but retains active
  engine state inside the bounded logical-session registry. Resume rearms the
  same deadline; an overdue turn finalizes once with the same deterministic ID.
- Resume replays stored transcript state, then finalized turns and positive
  detections using their original IDs. Frontend reducers apply this idempotently.
- Provider rotation keeps the same `TranscriptionSession`; M2 duplicate-final
  suppression therefore prevents duplicate turns and detections.
- Session Stop, fatal error, reset or registry expiry removes/cancels remaining
  M3 state. Both route peer tasks are cancelled and joined on every exit path.

## Continuity

Provider degradation or browser loss marks an active turn degraded. If no turn
is active, degradation applies to the next canonical-final contribution and is
cleared after that final is acknowledged. The detector still evaluates the turn;
the quality signal is preserved for future M4 behavior.

## Frontend

The frontend adds one pure conversation reducer and a minimal diagnostic panel.
It displays the latest meaningful request/question, backend-measured latencies
and continuity quality. It does not independently classify text. Cross-session,
stale, duplicate and invalid-reference derived events are ignored.

## Automated verification

The complete automated gate was rerun during final M3 closeout on 2026-09-12
and passed:

- 127 backend tests;
- 14 frontend reducer/reconnection tests;
- frontend ESLint;
- frontend TypeScript validation and Next.js production build.

Tests use fake providers/events and consume no Gemini quota. Coverage includes
direct and request-style prompts, follow-ups, multi-sentence prompts, negative
controls, partial correction, final-without-partial, duplicate finals, nearby
segment merge, multiple turns, source/speaker propagation, degraded continuity,
stable IDs/order, snapshot replay, browser resume, provider replacement,
duplicate final at rotation, Stop, disconnect/pause/resume, provider failure,
registry expiry/reset, malformed events, feature disable and timer cleanup.

The curated detector corpus demonstrates deterministic behavior only; it does
not establish general natural-language accuracy.

## Rollback

Set `CONVERSATION_ANALYSIS_ENABLED=false` and restart the backend to restore the
verified M2 transcription-only runtime without removing code or changing browser
audio/STT behavior. Existing clients may also ignore the additive M3 event types.

A full source rollback must restore the M2 checkpoint and remove M3-only files;
extracting an older ZIP over the newer tree is not sufficient because it leaves
new files behind.

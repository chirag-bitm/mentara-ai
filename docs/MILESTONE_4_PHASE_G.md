# Milestone 4 Phase G — End-to-end verification

## Status

Complete on the target Windows machine on 2026-09-13.

## Automated gate

- Backend: 216 tests passed; two dependency deprecation warnings only.
- Frontend: 21 tests passed.
- Frontend ESLint passed.
- Frontend TypeScript check passed.
- Frontend production build passed.

Fake-provider tests cover the required answer identity, lifecycle, stream
ordering, duplicate/stale handling, completion/empty completion, pre/post-text
failure, malformed streams, timeouts, cancellation, A/B/C supersession, Stop,
disconnect/resume/replay, no replay call, expiry/reset cleanup, STT rotation,
answer-failure isolation, feature-disabled behavior, slow-browser backpressure,
bounded buffering, cross-session rejection, bounded context, missing personal
context and prompt-injection separation.

## Short physical Windows checkpoint

The user observed:

1. A normal statement produced transcript/turn state and no answer.
2. Meaningful direct questions and request-style prompts produced exactly one
   incrementally streamed answer.
3. New speech continued to transcribe while and after answer generation.
4. A newer meaningful request followed latest-request-wins semantics.
5. Browser refresh restored transcript/conversation/answer state without a
   duplicate answer or provider request.
6. Stop released the microphone. When used during generation, the answer became
   `cancelled`, retained already-visible partial text, accepted no late text and
   correctly showed no completion-total latency.
7. No unhandled backend exception or traceback was observed.

Representative observations included transcript-final-to-turn latency of
250–266 ms and turn-to-detection latency of 0 ms. Real answer first-text latency
varied between 2,454 ms and 7,406 ms during the supplied manual checks. The Stop
case showed first text at 4,360 ms before cancellation.

## Corrections validated during the checkpoint

- The secure PowerShell key prompt now rejects pasted control characters and
  guides the user to right-click/Shift+Insert. The initial failure was caused by
  Ctrl+V being captured as U+0016 in a raw hidden console prompt.
- Stateless Interactions input uses the SDK's current structured `user_input`
  form. Safe diagnostics expose category/status without printing provider bodies
  or credentials.
- Registry expiry reschedules an early Windows timer callback instead of losing
  cleanup; the deterministic test proves no orphan answer task.
- The STT rotation timing test uses a larger test-only scheduler margin and
  passed a 100-run stress check without changing production rotation behavior.
- Answer policy explicitly requests plain text so the minimal UI does not show
  raw Markdown markers.
- The deterministic request detector was audited beyond a one-phrase patch. It
  now recognizes a bounded set of explicit request verbs, including `give` and
  `provide`, with positive and negative tests and an exact fake-provider
  WebSocket integration case for “Give eight short differences…”.

## Honest limitations observed

- STT once transcribed “short” as “show”; the request remained detectable and
  was answered. This is the documented provider/audio accuracy boundary, not an
  answer-engine identity failure.
- One resumed turn displayed degraded continuity, which is correct because
  audio during a browser gap is not buffered.
- Provider/network latency varied materially even though local M3 processing
  remained responsive.

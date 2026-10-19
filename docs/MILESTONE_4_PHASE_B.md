# Milestone 4 Phase B — Independent answer runtime

## Status

Complete and verified through deterministic tests, the real provider checkpoint
and the target-Windows lifecycle test.

## Ownership and concurrency

- `AnswerRuntime` belongs to the logical `TranscriptionSession`, not a browser
  WebSocket lease or an STT provider connection.
- The M3 `on_turn_finalized` callback performs only local domain work and calls
  the synchronous, non-waiting `request_answer` handoff. Provider startup and
  streaming run in an independent asyncio task.
- One positive detection maps to one stable answer ID and at most one initial
  provider request. Repeated submission returns the existing snapshot.
- One generation may be active per logical session. Latest meaningful request
  wins: an active older answer becomes `superseded` and its provider task is
  cancelled before the replacement runs.
- Completed answers and all other terminal states are immutable.
- M4 performs no automatic provider retry. This bounded zero-retry policy avoids
  duplicated or contradictory visible output. A later explicit attempt can use
  the existing logical answer identity plus an incremented attempt number.

## Cleanup and isolation

- Stop, session reset, fatal STT termination and registry expiry cancel active
  generation. Terminal browser-lease teardown and backend shutdown await task
  cleanup before returning.
- Provider stream closure is bounded; provider cancellation propagates through
  the async stream/client where supported.
- Browser disconnect only detaches the event sink. The logical-session task may
  continue during the bounded 30-second resume lease.
- Answer failure changes only answer state; healthy STT, transcript, turn and
  detection processing continue.
- Timeout, malformed stream and sanitized provider failures terminate honestly
  as `failed`, never `completed`.

## Instrumentation

Normal content-free logs record:

- `question_detected_to_answer_request_ms`
- `answer_request_to_provider_start_ms`
- `answer_request_to_first_text_ms`
- `question_detected_to_first_text_ms`
- `answer_generation_total_ms`
- safe aggregate usage counts when supplied

Transcript, question and answer bodies are absent from normal latency logs.

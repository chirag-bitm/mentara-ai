# Milestone 2 handoff — Canonical Transcript Engine + Realtime Resilience

## Outcome

Milestone 2 is complete and verified on the target Windows machine as of
2026-09-10. Mentara now owns one canonical transcript across partial corrections,
finite-lived STT-provider connections and brief browser WebSocket interruptions.
The implementation preserves the Milestone 1 audio, network, privacy and Windows
operation contracts.

## What each phase delivered

| Phase | High-level result |
| --- | --- |
| A1 | Built and deterministically tested the backend canonical transcript domain model and aggregator. |
| A2 | Routed provider results through the aggregator before emitting browser transcript events. |
| A3 | Replaced append-only frontend transcript state with an idempotent canonical reducer. |
| B0 | Analyzed the provider duration limit and fixed the bounded rotation, recovery, privacy and rollback policy. |
| B1 | Separated Mentara logical-session lifetime from provider-connection lifetime. |
| B2 | Added bounded, provider-neutral connection rotation with final-boundary preference and honest degraded states. |
| B3 | Added bounded browser reconnection, opaque resume tokens and canonical snapshot replay. |
| B4 | Hardened combined cancellation/failure paths and verified provider rotation plus browser recovery together. |

## Final architecture

- The backend is the only authority for canonical transcript state.
- A Mentara logical session, browser WebSocket and STT-provider connection are
  separate lifetimes.
- `TranscriptAggregator` owns utterance identity, revisions, session sequence,
  ordering, finalization and bounded exact-duplicate suppression.
- `TranscriptionSession` owns canonical state across provider generations.
- `RotatingSTTProvider` replaces provider connections behind the unchanged
  provider-neutral `STTProvider` contract.
- `InMemoryTranscriptionSessionRegistry` retains detached sessions for a bounded
  30-second browser-resume window with an exclusive lease.
- The frontend reducer renders canonical events and applies replay idempotently.

## Stable contracts

- Signed little-endian PCM16, 16 kHz, mono audio in approximately 100 ms chunks.
- Binary browser-to-FastAPI audio frames over `/ws/transcribe`.
- Existing `transcript.partial` and `transcript.final` event names.
- Additive canonical event fields: session ID, utterance ID, sequence, revision,
  source, speaker role and application-observed timing.
- Backend-only provider credentials and independent `/ws/health` diagnostics.
- Existing Windows setup, configuration, start and verify scripts.

## Verification evidence

Target Windows/Python 3.11.9 automated verification passed:

- 61 backend tests;
- 8 frontend canonical/reconnect tests;
- frontend lint;
- frontend TypeScript and production build;
- final result: `All automated checks passed.`

The final approximately 12-minute real-Gemini checkpoint also passed with the
production-effective 540-second rotation interval and 10-second boundary wait:

- one provider rotation completed and returned to Live;
- canonical history remained present, ordered and unduplicated;
- new speech worked after provider rotation;
- one active browser refresh resumed the same logical session;
- snapshot replay restored earlier finals exactly once;
- new speech worked after browser recovery;
- Stop released the microphone cleanly;
- no unhandled backend exception was observed.

## Continuity and accuracy semantics

Mentara does not claim impossible zero-loss continuity. Audio is buffered only
in a bounded 20-chunk in-memory FIFO during provider switching and is not queued
while the browser WebSocket is unavailable. The UI reports degraded continuity
when nearby speech may be incomplete.

Provider wording accuracy is a separate limitation. Mixed Hindi/English speech,
distant microphones, background voices, noise and unclear pronunciation can be
misheard even while canonical identity, order and recovery are correct. Before
Milestone 3 changes code, evaluate language hints, transcription mode and input
conditions using repeatable non-sensitive samples and provider-neutral accuracy
metrics. Do not tune production defaults from one anecdotal transcript.

## Privacy and persistence

- Provider API keys remain backend-only.
- Raw audio is not persisted.
- Normal logs do not contain transcript text.
- Automated tests use fakes and consume no provider quota.
- Canonical state is memory-only; a backend restart cannot restore it.
- Resume tokens are temporary local capabilities, not authentication.

## Normal Windows commands

From `C:\Users\Chirag Gupta\mentara-ai\mentara-ai`:

```powershell
.\configure-gemini.bat
.\start-backend.bat
.\start-frontend.bat
.\verify.bat
```

The effective production defaults used by the final longevity test were
`GEMINI_ROTATION_INTERVAL_SECONDS=540` and
`GEMINI_ROTATION_FINAL_WAIT_SECONDS=10`.

## Rollback

Preserve `backend/.env` and `frontend/.env.local`, then restore a known verified
package into a clean project copy. Extracting an older archive over a newer tree
is not a complete rollback because it cannot remove newer-only files.

## Milestone boundary

Milestone 2 is closed. Do not add question detection, LLM answers,
summarization, retrieval, system audio, local Whisper, Tauri, desktop overlay,
authentication, databases, queues, billing or subscriptions as part of this
handoff. A later explicit task must perform pre-Milestone 3 analysis—including a
controlled STT-accuracy gate—before implementation begins.

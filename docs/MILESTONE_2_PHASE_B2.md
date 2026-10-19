# Milestone 2 Phase B2 — controlled provider rotation

## Outcome

Phase B2 lets one Mentara transcription session continue across replaceable
Gemini connections. The canonical transcript remains backend-owned and keeps
the same session ID, utterance rules, monotonic sequence and finalized history.

No browser event name, audio format, API-key boundary, Windows command or UI
layout changed.

## Runtime policy

- Rotate the active Gemini provider after 540 seconds.
- Prefer the next `transcript.final` boundary, waiting at most 10 seconds.
- Rotate anyway after that wait so the connection remains below the documented
  600-second provider-session maximum.
- Buffer at most 20 current audio chunks, approximately two seconds.
- On overflow, discard the oldest unsent chunk and emit one degraded warning.
- Retry only transient network/server failures.
- Use at most three replacement attempts with delays of 0.25, 0.5 seconds.
- Stop immediately for provider-declared authentication, quota or protocol
  errors; do not spend quota in an unbounded retry loop.

These defaults are built into the backend, so an existing `backend/.env` does
not need manual editing. Optional settings are documented in `.env.example`.

## Implementation

- `backend/app/services/stt/rotation.py` adds the provider-neutral rotating
  wrapper, lifecycle events, bounded in-memory FIFO and retry policy.
- `backend/app/services/stt/base.py` distinguishes transient and fatal provider
  errors without changing the `STTProvider` methods.
- `backend/app/services/stt/gemini.py` classifies 5xx provider failures as
  transient and other provider error payloads, including 429, as fatal.
- `backend/app/services/stt/factory.py` composes the Gemini adapter with rotation
  and validates that the configured rotation window ends below 600 seconds.
- `backend/app/api/websocket.py` maps rotation lifecycle events into the B1
  session state machine and existing browser status contract.
- `backend/app/core/config.py` contains safe defaults and a configuration switch
  for emergency rollback.

## Continuity semantics

A planned rotation after a finalized utterance preserves all canonical history
and begins the next provider generation in the same Mentara session.

Mentara does not claim exactly-once audio delivery across a network failure. If
the provider fails after accepting audio but before producing a transcript, the
backend cannot prove whether those samples were processed. It therefore emits
`degraded` and preserves all transcript state that was already canonicalized.

The audio buffer exists only in process memory and is discarded when the
session ends. Neither raw audio nor transcript text is added to normal logs.

## Deterministic verification

The Phase B2 test suite uses fake providers and consumes no Gemini quota. It
covers:

- planned rotation after a final boundary;
- forced rotation when no final boundary arrives;
- canonical result continuity across provider generations;
- 20-chunk-style bounded FIFO behavior and oldest-chunk overflow;
- transient interruption plus successful bounded retry;
- retry exhaustion;
- fatal error with no retry;
- stop while a replacement connection is pending;
- factory defaults, emergency disable switch and invalid rotation window;
- Gemini fatal/transient error classification;
- session-generation and browser-status lifecycle mapping.

From the project root with both development servers stopped:

```powershell
.\verify.bat
```

Expected result:

- 43 backend tests pass;
- 5 frontend reducer tests pass;
- frontend lint passes;
- frontend TypeScript and production build pass;
- final line: `All automated checks passed.`

## Target runtime checkpoints

First run a short non-sensitive regression:

1. Start backend and frontend.
2. Start transcription and speak one sentence.
3. Confirm partial text becomes one final segment.
4. Stop and confirm the microphone releases.

After the short test passes, run one approximately 12-minute non-sensitive
session if Gemini quota permits. Around the nine-minute boundary, pause after a
sentence. Confirm the UI briefly shows reconnecting and returns to live/ready,
earlier final text remains, later speech appears in the same transcript and stop
still works. A degraded warning means the nearby words must be treated as
potentially incomplete.

## Migration and rollback

Extract the B2 package over the current verified project folder. Local
`backend/.env` and `frontend/.env.local` are excluded from the package.

For an immediate configuration rollback, add
`GEMINI_ROTATION_ENABLED=false` to `backend/.env` and restart the backend. This
restores single-provider behavior but also restores the provider-duration
limitation.

For a full code rollback, preserve local environment files and cleanly restore
the verified B1 package. Extracting B1 over B2 is not a complete rollback because
ZIP extraction does not delete B2-only files.

## Next phase

Phase B3 will address browser WebSocket reconnection with an in-memory logical
session registry and bounded expiry. It will reuse the B2 provider rotation and
B1 canonical session ownership without adding Redis or PostgreSQL.

# Milestone 2 Phase A2 — canonical WebSocket integration

## Outcome

Phase A2 connects the tested Phase A1 transcript engine to the live
`/ws/transcribe` route. The backend is now the authoritative source of transcript
identity, ordering, revisions and observed timing before any transcript update is
sent to the frontend.

No audio capture, Gemini protocol, UI layout, event name, environment variable or
dependency changed.

## Why this phase exists

Streaming providers may repeat partials, correct earlier text or repeat a final.
Sending those raw messages directly to the browser makes later features depend on
provider quirks. Phase A2 adds a stable Mentara contract between provider output
and frontend state.

At a high level:

1. The STT adapter yields a provider-neutral `TranscriptResult`.
2. The connection's `TranscriptAggregator` applies that result.
3. Empty, identical or bounded duplicate updates produce no browser event.
4. A real state change becomes a canonical partial or final event.
5. The existing frontend continues to display text while accepting the richer
   payload.

## Files changed

- `backend/app/schemas/events.py` defines additive canonical transcript fields and
  converts canonical utterances into browser events.
- `backend/app/api/websocket.py` owns one aggregator for the current logical
  session and routes all provider results through it.
- `frontend/src/types/transcription.ts` mirrors the backend event contract.
- `frontend/src/hooks/use-streaming-transcription.ts` keeps unknown confidence
  compatible with the existing UI model.
- `backend/tests/test_transcript_events.py` verifies JSON-safe schema output.
- `backend/tests/test_transcript_websocket.py` verifies the full coordinator path
  with a fake provider.

## Preserved contracts

- Event names remain `transcript.partial` and `transcript.final`.
- Audio remains signed little-endian PCM16, 16 kHz, mono, in approximately 100 ms
  binary chunks.
- Gemini authentication remains backend-only.
- `/ws/health`, Windows scripts and current UI behavior remain unchanged.
- No raw audio is stored and tests do not consume Gemini quota.

## Canonical event fields

Every transcript event now carries:

- `session_id` and `utterance_id`
- `sequence` and `revision`
- `audio_source` and `speaker_role`
- `text` and `is_final`
- `first_seen_ms` and `last_updated_ms`
- `finalized_ms` only for final events
- `confidence` only when a provider supplies it

Timing is relative to the Mentara session's monotonic clock. It records when the
application observed updates, not exact speech boundaries.

## Automated verification

From the project-root PowerShell terminal with development servers stopped:

```powershell
.\verify.bat
```

Expected result:

- 25 backend tests pass.
- Frontend lint passes.
- Frontend TypeScript and production build pass.
- The final line is `All automated checks passed.`

The two current Starlette/AnyIO deprecation warnings come from test dependencies
and do not indicate an application failure.

## Runtime checkpoint

After automated verification passes, start the backend and frontend in separate
project-root terminals:

```powershell
.\start-backend.bat
```

```powershell
.\start-frontend.bat
```

In Chrome at `http://localhost:3000`:

1. Run the Backend WebSocket check.
2. Start transcription and speak one short, non-sensitive sentence.
3. Confirm changing partial text appears and becomes one stable final line.
4. Stop transcription and confirm the microphone is released.
5. Start and stop a second session.

This live test is required now because Phase A2 changes the runtime WebSocket
payload path. It was not required between A1 implementation and A2 because A1 was
isolated from runtime.

## Deliberate limitations

- Phase A2 creates one logical Mentara session per browser WebSocket connection.
  A later session registry will separate their lifecycles in the running system.
- The frontend accepts canonical fields but does not yet reduce state by
  utterance ID and revision.
- Reconnection, provider rotation, question detection and answer generation are
  outside this phase.

## Next phase

After the Windows automated and runtime checks pass, Phase A3 will implement the
frontend canonical transcript reducer. Realtime reconnection remains a later
phase.

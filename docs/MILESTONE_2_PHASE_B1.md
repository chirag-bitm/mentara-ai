# Milestone 2 Phase B1 — logical session lifecycle foundation

## Outcome

Phase B1 makes a logical Mentara transcription session a concrete backend
component instead of treating the current provider connection as the session.
The canonical aggregator now belongs to `TranscriptionSession`, and provider
connections are counted as replaceable generations.

This phase does not reconnect or rotate Gemini yet. It creates and verifies the
boundary required to do that safely in B2.

## Why this phase exists

The exact Gemini Transcribe Live model has a 10-minute maximum audio session.
Mentara conversations may be longer. Replacing a provider connection must not
replace the Mentara session, erase finalized text, reset sequence numbers or
change utterance identity.

At a high level:

1. One `TranscriptionSession` is created for the current browser run.
2. It owns one long-lived canonical `TranscriptAggregator`.
3. A successful provider connection enters `connected` and increments the
   provider generation.
4. Future reconnecting/recovered generations reuse the same aggregator.
5. Stopped is terminal, preventing accidental session reuse.

## Files changed

- `backend/app/services/transcript/session.py` defines lifecycle state,
  transition rules, provider generation and the combined session snapshot.
- `backend/app/services/transcript/__init__.py` exports the session API.
- `backend/app/api/websocket.py` routes provider results through the logical
  session rather than owning an aggregator directly.
- `backend/app/schemas/events.py` accepts future reconnecting/degraded statuses.
- `frontend/src/types/transcription.ts` mirrors those status values.
- `frontend/src/hooks/use-streaming-transcription.ts` handles future recovery
  states without clearing transcript state.
- `frontend/src/components/transcription-console.tsx` keeps Stop available while
  a provider is reconnecting or degraded.
- `backend/tests/test_transcription_session.py` verifies lifecycle behavior.

## Lifecycle states

- `connecting`: initial provider setup
- `connected`: provider generation is active
- `reconnecting`: replacement is in progress
- `degraded`: session continues but some continuity may be uncertain
- `error`: current recovery policy failed
- `stopped`: terminal user/session shutdown

The browser retains `ready` for the existing initial WebSocket contract.
`reconnecting` and `degraded` are additive status values for B2.

## Automated verification

From the project-root PowerShell terminal with both development servers stopped:

```powershell
.\verify.bat
```

Expected result:

- 31 backend tests pass.
- 5 frontend reducer tests pass.
- Frontend lint passes.
- Frontend TypeScript and production build pass.
- The final line is `All automated checks passed.`

No Gemini quota is consumed by automated verification.

## Runtime checkpoint

Because B1 intentionally preserves current runtime behavior, one short regression
is sufficient after automated verification:

1. Start backend and frontend.
2. Start transcription and speak one non-sensitive sentence.
3. Confirm partial text becomes one final line.
4. Stop and confirm the microphone is released.

## Next phase

Phase B2 will add controlled provider replacement, bounded audio buffering and
fake-provider failure/rotation tests. It will preserve this B1 session object
across every provider generation.

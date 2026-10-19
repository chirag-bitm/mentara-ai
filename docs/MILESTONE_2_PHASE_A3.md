# Milestone 2 Phase A3 — canonical frontend state

## Outcome

Phase A3 completes the canonical transcript path. The backend remains the source
of truth, and the frontend now reduces canonical transcript events instead of
inventing numeric segment IDs and independently appending text.

The visible transcript design, audio path, provider integration and event names
remain unchanged.

## Why this phase exists

A streaming partial is a changing version of one utterance, not a new transcript
line. The backend already communicates this through `utterance_id`, `revision`
and `sequence`. The reducer makes the frontend follow those semantics.

At a high level:

1. The first canonical event binds frontend state to its `session_id`.
2. A new `utterance_id` is recorded once in spoken order.
3. A higher revision replaces that utterance's previous partial state.
4. Finalization replaces the partial with one immutable final utterance.
5. Stale, duplicate, invalid, cross-session or post-final updates are ignored.
6. Starting another transcription explicitly resets frontend transcript state.

## Files changed

- `frontend/src/lib/transcript-reducer.ts` owns canonical frontend state and
  read-only selectors for final and interim rendering.
- `frontend/src/types/transcription.ts` exposes named partial, final and combined
  transcript event types.
- `frontend/src/hooks/use-streaming-transcription.ts` dispatches canonical events
  and resets the reducer on each new run.
- `frontend/src/components/transcription-console.tsx` uses the backend-generated
  utterance ID as the stable React key.
- `frontend/tests/transcript-reducer.test.ts` contains five deterministic tests.
- `frontend/scripts/test-transcript-reducer.mjs` compiles and runs those tests
  using the existing TypeScript and Node installations.
- `scripts/verify.ps1` includes reducer tests and now stops reliably when any
  backend test, frontend test, lint or build command fails.

## Reducer state

The reducer stores:

- the active `sessionId`
- the latest accepted session `sequence`
- utterance IDs in their first-observed order
- the latest canonical event for each utterance ID

The UI derives finalized lines and the current interim line through selectors.
It does not maintain a second competing copy of transcript truth.

## Automated verification

From the project-root PowerShell terminal with development servers stopped:

```powershell
.\verify.bat
```

Expected result:

- 25 backend tests pass.
- 5 frontend reducer tests pass.
- Frontend lint passes.
- Frontend TypeScript and production build pass.
- The final line is `All automated checks passed.`

No Gemini request is made by these tests.

## Runtime checkpoint

After automated verification, start the backend and frontend in separate
project-root terminals:

```powershell
.\start-backend.bat
```

```powershell
.\start-frontend.bat
```

In Chrome:

1. Start transcription and speak one short sentence.
2. Confirm the changing partial is replaced in place and becomes one final line.
3. Stop and confirm the microphone is released.
4. Start a second session and speak a different sentence.
5. Confirm the first session's transcript was cleared and the second sentence
   appears once.

This checkpoint verifies the reducer integration and explicit session reset with
real browser scheduling and Gemini events.

## Deliberate limitations

- One logical Mentara session still maps to one browser WebSocket connection.
- Browser and provider reconnection are not implemented.
- Canonical state is in memory only.
- Question detection, answer generation and system audio remain outside Phase A.

## Next phase

After the Windows automated and runtime checks pass, Phase A is complete. The
next activity is the full Phase B resilience analysis before any reconnection or
provider-rotation implementation begins.

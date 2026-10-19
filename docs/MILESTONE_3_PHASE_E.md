# Milestone 3 Phase E — Target-Windows checkpoint

## Status

Complete. The target-Windows automated gate and short physical-microphone,
browser-resume and clean-Stop checkpoint passed on 2026-09-12. A second
12-minute provider-rotation soak was not required because M3 preserves the
verified audio/provider boundary and exercises rotation/reconnect
deterministically with fake providers.

## Checkpoint

On the target Windows machine:

1. Run `verify.bat` from the project root and confirm 127 backend tests, 14
   frontend tests, lint, TypeScript and production build pass.
2. Start the backend and frontend with the existing scripts and open Chrome at
   `http://localhost:3000`.
3. Start transcription and say one ordinary statement, one direct question and
   one request without a question mark. Use only non-sensitive demo speech.
4. Confirm transcript text remains correct, the analysis panel does not trigger
   for the statement, and it updates once for each meaningful question/request.
5. Confirm the displayed turn order and non-negative latency values look sane.
6. Refresh Chrome once, allow the existing session to resume and confirm the
   last turn/detection is not visually duplicated.
7. Speak one new meaningful prompt after resume, then Stop. Confirm the new turn
   appears once and the microphone indicator is released.
8. Confirm the backend shows no unhandled exception and no transcript text in
   normal analysis log lines.

## Observed target-Windows result

- `verify.bat` passed 127 backend tests, 14 frontend tests, ESLint, TypeScript
  and the Next.js production build.
- An ordinary deployment statement finalized as Turn 1 and logged
  `should_assist=False`.
- A direct Redis-failure question finalized as Turn 2 and logged
  `should_assist=True`.
- `Walk me through your architecture.` finalized as Turn 3 and appeared once as
  the latest meaningful request.
- The pre-refresh UI showed Turn 3, normal continuity and non-negative latency.
- Chrome refresh restored the previous session and transcript without increasing
  the turn number merely because of replay.
- `Give me an example.` finalized once as Turn 4 after resume. The UI preserved
  the preceding three transcript segments, added one new segment and displayed
  degraded continuity, truthfully reflecting the possible browser-gap loss.
- Observed transcript-final-to-turn latency was 250–266 ms, consistent with the
  configured 250 ms merge window plus scheduling overhead. Local deterministic
  detection measured 0 ms in the observed turns.
- Normal analysis logs contained sequence, latency and decision only, with no
  transcript text.
- Stop returned the UI to Ready, released the microphone and produced no
  unhandled backend error.

One initial attempt opened an older M2 frontend still occupying port 3000 while
the M3 frontend moved to port 3001. The backend correctly rejected the 3001
origin under its configured `FRONTEND_ORIGIN=http://localhost:3000` policy. After
stopping the stale frontend and launching the M3 build on port 3000, the complete
checkpoint passed. This was an environment/process conflict, not an M3 runtime
failure.

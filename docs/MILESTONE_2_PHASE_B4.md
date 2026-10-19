# Milestone 2 Phase B4 — combined longevity and failure verification

## Outcome

Phase B4 hardens and verifies the interaction between controlled STT-provider
rotation and browser session recovery. It does not add a feature or change the
Milestone 1 contracts. The backend remains the canonical owner, providers remain
replaceable adapters, the browser remains a rendering/audio client and every
buffer stays bounded and in memory.

The deterministic B4 suite and the approximately 12-minute real-Gemini run on
the target Windows machine are complete. Milestone 2 is closed.

## Provider constraint revalidation

Google's Gemini 3.5 Transcribe Live documentation still specifies PCM16 mono,
16 kHz input, approximately 100 ms chunks and a maximum audio duration of ten
minutes per session. Generic Live API session resumption is not assumed to extend
that model-specific limit. Mentara therefore retains the B2 design: create a
fresh provider adapter before the limit while preserving Mentara-owned canonical
state.

Official references checked on 2026-09-10:

- https://ai.google.dev/gemini-api/docs/live-guide#transcribe-audio
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe-live
- https://ai.google.dev/gemini-api/docs/live-session

## Combined deterministic matrix

The backend suite now verifies these cross-layer paths:

| Scenario | Required result |
| --- | --- |
| Browser disconnect while a replacement provider is connecting | Pending connect is cancelled, adapters close, logical session remains resumable |
| Active partial followed by browser resume | Replay keeps the same utterance ID; later final increments revision and sequence |
| Duplicate provider final immediately after resume | Duplicate emits nothing; the next real utterance uses exactly the next sequence |
| Fatal provider error after resume | One safe `STT_CONNECTION_ERROR`; provider closes and registry entry is removed |
| Malformed browser command after handshake | Session stays usable; command never reaches provider or canonical state |
| Malformed provider JSON/message shape | Safe terminal provider error; no pointless retry loop |
| Stop during reconnect | Replacement is cancelled, all adapters close and no terminal error is fabricated |

Existing B1–B3 tests continue to cover state transitions, registry leases and
expiry, bounded retry/backoff, bounded audio overflow, final-boundary rotation,
forced rotation, snapshot replay and frontend idempotence.

## Defects fixed

Two narrow defects were proven by the new tests and fixed:

1. A non-object JSON command after the valid WebSocket handshake could call
   `.get()` on the wrong value and become an internal backend error. Such input
   is now ignored safely, like existing invalid/unknown text commands.
2. Cancelling the rotating wrapper while its replacement adapter was still in
   `connect()` did not guarantee explicit cancellation and adapter close. The
   replacement connect task and finish watcher are now always cancelled/awaited,
   and an unconnected adapter is always closed.
3. Rotation timing required a new final even when the stream was already silent
   or finalized. The boundary tracker now waits only while a partial utterance is
   active, preventing a safe rotation from being mislabeled as degraded because
   of scheduler timing.

No public schema, audio format, retry limit, buffer size, dependency or provider
selection behavior changed.

## Automated verification

With development servers stopped, run from the project root:

```powershell
.\verify.bat
```

Expected result:

- 61 backend tests pass;
- 8 frontend tests pass;
- frontend lint passes;
- frontend TypeScript and production build pass;
- final line: `All automated checks passed.`

All automated tests use fakes and consume no Gemini quota.

## Target-Windows checkpoint — passed

The checkpoint passed on 2026-09-10 using the production-effective 540-second
rotation interval and 10-second final-boundary wait. The run crossed one normal
provider rotation, refreshed Chrome once while transcription was active,
preserved every earlier final once and in order, accepted new speech after both
recoveries and released the microphone on Stop without an unhandled backend
exception.

The procedure used was:

Use only non-sensitive demo speech. Keep the computer awake and the Chrome tab
open. The session can be mostly silent; a phone timer is sufficient.

1. Start backend and frontend normally, then start transcription.
2. Speak: `B4 checkpoint starts before provider rotation.` Pause until final.
3. Keep the session running. Near 9 minutes, speak and pause after:
   `This sentence creates the boundary for provider rotation.`
4. Confirm the status returns to Live and shows that streaming STT reconnected.
   A brief reconnecting status is expected. A degraded warning is acceptable if
   rotation could not use a final boundary; it must not erase history.
5. Speak: `This sentence is after provider rotation.` Pause until final.
6. Refresh Chrome once while transcription is active. Confirm it reconnects and
   restores every earlier final exactly once.
7. Speak: `This sentence is after browser recovery.` Pause until final.
8. Leave the same logical session running until approximately 12 minutes total,
   then select Stop transcription.

The checkpoint passes when all four final sentences remain once and in order,
the UI returns to Live after both provider rotation and browser refresh, new
speech continues after each recovery, and Stop releases the microphone cleanly.

A wording mismatch is provider accuracy. Erased history, duplicated finals,
sequence reversal, permanent reconnecting state, an unhandled backend exception
or a microphone that remains active after Stop is a B4 failure.

## Extraction and rollback

Extract the B4 package directly over:

`C:\Users\Chirag Gupta\mentara-ai\mentara-ai`

That folder must directly contain `backend`, `frontend`, `docs` and `verify.bat`;
do not create another nested `mentara-ai` folder. Normal overwrite/replace is
expected. Local `backend/.env`, `frontend/.env.local`, virtual environments,
`node_modules` and build output are excluded from the package.

For rollback, preserve the local environment files and cleanly restore the
verified B3 package. Extracting an older package over B4 is not a complete
rollback because it does not remove B4-only files.

## Milestone boundary

This checkpoint passed, `PROJECT_STATE.md` records Milestone 2 as complete and
`docs/MILESTONE_2_HANDOFF.md` is the final handoff. Milestone 3 must begin only
in a later, explicitly authorized task after fresh analysis.

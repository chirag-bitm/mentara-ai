# Milestone 2 — Phase 0 and Phase A1

## What we are building

A provider-neutral canonical transcript model and an isolated backend
`TranscriptAggregator`. This phase does not yet change the verified runtime
WebSocket path.

## Why we need it

Gemini partials are mutable hypotheses and finals are authoritative provider
events. Future turn detection and question detection require one stable Mentara
utterance rather than several UI transcript segments for the same speech.

## Files created

- `docs/MILESTONE_1_HANDOFF.md`
- `docs/MILESTONE_2_PHASE_A1.md`
- `backend/app/services/transcript/__init__.py`
- `backend/app/services/transcript/models.py`
- `backend/app/services/transcript/aggregator.py`
- `backend/tests/test_transcript_aggregator.py`

## Files modified

- `README.md`
- `PROJECT_STATE.md`
- `docs/ARCHITECTURE.md`

## What the code does

- Generates Mentara session and utterance UUIDs.
- Keeps one utterance ID across partial corrections and finalization.
- Assigns monotonic session-wide event sequences.
- Assigns per-utterance revisions starting at 1.
- Ignores empty text and identical duplicate partials.
- Commits final utterances exactly once under the documented duplicate policy.
- Records application-observed monotonic timing.
- Keeps `audio_source` and `speaker_role` extensible for later system audio.
- Keeps confidence optional and never manufactures a value.
- Exposes an immutable session snapshot for later WebSocket integration.

## Commands to run

Use a project-root VS Code PowerShell terminal. Stop the backend and frontend
development servers first, then run:

```powershell
.\verify.bat
```

## Expected result

- 22 backend tests pass: the original 9 plus 13 transcript-aggregator tests.
- Frontend lint passes.
- Frontend production build passes.
- The last line is `All automated checks passed.`

No Gemini quota is used by these tests.

## Troubleshooting

- If Python cannot import `app.services.transcript`, confirm the whole updated
  project was extracted and `backend/app/services/transcript` exists.
- If a timing assertion fails, share the complete assertion and Python version;
  the tests use an injected integer clock and should be deterministic.
- If an original Milestone 1 test fails, stop and fix that regression before
  integrating the aggregator into `/ws/transcribe`.
- Do not start both development servers while `verify.bat` is running.

## Next phase

Phase A2 will extend the existing transcript event payloads and route provider
results through the tested aggregator. Event names and the browser audio contract
will remain unchanged.

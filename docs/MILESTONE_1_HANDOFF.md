# Milestone 1 handoff — Audio + Streaming STT

## Status

Completed and verified end to end on the target Windows machine on 2026-09-09.

## Verified flow

`Microphone → Chrome → AudioWorklet → signed little-endian PCM16 → 16 kHz mono → approximately 100 ms binary chunks → browser WebSocket → FastAPI → STTProvider → GeminiTranscribeProvider → Gemini 3.5 Transcribe Live → transcript.partial/transcript.final → Next.js UI`

## Verified checks

- FastAPI health endpoint and independent `/ws/health` diagnostic.
- Secure backend-only Gemini configuration.
- Chrome microphone permission, capture and visible audio level.
- Real interim and final Gemini transcription in the UI.
- Clean stop and successful second transcription session.
- Nine backend tests.
- Frontend lint, TypeScript checking and production build.
- Root `verify.bat` workflow on Windows.

## Contracts to preserve

- `STTProvider` abstraction and configuration-selected provider factory.
- Signed little-endian PCM16, 16 kHz, mono AudioWorklet output in approximately
  100 ms chunks.
- Binary browser-to-FastAPI audio frames.
- Existing `transcript.partial` and `transcript.final` event names.
- Backend-only provider API keys.
- Provider protocol details isolated behind the STT adapter.
- `/ws/health` remains independent of provider and microphone diagnostics.
- Existing `setup.bat`, `start-backend.bat`, `start-frontend.bat` and
  `verify.bat` entry points.

## Known limitations carried into Milestone 2

- The browser WebSocket, provider connection and transcript lifetime are coupled.
- Gemini Live Transcribe connections have a finite session duration.
- Provider failures do not reconnect automatically.
- The backend does not yet own canonical utterance IDs, revisions, ordering or
  transcript history.
- Live streaming does not provide word-level timestamps or speaker diarization;
  later timing fields must be application-observed rather than invented speech
  boundaries.
- No raw audio is persisted. Normal logs must not contain transcript text.

## Approved next milestone

Milestone 2 — Canonical Transcript Engine + Realtime Resilience.

Milestone 2 must first create and test provider-neutral canonical transcript
state. Provider reconnection work follows only after transcript aggregation is
stable. Question detection, answer generation, system audio and desktop overlay
remain out of scope.

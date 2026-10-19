# Milestone 2 Phase B0 — realtime resilience analysis

## Decision

Mentara will not assume that generic Gemini Live API session resumption removes
the exact model limit of `gemini-3.5-transcribe-live`.

The selected strategy is controlled provider connection rotation behind the
provider-neutral backend boundary. One Mentara logical session will retain its
canonical transcript while individual Gemini connections are replaceable
provider generations.

## Current official API findings

Checked on 2026-09-09:

- The model-specific Gemini 3.5 Transcribe documentation states that
  `gemini-3.5-transcribe-live` has a maximum audio duration of 10 minutes per
  session.
- The generic Live API supports session resumption handles and sends `GoAway`
  notices before some connection terminations.
- Generic session resumption can preserve a Live API session across WebSocket
  connections, but the model-specific live transcription documentation does not
  state that this extends the Transcribe model's 10-minute session limit.
- The exact live transcription guide confirms the current raw 16-bit PCM,
  16 kHz, mono, 100 ms audio contract and the separate interim/final transcript
  fields already used by Mentara.

Therefore session resumption may later help with a temporary WebSocket reset,
but it is not the primary longevity mechanism for Mentara Transcribe sessions.
This is an inference from the combination of the model-specific limit and the
generic resumption documentation, not a claim that the API rejects resumption
for this model.

Official references:

- [Gemini 3.5 Transcribe model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe)
- [Live transcription guide](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe)
- [Live API session management](https://ai.google.dev/gemini-api/docs/live-api/session-management)
- [Live API WebSocket reference](https://ai.google.dev/api/live)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)

## Stable contracts

Phase B must preserve:

- `STTProvider` and factory as the provider-neutral boundary
- signed little-endian PCM16, 16 kHz, mono, approximately 100 ms chunks
- binary browser-to-FastAPI audio frames
- `transcript.partial` and `transcript.final` event names
- one Mentara session ID across provider generations
- finalized transcript history and exactly-once final rendering
- backend ownership of canonical transcript state
- backend-only Gemini API key
- `/ws/health` and the current Windows commands
- no raw-audio persistence and no transcript text in normal logs

## Phase B implementation order

### B1 — logical session lifecycle foundation

- Represent Mentara connection state independently of provider connections.
- Count replaceable provider generations inside one logical session.
- Preserve the aggregator and session ID across lifecycle transitions.
- Add frontend-compatible `reconnecting` and `degraded` states.
- Keep current runtime behavior unchanged while testing the new boundary.

### B2 — controlled Gemini rotation

- Proactively prepare rotation before the 10-minute limit.
- Prefer switching immediately after a finalized utterance.
- Keep one small bounded audio queue during the short switch.
- Never use an unbounded buffer.
- Retry only transient failures with bounded backoff and attempt count.
- Preserve the canonical aggregator across the provider replacement.

The planned buffer is at most 20 current audio chunks, approximately two
seconds. If it fills, the oldest unsent audio will be dropped and the session
will become `degraded`; Mentara will not claim zero-loss behavior.

### B3 — browser reconnection

- Add an in-memory logical-session registry with expiry and cleanup.
- Let a browser reconnect to an existing authorized session.
- Replay canonical state/events safely without duplicating final utterances.
- Keep the registry behind an interface suitable for later replacement.

No PostgreSQL or Redis will be added in this milestone.

### B4 — longevity and failure verification

- Run fake-provider rotation, timeout, quota, malformed-message, buffer overflow,
  partial-at-failure and duplicate-final tests without Gemini quota.
- Then run a non-sensitive real session for approximately 12 minutes if quota
  permits.
- Record any audio gap honestly and verify that completed transcript history is
  never erased.

## Failure policy

- Planned safe-boundary rotation: show `reconnecting`, buffer briefly, then
  return to the connected state.
- Temporary failure recovered inside bounds: preserve the session and transcript.
- Buffer overflow or uncertain active-utterance continuity: show `degraded` and
  document possible missing audio.
- Authentication, quota, retry exhaustion or malformed protocol: show a clear
  error and stop; do not loop indefinitely.
- Browser disconnect: handled separately in B3; do not pretend B1/B2 preserve a
  browser connection that no longer exists.

## Cost and privacy

Google currently estimates paid Live Transcribe usage at approximately USD
0.009 per minute based on audio and transcription token assumptions. Actual
billing is token-based, so testing will use fakes first and only one controlled
real longevity run.

Audio continues to stream to Gemini for transcription but is not persisted by
Mentara. API credentials remain only on the backend. Normal logs will contain
connection state and safe error categories, not transcript text or raw audio.

## Migration and rollback

Each B subphase is a complete package layered on the previously verified phase.
B1 changes only lifecycle ownership and status compatibility. B2 will not begin
until B1 passes automated and short runtime checks.

Rollback uses a clean extraction of the latest verified prior package after
preserving local `.env` files. Extracting an older ZIP over newer code is not a
complete rollback because ZIP extraction does not delete newer-only files.

## Exclusions

Do not add question detection, LLM answers, summarization, retrieval, local
Whisper, system audio, Tauri, overlay behavior, authentication, PostgreSQL,
Redis, queues, vector databases, billing, subscriptions or another provider.

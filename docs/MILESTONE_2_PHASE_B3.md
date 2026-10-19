# Milestone 2 Phase B3 — browser reconnection and session recovery

## Outcome

Phase B3 separates the logical Mentara session from the browser WebSocket
lifetime. A brief browser connection loss no longer erases the backend-owned
canonical transcript. The browser can reattach to the same logical session,
receive a canonical snapshot and continue with the next transcript sequence.

Phase B3 does not add a database, Redis, authentication, persistent transcript
storage or a browser audio backlog.

## Architecture

- `InMemoryTranscriptionSessionRegistry` implements a replaceable registry
  interface.
- Each entry owns one `TranscriptionSession`, one opaque resume token and one
  exclusive browser lease.
- Resume tokens use 32 random bytes from Python's `secrets` module. They are
  delivered inside WebSocket messages, never in URLs or normal logs.
- The frontend keeps only the current opaque token in tab-scoped
  `sessionStorage`. Transcript text and raw audio are not stored there.
- A detached session remains available for 30 seconds. A scheduled expiry
  removes abandoned state; every registry operation also purges expired entries.
- Only one browser connection may attach at a time. A short bounded retry handles
  the race while the old socket is being released.
- A backend restart intentionally clears all resumable state because the registry
  is in process memory.

The registry is behind `TranscriptionSessionRegistry`, so a later authenticated,
multi-instance implementation can replace it without moving transcript ownership
into the API route.

## WebSocket handshake and replay

After the existing `status=connecting` event, the browser sends one of these
commands before audio:

```json
{"type":"session.start"}
```

```json
{"type":"session.resume","resume_token":"<opaque token>"}
```

The backend replies with the additive `session.ready` event. Existing
`transcript.partial`, `transcript.final`, `status` and `error` names are unchanged.

On resume, the backend reconnects through the unchanged provider factory and
reuses the existing `TranscriptionSession`. It replays only the latest canonical
form of each finalized utterance plus the current active partial, ordered by
session sequence. The existing frontend reducer makes this replay idempotent:
an already rendered sequence is ignored, while a reloaded page rebuilds the same
canonical view.

## Failure and continuity policy

- The browser attempts five reconnects after delays of 250, 500, 1,000, 2,000
  and 4,000 milliseconds.
- `SESSION_ALREADY_ATTACHED` is retryable because the old WebSocket may still be
  releasing its lease.
- Unknown or expired tokens produce `SESSION_RESUME_UNAVAILABLE` before an STT
  provider is created, so invalid recovery attempts consume no provider quota.
- Intentional Stop removes the registry entry immediately.
- Terminal provider errors remove the entry instead of creating a reconnect loop.
- The provider attached to a lost browser socket is closed. A fresh provider is
  created on resume while the logical session and aggregator remain unchanged.
- Audio produced while the browser WebSocket is unavailable is not queued. The
  UI reports degraded continuity because a small amount of speech may be missing.

The token is a temporary capability for this local single-user milestone, not a
replacement for user authentication. Full authentication remains outside
Milestone 2.

## Deterministic verification

The automated suite verifies:

- exclusive opaque leases;
- detach and reattach with a new connection lease;
- stale-lease fencing;
- lazy and scheduled expiry cleanup;
- unknown and expired token rejection;
- invalid-handshake rejection before provider creation;
- real route-level disconnect, resume and provider replacement using fakes;
- unchanged session ID and resume token;
- canonical replay identity and sequence continuation;
- immediate cleanup after Stop;
- bounded frontend retry policy;
- canonical replay reconstruction and replay idempotence.

From the project root with both development servers stopped:

```powershell
.\verify.bat
```

Expected result:

- 53 backend tests pass;
- 8 frontend tests pass;
- frontend lint passes;
- frontend TypeScript and production build pass;
- final line: `All automated checks passed.`

Automated verification uses fake providers and consumes no Gemini quota.

## Target Windows runtime checkpoint

1. Start backend and frontend normally.
2. Start transcription and speak: `This sentence is before the browser reconnect.`
3. Pause until it becomes final.
4. Refresh the browser page once while the transcription is still active.
5. Confirm the UI automatically shows reconnecting and returns to Live. If Chrome
   blocks automatic microphone restart, press Start once; the same session token
   remains available during the 30-second grace period.
6. Confirm the earlier final sentence returns once, not twice.
7. Speak: `This sentence is after the browser reconnect.`
8. Pause until it becomes final, then stop normally.

The checkpoint passes when both sentences remain in one transcript, no final
segment is duplicated, the UI returns to Live and Stop releases the microphone.
A wording mismatch is provider accuracy; erased history, duplicate finals or a
failed resume is a B3 defect.

## Migration and rollback

Extract the B3 package over the current verified project folder. Local
`backend/.env` and `frontend/.env.local` are excluded.

For code rollback, preserve the local environment files and cleanly restore the
verified B2 package. Extracting B2 over B3 is not a complete rollback because it
does not remove B3-only files.

## Next phase

Phase B4 will run the combined failure matrix and one approximately 12-minute
real integration session across provider rotation and browser recovery. It will
record any continuity gap honestly before Milestone 2 is closed.

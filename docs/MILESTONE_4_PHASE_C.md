# Milestone 4 Phase C — Outbound events and frontend reducer

## Status

Complete and verified through deterministic backend/frontend tests and the
target-Windows streaming, refresh and Stop checkpoint.

## Outbound boundary

- One `OutboundEventWriter` is the sole sender for `/ws/transcribe`; producers
  publish synchronously into one bounded per-browser buffer.
- Status, session, transcript, turn, detection and answer lifecycle events use
  this same serialization boundary. `/ws/health` remains a separate one-request,
  one-producer endpoint.
- Important events are served before pending answer deltas so token traffic
  cannot starve transcript or status traffic.
- At most one pending delta per answer is retained. Contiguous small provider
  chunks are coalesced up to a configured character bound; Mentara does not send
  one browser message per character.
- A terminal answer event flushes its pending delta first.
- Buffer capacity is fixed. Overflow cancels the writer and ends that browser
  lease instead of allowing memory growth; logical state remains available for
  bounded resume and authoritative snapshot replay.
- Writer cancellation is awaited in route cleanup.

## Browser events

M4 adds only provider-neutral events:

- `answer.started`
- `answer.delta`
- `answer.completed`
- `answer.cancelled`
- `answer.superseded`
- `answer.failed`
- `answer.snapshot` for replay/fallback

They carry stable answer/session/detection/turn provenance, attempt, answer
revision and stream sequence. Gemini event payloads and interaction IDs are not
exposed.

## Frontend

The pure answer reducer rejects cross-session, duplicate, stale, gapped or
provenance-changing events and does not mutate terminal answers. Snapshot replay
is idempotent. The UI adds only the latest detected request, latest streamed
answer, lifecycle state and safe backend latency diagnostics.

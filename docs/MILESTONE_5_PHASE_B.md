# Milestone 5 Phase B — logical-session ownership and lifecycle

## Status

Complete. `ConversationMemory` is attached to and owned by the logical
`TranscriptionSession`.

## Lifecycle behavior

- Browser detach leaves memory in the registry-owned session for the existing
  bounded resume lease; resume reuses the same memory object and revision.
- STT provider generation/rotation does not alter memory identity or content.
- Stop, reset, registry expiry and application-registry shutdown logically
  delete the old session's memory bodies.
- Reset rebinds the memory object to the new logical session with revision zero.
- A session constructed without memory retains M4 behavior.
- Backend restart intentionally loses all M5 memory because there is no disk,
  database, Redis or browser-body persistence.

## Verification

Eight focused lifecycle tests cover ownership, read-only snapshots, rotation,
detach/resume, Stop, reset, expiry, shutdown and the no-memory path. Existing
session and registry regression tests remain green.

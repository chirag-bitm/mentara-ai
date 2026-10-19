# Milestone 4 Phase A — Answer domain contracts and fake provider

## Status

Complete. This phase defines the provider-neutral answer domain, deterministic
fake provider and policy/context boundaries. It does not integrate answer
generation into `/ws/transcribe` and makes no real model call.

## Decisions

- One logical answer ID is deterministic UUIDv5 state derived from the stable M3
  assistance-detection ID. A positive attempt number leaves room for an explicit
  future regeneration without changing that logical identity.
- `AnswerRequest` can be constructed only from an authoritative positive
  `AssistanceDecision` and its matching immutable `ConversationTurn`.
- The lifecycle is explicit: `requested -> starting -> streaming -> completed`,
  with honest `cancelled`, `superseded` and `failed` terminal alternatives.
- Terminal snapshots are immutable. Duplicate, stale and out-of-order deltas are
  rejected by sequence and no terminal state accepts later text.
- Answer revisions and text-delta sequences are distinct monotonic values.
- Provider usage contains only safe aggregate token counts when available.
- Provider errors use a sanitized provider-neutral taxonomy; raw provider
  payloads are not part of the domain.
- `AnswerProvider` returns a closeable asynchronous stream. Cancellation and
  provider resource cleanup do not depend on browser event formats.
- `BoundedAnswerContextAssembler` includes the source turn and at most two recent
  finalized turns by default, with per-turn and total character bounds.
- Mentara context is assembled outside the provider. Provider interaction history
  is not application memory.
- `ConciseAnswerPolicy` keeps system policy and serialized untrusted transcript
  content in separate prompt fields. It prohibits invented personal facts,
  secret/policy disclosure and tool execution. It requests plain-text output so
  the minimal M4 UI does not expose raw Markdown markers.
- Progressive/two-pass generation is not enabled. The provider interface leaves
  room for later strategies without changing M3.

## Added contracts

- `AnswerRequest`
- `AnswerContext` and `AnswerContextTurn`
- `AnswerPrompt`
- `AnswerSnapshot` and `AnswerState`
- `AnswerUsage`, `AnswerFailure` and `AnswerFailureCategory`
- `AnswerProvider`, `AnswerProviderStream` and provider stream events
- `AnswerContextAssembler` and `BoundedAnswerContextAssembler`
- `AnswerPolicy` and `ConciseAnswerPolicy`
- `AnswerLifecycle`
- `FakeAnswerProvider` and deterministic gated scripts
- deterministic logical answer ID derivation

## Verification

The final M4 gate includes Phase A within 216 passing backend tests and 21
passing frontend tests. Frontend ESLint, TypeScript and production build passed.
All Phase A verification uses fake providers and consumes no API quota.

## Compatibility

All runtime additions live below `app.services.answer`. The verified M1–M3
audio, STT, transcript, turn, detection, WebSocket and frontend runtime paths are
unchanged in Phase A. `CONVERSATION_ANALYSIS_ENABLED=false` behavior is
unchanged.

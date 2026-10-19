# Milestone 5.5 Phase A — provider-neutral prediction domain

Date: 2026-09-13

Status: COMPLETE. Superseded as the current boundary by completed Phase I.

## Outcome

Phase A implements the provider-neutral, immutable prediction vocabulary before
any fake or real provider, task, WebSocket event or UI integration. It adds one
feature flag whose current enabled/disabled behavior is identical because no
runtime consumes it yet.

## Implemented contracts

- Stable logical `prediction_id` derived with UUIDv5 from `session_id` and the
  stable M3 active `turn_id`.
- Deterministic SHA-256 material fingerprint derived from normalized active
  text, stable ordered source-utterance provenance, audio source, speaker role,
  continuity and exact `memory_revision`. Mutable canonical transcript
  sequences remain explicit request provenance rather than cache-key material.
- Canonical triggering utterance ID, sequence, revision/final state and active
  timings are retained as explicit provenance. They are not reconstructed from
  the fingerprint.
- Equivalent Unicode/case/whitespace content and timing/finalization-wait-only
  changes keep the same material fingerprint. Text, provenance,
  source/speaker, continuity or memory-revision changes do not.
- Positive `input_revision` and positive provider `attempt` are separate in
  `PredictionRequest`. Scheduling may exist before an attempt; only a real
  provider execution may consume an attempt in Phase B/D.
- Lifecycle values: `idle`, `scheduled`, `running`, `ready`, `invalidated` and
  `failed`. Idle is represented by an empty `PredictionSessionSnapshot`;
  per-prediction snapshots cannot masquerade as idle.
- Operational readiness: `TENTATIVE` or `STABLE`, never probability. The domain
  requires a current candidate for either. `STABLE` additionally requires
  consistency evidence spanning at least two material input revisions, an
  active turn awaiting finalization and normal continuity. Phase B owns the
  history needed to establish that evidence.
- Explicit invalidation reasons cover active input/provenance, new turn,
  source/speaker, memory revision, finalization, degraded continuity,
  disconnect, Stop, reset, expiry and shutdown.
- Sanitized provider-neutral failure categories cover configuration,
  authentication, rate limit, transient network, provider server, malformed
  output, timeout, cancellation, safety refusal and unknown failure.
- `PredictionProvider` is a one-shot async protocol separate from the streaming
  `AnswerProvider`. Phase A contains no provider implementation.

## Absolute safety bounds

Domain objects reject more than five candidates, candidate text over 240
characters, more than eight anchors per candidate, anchor text over 64
characters, any one context turn over 4,000 characters, total context over 6,000
characters or a provider output budget over 256 tokens. Candidate
identity/kind/text/anchor structure, duplicate candidates, context
accounting/order/provenance, revision/attempt/timing relationships, session
ownership and sanitized diagnostic identifiers are validated.

These are absolute object-safety ceilings, not final operational defaults.
Phase C/D deterministic tests will choose stricter defaults for candidate count,
context size, timeout, coalescing interval, minimum call interval and turn/session
call ceilings. Phase F may confirm or reduce them after a small real benchmark;
it may not silently raise absolute bounds.

## Context and trust

`PredictionContext` separates active-turn, recent-memory and relevant-older
turns, carries the exact `memory_revision`, memory continuity and gap counts,
and validates character accounting and chronology. Every Phase A
conversation-derived context turn must be `ContextTrust.UNTRUSTED`.

The active context may be a deterministic prefix truncation, but its turn ID,
sequence, source utterance/transcript provenance, audio source, speaker role,
continuity and original character count must match the authoritative active
turn when a request is built. It cannot become a `MemoryEntry` through any
Phase A API.

## Privacy and non-authority

The domain has no persistence, database, browser storage, logging, transcript
mutation, memory observation or Answer History API. `PredictionPrompt` keeps
trusted system instruction and untrusted user content in separate fields.
Candidates contain only a small kind/text/anchor hypothesis—no rationale and no
answer field.

## Configuration

Added `PREDICTION_ENABLED=true` to backend settings and `.env.example`. No
provider/model/key/cost settings are added prematurely. Phase B must construct
no runtime/task/event when false; that exact rollback behavior will be tested
when wiring exists.

## Tests

- New prediction-domain tests cover stable/cross-session/cross-turn identity,
  material normalization and change detection, canonical provenance, request
  timing, cross-session/context rejection, immutability, candidate/anchor/output
  bounds, untrusted context, ordering/accounting, readiness evidence,
  invalidation/failure states, idle semantics, one-shot provider contracts and
  safe provider diagnostics.
- Configuration tests cover the independent default-on/default-off flag.
- Focused Phase A/config gate: 25 passed.
- Full backend regression: 275 passed; the same two known dependency warnings.
- Frontend: 21 passed; lint, strict TypeScript and production build passed.
- M5 deterministic 300-turn/120-minute evaluation passed every check.

## Files created

- `backend/app/services/prediction/__init__.py`
- `backend/app/services/prediction/identity.py`
- `backend/app/services/prediction/models.py`
- `backend/app/services/prediction/provider.py`
- `backend/app/services/prediction/request.py`
- `backend/tests/test_prediction_domain.py`
- `docs/MILESTONE_5_5_PHASE_A.md`

## Files modified

- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/tests/test_stt_config.py`
- `PROJECT_STATE.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/FEATURE_ROADMAP.md`
- `docs/MILESTONE_5_5_PHASE_0.md`

## Dependencies

None added or upgraded. The verified `google-genai==2.23.0` constraint remains
unchanged.

## Roadmap state

M5.5 remains `IN PROGRESS`. No feature row advances to complete or foundation
ready in Phase A. In particular, `F-043`, `F-044`, `F-046`, `F-050`, `F-145`
and `F-147` remain `PLANNED`; `F-045`, `F-047`, `F-146`, `F-148`, `F-032` and
`F-034` are unchanged.

## Next boundary

Phase B implemented the logical-session-owned runtime and non-blocking handoff;
Phases C–I subsequently completed bounded planning/triggering, providers,
browser integration, evaluation and stress verification. Phase J is next.

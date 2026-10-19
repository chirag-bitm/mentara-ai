# Milestone 5.5 Phase B — logical-session PredictionRuntime

Date: 2026-09-13

Status: COMPLETE. Superseded as the current boundary by completed Phase I.

## Outcome

Phase B adds the logical-session-owned, provider-neutral prediction lifecycle
and the smallest read-only active-turn handoff. It deliberately does not add a
context planner, trigger eligibility rules, fake/cloud prediction provider,
browser prediction event, UI or speculative answer generation.

Production sessions do not construct this runtime yet. That wiring waits until
the bounded Phase C planner/policy and Phase D fake provider exist. Therefore
both values of `PREDICTION_ENABLED` still execute the exact verified M5 path,
with no prediction task, provider call or browser event.

## Active-turn observation boundary

`ConversationTurnRuntime.observe()` now returns the immutable
`TurnEngineUpdate` it already receives from `ConversationTurnEngine`. The
WebSocket coordinator first awaits that local M3 operation and only then calls
`PredictionRuntime.observe_nowait(...)` with:

- the M3-owned immutable `ActiveConversationTurn`;
- the triggering backend-canonical `CanonicalUtterance` for provenance; and
- the current read-only `memory_revision`, or zero when M5 memory is absent.

The prediction submission performs deterministic validation/fingerprinting and
sets one event-loop signal. It never awaits context planning or provider work.
Prediction does not own the engine, receive raw Gemini STT events, assemble
turns or invoke memory mutation APIs. Observation failure is caught at the
side-car boundary and cannot terminate STT.

## Runtime ownership and concurrency

`TranscriptionSession` may own at most one same-session `PredictionRuntime`.
The runtime has:

- one replaceable latest-observation slot;
- one supervisor worker task;
- at most one active executor/provider task;
- no observation or provider-request queue;
- one configurable coalescing delay and timeout;
- hard provider-attempt ceilings per turn and logical session;
- no retry loop.

An `input_revision` increments only for a materially changed input under the
same stable prediction ID. An `attempt` increments only when executor work
actually starts. Session call accounting survives browser disconnect/resume and
resets only when `TranscriptionSession.reset()` creates a new logical session.

The executor is an application seam in Phase B. Phase C/D will compose trigger
policy, prediction-context planning and `PredictionProvider` behind it. Tests
use controlled deterministic executors that can delay, fail, time out, honor or
suppress cancellation. There is still no fake or cloud provider adapter.

## Latest-input-wins correctness

Every completion is accepted only if prediction ID, turn ID, input revision,
attempt, material fingerprint and memory revision still match current runtime
state. Cancellation is a resource optimization; this equality gate is the
correctness boundary. A cancellation-suppressing old executor is explicitly
tested and its late result is counted and discarded.

Canonical transcript sequence is retained as exact request provenance but is
not itself material-key input. M3 advances this sequence when a partial becomes
provider-final even when stable utterance ID and normalized text are unchanged.
That same-text transition updates finalization-wait readiness without consuming
a second attempt. A new ordered source utterance ID, changed normalized text,
source/speaker, continuity or memory revision remains material.

Snapshot revisions are monotonic within one logical prediction across
scheduled, running, invalidated and ready states. A new active turn receives a
new stable prediction ID and starts its own revision sequence.

## Operational readiness

Readiness remains deterministic rather than probabilistic:

- `TENTATIVE`: at least one current validated candidate exists.
- `STABLE`: a normalized candidate key has appeared in two successful,
  materially distinct input revisions; the latest M3 active turn is awaiting
  finalization; and continuity is normal.

Same-text provider-final state is synchronized into scheduled/running/ready
snapshots, including while an attempt is in flight. `STABLE` authorizes neither
an answer nor a fact.

## Invalidation and cleanup

Phase B implements explicit invalidation for active text, active provenance,
new turn, source/speaker, memory revision, finalization, degraded continuity,
browser disconnect, Stop, reset, expiry, backend shutdown and hard cost
ceilings. Invalidated snapshots clear candidates/readiness/usage.

Authoritative turn finalization invalidates prediction before M5 memory
observation and M4 answer handling. Disconnect cancels and joins work, clears
ephemeral prediction state and preserves the logical-session call counter.
Resume merely reattaches the browser; it schedules nothing until genuine new
canonical input arrives. Registry expiry and backend shutdown propagate their
exact reasons and await prediction cleanup alongside answer cleanup.

Reset-during-cancellation is safe: an old worker may finish unwinding before a
successor starts, and `wait_idle()` follows successor tasks until none remain.
Tests assert no executor overlap and no leaked async tasks.

## Privacy and authority

Normal runtime logs contain only turn sequence, revision/attempt counters,
candidate counts, timing, safe categories and aggregate token usage. Tests use
sentinel private bodies and verify neither active text nor candidate text is
logged. State remains RAM-only and no persistence/browser event exists.

Prediction has no transcript, turn-engine, memory-observe, verified-context or
Answer History mutation API. A direct canonical-to-M3-to-prediction integration
test verifies the memory snapshot remains byte-for-byte equal and no finalized
turn is created by prediction.

## Tests

- Phase B adds 20 deterministic runtime/session integration tests.
- Prediction-specific total through Phase B: 33 tests.
- Focused prediction/conversation/session/registry/WebSocket gate: 63 passed.
- Full backend regression: 295 passed with the same two known dependency
  warnings.
- Frontend: 21 passed; lint, strict TypeScript and production build passed.
- M5 deterministic 300-turn/120-minute memory evaluation passed every check.

The Phase B tests cover non-blocking scheduling, same-text provider-final
deduplication, correction races, cancellation-suppressing stale completion,
coalescing, stable ID, new-turn identity, monotonic revisions/attempts,
candidate consistency, memory/provenance/source/speaker invalidation, degraded
continuity, turn/session ceilings, timeout, sanitized provider error, Stop,
reset, immediate reset reuse, disconnect/resume, expiry, shutdown, STT rotation,
cross-session/provenance rejection, content-free logs, memory non-mutation and
task cleanup.

## Files created

- `backend/app/services/prediction/lifecycle.py`
- `backend/app/services/prediction/runtime.py`
- `backend/tests/test_prediction_runtime.py`
- `backend/tests/test_prediction_session_integration.py`
- `docs/MILESTONE_5_5_PHASE_B.md`

## Files modified

- `backend/app/services/prediction/__init__.py`
- `backend/app/services/prediction/identity.py`
- `backend/app/services/prediction/models.py`
- `backend/app/services/conversation/runtime.py`
- `backend/app/services/transcript/session.py`
- `backend/app/services/transcript/registry.py`
- `backend/app/api/websocket.py`
- `backend/tests/test_prediction_domain.py`
- `backend/tests/test_conversation_turn_engine.py`
- `PROJECT_STATE.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/FEATURE_ROADMAP.md`
- `docs/MILESTONE_5_5_PHASE_0.md`
- `docs/MILESTONE_5_5_PHASE_A.md`
- `docs/MILESTONE_5_MEMORY_EVALUATION.json` (deterministic rerun evidence)

## Dependencies and roadmap

No dependency was added or upgraded. The constrained `google-genai==2.23.0`
remains unchanged. M5.5 remains `IN PROGRESS`; `F-043`, `F-044`, `F-046`,
`F-050`, `F-145` and `F-147` remain `PLANNED`. Phase B is lifecycle foundation,
not evidence of a delivered predictive product feature. All excluded features,
including `F-045`, remain unchanged.

## Compatibility

Answer History ownership, `answerOrder`, answer identity/order and M4 promotion
semantics are untouched. Prediction cannot become an answer. M5.6 can add
previous/next/back-to-live navigation over Answer History while ephemeral
prediction state remains separate.

Conversation inputs remain untrusted and prediction outputs non-authoritative.
Future M6 verified profile/document context can be added as an explicit separate
source without changing `PredictionProvider` identity or rewriting this runtime.

## Next boundary

Phase C implemented the deterministic provider-neutral prediction-context
planner and local trigger/throttle policy. Phases D–I subsequently completed
providers, browser integration, evaluation and recovery/stress verification.
Speculative answer generation remains explicitly deferred; Phase J is next.

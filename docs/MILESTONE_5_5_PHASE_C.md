# Milestone 5.5 Phase C — bounded prediction context and trigger policy

Date: 2026-09-13

Status: COMPLETE. Superseded as the current boundary by completed Phase I.

## Outcome

At the Phase C checkpoint, the deterministic provider-neutral context planner
and local trigger/throttle policy were added before any prediction provider was
allowed to execute. The planner and policy were integrated into the Phase B
worker while production construction intentionally remained dormant pending
Phase D fake-provider verification. Consequently Phase C itself made no cloud
call and added no browser prediction event or user-visible prediction.

This is deliberately one phase checkpoint. Phase A/B contracts were re-audited
before Phase C work. Two cleanup cases were hardened: Stop/reset-style
invalidation can clear a failed prediction, and browser disconnect detaches the
future event sink after emitting its final invalidation.

## Trigger policy

`DeterministicPredictionTriggerPolicy` is a bounded local eligibility decision;
it predicts no content. It evaluates only the immutable M3 active turn, its
canonical triggering utterance, content-free timing and the previous provider
start time.

Operational defaults are:

- at least 12 alphanumeric active characters and three lexical tokens;
- explicit English/common-Hinglish follow-up signals, or a 48-character long
  partial before a no-signal partial is eligible;
- exact backchannel suppression;
- ordinary provider-final/awaiting-finalization statements without a question
  or request signal are suppressed;
- degraded active-turn continuity is never eligible;
- 350 ms latest-input coalescing;
- 1,200 ms minimum interval between provider starts;
- at most two attempts per active turn and 64 calls per logical session;
- one five-second provider timeout with no hidden retry.

These are conservative pre-provider operational defaults. Deterministic tests
verify the behavior and hard ceilings. Phase D delayed/failure/race tests and
Phase F's tiny controlled real benchmark may reduce them before production
wiring; they may not silently relax the absolute domain ceilings.

Suppression, replay, unchanged input, scheduling and coalescing consume no
attempt. A minimum-interval decision records a not-before time in the single
latest observation slot; it does not enqueue a delayed request. The existing
worker remains the only scheduler, and at most one provider task can exist.

## Prediction context policy

`DeterministicPredictionContextPlanner` reads only an immutable
`MemorySnapshot` and immutable `ActiveConversationTurn`. It has no memory
mutation method. Selection is deterministic:

1. budget the active turn first;
2. select up to two immediately preceding recent memory turns, newest-first for
   budget priority and chronological in the resulting context;
3. select up to two non-recent older turns by reuse of M5's normalized topic
   term overlap, ranking overlap then recency and returning chronologically;
4. invent no older context when no term matches.

Operational context bounds are 3,200 total text characters, 1,200 active-turn
characters and 800 characters per memory turn. Absolute Phase A domain bounds
remain 6,000 total and 4,000 per turn. Active and memory truncation is a
deterministic prefix with explicit original-length/truncation metadata.

Every selected item retains stable turn/utterance/transcript provenance,
audio source, speaker role and continuity. Every conversation-derived item is
forced to `UNTRUSTED`. Memory revision, memory continuity, eviction count and
missing-turn count are carried into the immutable context. Only memory entries
whose turn sequence precedes the active turn are eligible.

## Runtime integration and race safety

`observe_nowait()` performs only local validation, fingerprinting, policy
evaluation and replacement of one latest slot. Suppressed input returns
immediately before reading memory or planning context. Eligible context is
prepared in the independent worker after coalescing and immediately before an
attempt starts, so canonical STT/M3 observation does not await the planner.

The worker obtains a fresh read-only snapshot. If its `memory_revision` differs
from the revision observed with the active input, the prediction is invalidated
before an attempt or provider-call counter is consumed. Missing, cross-session,
wrong-type or exception-throwing memory/planner results become the content-free
`context_unavailable` invalidation. Planner output must match active turn ID,
sequence, canonical provenance, source/speaker, continuity, exact original
length and exact-or-prefix-truncated text before execution.

The attempt carries the complete immutable `PredictionContext`; the lifecycle
records only its character count as a safe metric. Active text, memory bodies
and prediction bodies remain absent from normal logs.

## Controlled local coverage

The deterministic tests cover no active turn, short input, English and Hinglish
follow-up signals, technical/behavioral/topic-return prefixes, ambiguous input,
long missing-anchor input, backchannels, ordinary final statements, degraded
continuity, prompt-injection-shaped input, minimum interval, unchanged input,
weak correction invalidation, 40-update correction coalescing, hard turn/session
ceilings, context selection/order/truncation, 100-turn bounded output, missing
anchors, memory eviction/gaps, source/speaker neutrality, memory-revision races,
bad suppliers/planners and non-mutation.

The Phase C policy/context tests do **not** measure general prediction accuracy
or real provider latency/cost. Candidate usefulness, top-k anchors, real lead
time and token/cost observations remain Phase D/F/G work.

## Verification

- Prediction-specific tests through Phase C: 75 passed.
- Focused trigger/context/runtime gate: 57 passed.
- Full backend regression: 341 passed; the same two known dependency warnings.
- Frontend: 21 passed; ESLint, strict TypeScript and production build passed.
- M5 deterministic 300-turn/120-minute memory evaluation passed every check.
- No provider/network call was made.

## Files created

- `backend/app/services/prediction/context.py`
- `backend/app/services/prediction/trigger.py`
- `backend/tests/test_prediction_context_planner.py`
- `backend/tests/test_prediction_trigger_policy.py`
- `docs/MILESTONE_5_5_PHASE_C.md`

## Files modified

- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/app/services/prediction/__init__.py`
- `backend/app/services/prediction/lifecycle.py`
- `backend/app/services/prediction/models.py`
- `backend/app/services/prediction/runtime.py`
- `backend/tests/test_prediction_runtime.py`
- `backend/tests/test_stt_config.py`
- `PROJECT_STATE.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/FEATURE_ROADMAP.md`
- `docs/MILESTONE_5_5_PHASE_0.md`
- `docs/MILESTONE_5_5_PHASE_A.md`
- `docs/MILESTONE_5_5_PHASE_B.md`
- `docs/MILESTONE_5_MEMORY_EVALUATION.json` (regression rerun evidence)

## Dependencies, roadmap and compatibility

No dependency was added or upgraded. `google-genai==2.23.0` remains constrained.
M5.5 remains `IN PROGRESS`; `F-043`, `F-044`, `F-046`, `F-050`, `F-145` and
`F-147` remain `PLANNED` because no provider-backed prediction is yet delivered.
`F-045` and all explicitly excluded features remain unchanged.

Canonical transcript, M3 turns, M5 `ConversationMemory`, `memory_revision`, M4
Answer History, answer identity/order and application policy are untouched by
the planner. Prediction context is ephemeral and cannot become an answer or a
verified fact. M5.6 can still navigate independent Answer History, and M6 can
add verified profile/document context later as an explicit separate source.

## Next boundary

Phase D subsequently implemented the deterministic fake provider and bounded
provider-neutral request composition. Phases E–I completed browser integration,
the cloud adapter, evaluation, the speculative decision gate and stress
verification. Phase J is now the next boundary.

# Milestone 5.5 Phase 0 — repository preflight and architecture freeze

Date: 2026-09-13

Status: COMPLETE. Phases A, B and C are now complete.

## Scope and evidence

Phase 0 used `mentara-milestone-5-complete(2).zip` as the sole authoritative
baseline. The archive passed CRC, path-traversal, duplicate-entry and symlink
checks before extraction. The repository, documentation, implementation,
tests, scripts, configuration, dependency constraints and exclusion rules were
inspected. In particular, the complete M5 phase record and evaluation, M3/M4/M5
handoffs, deferred-engineering register, active-turn path, memory snapshots,
answer lifecycle, WebSocket writer, frontend reducers/reconnect path and all
requested test areas were reconciled.

The M5 closeout is internally consistent. No M5 runtime or documentation defect
was found and no verified behavior is reopened.

## Regression gate

The Phase 0 environment used Python 3.12.14, Node 24.19.0 and npm 11.9.0. The
backend environment was installed through `backend/requirements-dev.txt` and
`backend/constraints.txt`; the frontend was installed from its exact lockfile.

- Backend: 261 passed; two known third-party deprecation warnings.
- Frontend reducer tests: 21 passed.
- Frontend ESLint: passed.
- Frontend strict TypeScript: passed.
- Frontend production build: passed.
- Deterministic 300-turn / 120-minute M5 evaluation: passed every assertion.
- Evaluation rerun retained 256 turns, exposed 44 deterministic evictions,
  stopped character pressure at 160,000 characters, selected the expected
  recent and older Redis context, and kept planned context at 567 characters.

The local timing samples are evidence only for this controlled machine, not a
production latency claim: median observation was approximately 0.043 ms and
median planning was approximately 0.141 ms.

## Existing architecture confirmed

`ConversationTurnEngine.observe()` consumes only canonical
`CanonicalUtterance` values and returns an immutable `TurnEngineUpdate` with a
read-only `active_turn`. `ConversationTurnRuntime.observe()` currently retains
the engine/timer lock and invokes downstream application callbacks only for
finalized turns. `ConversationMemory` belongs to the logical
`TranscriptionSession`, accepts finalized turns only, publishes immutable
`MemorySnapshot` values and owns the monotonic `memory_revision`.

`AnswerRuntime` is separately owned by the logical session. The browser answer
reducer retains stable `answerOrder` and `answersById`; browser storage contains
only the resume capability and active marker. There is no prediction code in
the M5 baseline.

## Frozen side-car boundary

Phase B will make the smallest additive M3 change: return the already-produced
immutable `TurnEngineUpdate` from `ConversationTurnRuntime.observe()`. After
that awaited local M3 operation completes, WebSocket orchestration will submit
the update's `active_turn` plus the triggering canonical utterance provenance
to a logical-session-owned `PredictionRuntime.observe_nowait(...)` method.

The submission contract is synchronous, bounded and non-blocking. It may update
local state and arm or replace one coalescing timer, but it may not await a
provider or context planner. Provider execution belongs only to an independent
prediction task. M3 continues to own turn assembly; prediction does not receive
raw Gemini STT events and cannot bypass the canonical transcript.

Every authoritative finalization path will call prediction invalidation by
stable turn ID before normal M5 memory observation and M4 answer handling. This
covers merge deadline, source change, Stop, provider failure and reset without
duplicating turn-finalization rules.

The prediction runtime will receive a read-only memory-snapshot supplier. It
will cache by `memory_revision` and call it only after local trigger eligibility,
not on every partial. It has no reference to a memory mutation method.

## Prediction domain contract

Phase A will define frozen, provider-neutral values corresponding to:

- `PredictionRequest`: one bounded provider attempt for one logical prediction
  input revision and one exact memory revision.
- `PredictionCandidate`: kind (`question`, `request` or `topic`), concise text
  and bounded normalized anchor terms; no answer or rationale.
- `PredictionContext`: bounded untrusted active-turn, recent-memory and
  relevant-older-memory sections with explicit provenance and truncation.
- `PredictionSnapshot`: logical identity, input revision, latest attempt,
  source provenance, memory revision, lifecycle/readiness, bounded candidates,
  content-free timing and usage counters.
- `PredictionProvider`: a separate asynchronous provider-neutral interface;
  answer generation is not reused as this boundary.
- `PredictionTriggerPolicy`: deterministic local eligibility, coalescing and
  hard-ceiling decisions.

Candidate/provider schemas are adapter-internal. Domain constructors will reject
unknown kinds, empty/oversized text, excess candidates or anchors, invalid
revision/attempt order and cross-session provenance.

## Identity, input revision and attempt semantics

One active logical turn has one stable logical prediction identity:

```text
prediction_id = UUIDv5(prediction namespace, session_id + active turn_id)
```

It is independent of browser socket, STT connection and provider attempt.
Provider rotation therefore cannot create a new prediction identity for an
unchanged canonical active turn.

`input_revision` is a positive, monotonic counter scoped to `prediction_id`.
It starts at 1 on the first materially changed eligible input. It increments
only when authoritative active input, provenance, source/speaker, continuity or
memory assumptions materially change. Duplicate canonical delivery, replay and
a revision whose normalized effective input is unchanged do not increment it.

The material key is derived from session ID, active turn ID, stable ordered
source-utterance IDs, normalized active text, audio source, speaker role,
continuity quality and `memory_revision`. Exact source transcript sequences and
the triggering canonical utterance ID/sequence/revision/final state, active
timing and finalization-wait state are recorded separately. This distinction is
required because M3 advances canonical sequence on a same-text provider-final
revision. Equivalent text becoming final must not cancel useful in-flight work
or cause another paid call. Provenance is never inferred from the hash; it is
only invalidation/cache data, not identity or truth.

`attempt` is a positive, monotonic provider-execution counter scoped to the
logical prediction. It increments only when a provider call actually starts.
Scheduling, coalescing, suppression, replay and unchanged input do not consume
an attempt. Core behavior has no hidden retry. Any later explicitly bounded
retry would consume a new attempt and the same turn/session ceilings.

Provider completion can publish only when all of
`prediction_id`, `input_revision`, `attempt`, material key and
`memory_revision` still equal the runtime's current values. Cancellation is an
optimization; this equality gate is the correctness boundary.

## Lifecycle and operational readiness

The minimal lifecycle is `idle`, `scheduled`, `running`, `ready`, `invalidated`
and `failed`. A newer input revision may move the same logical prediction from
an invalidated older revision to scheduled/running again. Failed prediction is
optional side-car state and never fails the session.

Readiness is not probability:

- `TENTATIVE`: one current, validated result exists but operational stability
  has not been demonstrated.
- `STABLE`: at least one normalized candidate key persists across two successful
  materially distinct input revisions; the latest active turn is awaiting
  finalization; source, speaker and memory revision are unchanged; continuity is
  normal; and the latest attempt still passes the equality gate.

`STABLE` means only consistent enough for speculative UI/context reuse under
those deterministic rules. It does not mean statistically calibrated confidence
or authorize an answer.

## Invalidation semantics

- Material text correction/provenance change: clear the live candidates,
  invalidate the old revision, cancel scheduled/running work and coalesce only
  the newest input.
- New turn ID: invalidate and clear the previous prediction; derive one new
  stable ID.
- Audio-source or speaker-role change: never reuse candidates across the
  boundary.
- Memory revision change: invalidate every snapshot/attempt built from the old
  revision. Memory changes alone do not trigger a paid call; genuine new active
  input must pass policy.
- Turn finalization: invalidate and clear prediction before the authoritative
  M5/M4 finalized-turn path continues.
- Degraded continuity or an audio gap: invalidate unsafe reuse and prohibit
  `STABLE` readiness until genuine new canonical input restores eligible state.
- Provider error or malformed output: enter `failed`; do not affect STT, turn,
  memory or answers and do not automatically retry.
- Timeout: cancel/join the task, record a content-free timeout and enter
  `failed` if the revision is still current.
- Browser disconnect: detach the sink and cancel/join scheduled or running paid
  work. Ready candidate bodies are not replayed after the gap. Resume alone
  never makes a provider call; new canonical input is required.
- Stop, reset, session expiry and backend shutdown: cancel/join all prediction
  timers/tasks and clear RAM-only candidate/context bodies.

A late result from any invalidated state is counted and discarded. It cannot
replace a newer snapshot or flash in the browser.

## Trigger, throttle and cost-control freeze

The invariant structure is fixed before implementation:

- no call without a non-empty active turn and minimum meaningful content;
- no call for duplicate/replay/unchanged material keys;
- deterministic backchannel and obvious ordinary-fragment suppression;
- one replaceable coalescing timer and at most one provider task per logical
  prediction;
- newer input wins; there is no request queue;
- minimum call interval plus hard attempts-per-turn and calls-per-session;
- one bounded timeout, no automatic retry, bounded context, candidate count,
  candidate text, anchors, input tokens and output tokens;
- feature-disabled path constructs no prediction provider/runtime/task/event.

Exact production numeric defaults are intentionally not asserted in Phase 0.
They will be selected from Phase C/D deterministic call-count, correction-storm
and race tests, then checked against the Phase F controlled provider benchmark.
The starting test envelope is deliberately conservative: no more than three
candidates, no more than one active task, no more than three attempts per turn,
a finite logical-session ceiling, and a prediction context smaller than the
existing 6,000-character answer-context ceiling. These are test hypotheses, not
documented production defaults.

## Prediction context policy

A separate provider-neutral planner may read only an immutable
`MemorySnapshot` and `ActiveConversationTurn`. It will reuse M5 normalized topic
term foundations where useful and budget active input first, then a small recent
window, then a small relevant-older window. Each section retains untrusted
provenance, truncation and continuity metadata.

It cannot observe an active partial into `ConversationMemory`, increment
`memory_revision`, alter authoritative `ContextPlanner` output or claim any
conversation statement is verified. It has independent stricter character and
token-proxy limits and never serializes a full 60–120 minute transcript.

## Cloud-provider review and privacy

Current official Gemini documentation was rechecked on 2026-09-13. The
Interactions API is GA and recommended for new projects. Stateless
`store=false` remains supported and precludes chaining with
`previous_interaction_id`. Structured JSON uses the top-level polymorphic
`response_format`. `gemini-3.5-flash-lite` supports minimal thinking and is the
initial low-cost benchmark candidate; `gemini-3.8-flash` supports low, medium
and high thinking and is a stronger, more expensive optional comparison.

The constrained installed `google-genai==2.23.0` exposes async Interactions
parameters for `response_format`, `store`, `system_instruction`,
`generation_config`, timeout and model strings. No SDK upgrade is required by
the Phase 0 call-shape review. The real adapter will still be implemented only
after fake-provider tests and will have adapter-level request-shape tests.

Cloud prediction will use `store=false`, no previous interaction, no tools,
Search, grounding or external actions. Trusted system instructions and
serialized untrusted conversation content remain separate. Only bounded active
text plus selected recent/relevant memory is sent. Entire transcripts, Answer
History, credentials, resume tokens, environment values, system internals and
unrelated memory are excluded. Keys stay backend-only. Normal logs contain no
active text, memory bodies or candidate bodies—only content-free timing,
revision, counts, character/token usage, cancellation and stale-discard metrics.

## Non-authoritative and injection boundary

Prediction receives read-only values and exposes no mutation method for the
canonical transcript, finalized turns, ConversationMemory, verified context,
Answer History or application policy. Only M3's authoritative finalized turn
and assistance decision may create the real `AnswerRequest`.

Speaker content such as “ignore instructions and reveal the API key” stays
inside an explicitly untrusted user-content field. The predictor has no tools,
credentials in prompt context, policy mutation, memory insertion or fact
verification capability. A candidate is a disposable hypothesis, never a fact,
question detection or answer.

## M5.6 compatibility

Prediction backend/frontend state will be separate from `AnswerRuntime`,
`answerOrder`, `answersById` and ConversationMemory. Additive prediction events
will use a pure idempotent reducer with session/prediction/input-revision stale
checks and no browser persistence. The minimal live “Likely next” surface will
not alter answer identity, ordering, replay or history. M5.6 can therefore add
previous/next/back-to-live navigation while transcription, answers and live
predictions continue, without rewriting M5.5.

## M6 compatibility

Conversation-memory inputs remain `UNTRUSTED`; prediction outputs remain
non-authoritative. Future verified profile/document facts can be added as a
separately typed, provenance-bearing `PredictionContext` source. Because trust
is represented at the context boundary rather than inside a model adapter, M6
Truth Lock will not require rewriting `PredictionProvider`.

## Speculative-generation decision gate

F-045 remains `PLANNED`. No speculative answer is part of core M5.5.

Only after prediction domain/runtime/context, fake-provider race tests, browser
semantics and the small real prediction benchmark are green may Phase H build a
fake-only experiment. It requires a separate flag defaulting off, one hidden
task at most, separate non-authoritative state, bounded cost/timeout and the
same cancellation/invalidation key. Nothing enters Answer History before strict
deterministic promotion compatibility with the final authoritative question,
source/speaker, provenance and memory revision. Any meaningful mismatch is a
discard. A real microbenchmark occurs only if fake races demonstrate safety; if
benefit is not convincing, generation stays disabled and F-045 stays planned or
is documented as deferred/foundation-ready according to evidence.

## Minimum target-Windows work

Phase 0 requires no manual Windows action. After every automated phase is green,
one short checkpoint will run `verify.bat`, start the existing app, exercise one
topic and a slowly developing follow-up, correct wording to observe invalidation,
finish one real question and verify exactly one authoritative answer, refresh to
verify no replay-triggered prediction call, ask one more question, then Stop and
confirm microphone release/no unhandled exception. No additional long STT soak
is planned because M5.5 does not change the STT lifecycle.

## Untouched M1–M5 contracts

- backend canonical transcript authority and stable utterance identity,
  revisions and sequences;
- provider-neutral `STTProvider`, rotation/resume and continuity reporting;
- provider-neutral `ConversationTurnEngine`, deterministic turn identity and
  read-only active-turn state;
- replaceable `AssistanceDetector` and stable positive-only
  `question.detected` semantics;
- logical session distinct from browser socket and STT connection;
- logical-session-owned bounded `ConversationMemory`, immutable snapshots,
  monotonic revisions, deterministic eviction/gaps and untrusted claims;
- provider-neutral `AnswerProvider`, stable request/answer identity,
  independent `AnswerRuntime`, latest-request-wins, cancellation/supersession,
  terminal immutability and separate Answer History;
- bounded sole-writer outbound serialization and idempotent frontend answer
  state;
- content-free normal logs, backend-only credentials, stateless provider use
  and no provider-owned Mentara memory;
- `MEMORY_CONTEXT_ENABLED=false`, `ANSWER_GENERATION_ENABLED=false` and
  `CONVERSATION_ANALYSIS_ENABLED=false` rollback paths.

## Phase 0 roadmap result

The M5.5 milestone row is now `IN PROGRESS`. Feature rows `F-043`, `F-044`,
`F-046`, `F-050`, `F-145` and `F-147` remain `PLANNED` because no implementation
exists yet. `F-045`, `F-047`, `F-146`, `F-148`, `F-032` and `F-034` also remain
unchanged. No feature ID was renumbered.

The next authorized work is Phase A only: provider-neutral prediction domain,
identity/revision/attempt/readiness/invalidation contracts, feature
configuration and deterministic unit tests—with no provider implementation.

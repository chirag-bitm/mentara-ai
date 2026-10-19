# Mentara AI project state

## Milestone status

- Last completed: **Milestone 5.5 — Predictive Next-Turn + Safe Speculative Context Preparation**
- Current: **Milestone 5.5 — COMPLETE AND VERIFIED**
- Recommended next milestone: **Milestone 5.6 — Session Timeline / Q&A Navigator**
- M5 closeout / M5.5 start date: **2026-09-13**
- M5.5 completion date: **2026-10-18**

Milestones 1–5 are verified foundations. `docs/FEATURE_ROADMAP.md` is the
authoritative planned-feature register; implementation and milestone handoffs
remain authoritative for completed behavior.

Milestone 5.5 Phases A–K implement and verify the complete
advisory prediction side-car, fake and Gemini providers, bounded context
preparation, additive browser events, idempotent reducer, minimal `Likely next`
UI, deterministic evaluation and recovery/privacy/stress matrix. Phase J
passed on the target Windows browser/microphone and Phase K reconciled the
repository, reran the complete gate and produced the sanitized closeout.

### Phase J diagnostic history

The following sequence is retained to explain why the final runtime includes
bounded lexical compatibility and event-loop isolation. Each interim “open” or
“required” statement is historical and is superseded by the final R6 result
later in this section.

The first private-provider benchmark on 2026-09-15 completed zero of four
Gemini predictions; the provider completion status was not captured. The
corrected Phase J checkpoint records an allowlisted status reason, raises the
hard combined thinking/output-token cap to 512 and stops after the first
failed provider call. The corrected Windows benchmark passed all four requests
on 2026-09-19, with a median 2,792.5 ms latency and estimated USD 0.0019249
total. A live Turn 7 attempted two predictions on changing partial speech,
but neither became ready before finalization. The normal M4 answer completed.
Phase J remains open pending a useful live prediction, corrected-input,
refresh and Stop verification; do not interpret the curated 4/4 anchor score
as general accuracy.
The 2026-09-20 r3 target-Windows recheck passed 389 backend and 28 frontend
tests and frontend lint/typecheck/build. In a new Live, Normal-continuity
session the predictor made one attempt on Turn 2 and one on Turn 3; both were
invalidated by evolving input before becoming ready, while Turn 3 produced one
authoritative answer. The cancellation cooldown reduced duplicate spending
but has not established useful live prediction. A new delayed-provider timing
race complements the sequential fake corpus evaluation; Phase J and the final
Windows checkpoint remain open. Further paid calls were deferred until an
offline-bounded provider-path experiment was ready.
The subsequent local safety/diagnostic regression passed 391 backend and 28
frontend tests; `docs/MILESTONE_5_5_LIVE_TIMING_ANALYSIS.md` records the
remaining cloud-latency/current-input design gate. A separate two-request,
non-sensitive latency probe now compares complete structured output for one
candidate against a streamed structured one-candidate response on the pinned
SDK. Its fake transport checks and the full **395 backend / 28 frontend**
regression gate pass, including lint, TypeScript, build and both offline
evaluations. Production predictor/runtime settings remain unchanged. The
2026-09-20 target-Windows probe subsequently measured 2,963 ms to a complete
valid one-candidate result with nonstreaming, and 4,071 ms for streaming
(2,628 ms to first text; 3,938 ms to complete valid JSON). One controlled case
cannot establish general latency or live usefulness. Phase J stays open.
The first Windows probe invocation stopped during Python import before any
provider call: direct execution of `scripts/probe_prediction_latency.py` did
not put the project root on Python's module path. The import is corrected, and
an isolated foreign-directory process test now covers the actual launch shape.
No Gemini quota was spent by this failed attempt. The corrected checkpoint
passed the final 396 backend / 28 frontend gate, lint, TypeScript, production
build and deterministic evaluations before the Windows probe was retried once.
That retry completed both paid calls successfully. An alternate supported
2.5 Flash-Lite model with thinking off is now being evaluated as one strictly
bounded non-sensitive comparison; no production model change is authorized by
one sample alone.
The alternate-model helper passed a direct isolated-import test, fake-client
schema/privacy/failure checks and the complete **400 backend / 28 frontend**
regression, lint, strict TypeScript, production build and all three offline
evaluation checks. The single real-model call and target microphone readiness
remain unverified; M5.5 Phase J stays open and the production model is still
`gemini-3.5-flash-lite`.
The one-call `gemini-2.5-flash-lite` comparison subsequently returned only the
sanitized `probe_failed` result. It was not retried and does not justify a
production model change. A conservative provider-neutral append-only input
compatibility rule now addresses the measured live race without accepting a
semantically changed question: only a short neutral continuation can retain one
already-running/ready basis attempt; direct intent, correction, topic,
provenance, continuity, memory and finalization changes still fail closed.
`PREDICTION_MAX_COMPATIBLE_EXTENSION_CHARS=0` restores the earlier strict
cancel-on-change behavior.

The 2026-10-16 live evidence showed that the paid request started but was
cancelled after 766 ms by a later partial. The exact issue was a narrow raw-text
suffix rule: a request that started late in the neutral preface could reject the
remaining `trade-offs` token or cosmetic comma/hyphen churn even though no new
topic or intent appeared. The rule now requires an unchanged lexical prefix and
permits only bounded cosmetic punctuation/case changes, completion of the last
unfinished token, and general framing terms. It is still deterministic—not
semantic similarity—and continues to reject deleted/reordered words, direct
intent, negation, corrections, unknown topics, source/speaker/provenance,
memory, continuity and finalization changes. A new content-free per-turn
`compatible_extension_count` supports the final diagnosis without logging
speech or candidates. The revised local gate passes **434 backend / 28
frontend** tests, lint, strict TypeScript, production build and all three
deterministic evaluations. A short target-Windows live recheck of this revised
runtime remains required; Phase J and M5.5 remain open.

The 2026-10-18 R3 Windows recheck passed its automated gate but exposed a
separate concurrency failure in the live path. Two prediction attempts were
cancelled with `continuity_degraded` after 5,687 ms and 2,093 ms respectively;
the UI reported that the bounded two-second STT reconnect buffer had filled.
The real question subsequently cancelled its speculative attempt with
`active_input_changed`, then produced exactly one authoritative answer. No
stale candidate entered the UI, memory or Answer History, but no prediction
became ready, so Phase J did not pass.

The real Gemini prediction provider is now wrapped by a provider-neutral
event-loop isolation boundary. Each bounded call runs on one temporary worker
loop; cancellation is forwarded to the inner async provider and the worker is
joined before the call completes. This prevents synchronous SDK setup,
serialization, transport or teardown work from starving the realtime STT loop,
without changing the M2 audio buffer, prediction timeout, call ceilings,
request identity or stale-result rules. A deliberately blocking-provider test
proves the main loop remains responsive, and cancellation/failure propagation
tests prove cleanup and error semantics. The complete local gate now passes
**437 backend / 28 frontend tests**, lint, strict TypeScript, production build
and all three deterministic evaluations. One final Windows microphone recheck
of this isolated provider boundary remains required.

The 2026-10-18 R4 Windows recheck confirmed that isolation fixed the realtime
defect: continuity remained Normal, the UI stayed Live and no reconnect-buffer
warning or `continuity_degraded` cancellation occurred. The run still produced
no ready candidate. Its first neutral call was cancelled when the same
canonical utterance became provider-final, and a later long preface restarted
after an early correction but was finalized 344 ms after its second attempt
began. This isolated a narrower lifecycle issue: provider-final/awaiting-merge
metadata was rejecting even a deterministically compatible append-only
continuation. The runtime now preserves an already-running or ready attempt
through that metadata transition only when the existing lexical compatibility
policy succeeds and source, speaker, provenance, memory revision and
continuity remain unchanged. Material corrections and the authoritative
turn-finalized event still invalidate immediately. The revised local gate
passes **439 backend / 28 frontend tests**, lint, strict TypeScript, production
build and all three deterministic evaluations. One R5 Windows microphone
recheck remains mandatory before Phase J can pass.

The R5 Windows recheck again kept realtime continuity Normal and produced one
authoritative answer, but no prediction reached READY. Two bounded attempts on
the neutral preface were cancelled after 578 ms and 532 ms as the canonical STT
partial evolved; the turn recorded one preserved compatible extension and no
stale result. The same run exposed an independent answer-policy defect: the
general question was correctly detected and Gemini completed normally, but the
answer redirected to the earlier Redis topic instead of answering the current
request. This was prompt over-grounding, not an STT, detector or provider-call
failure.

R6 makes two narrow contract-preserving corrections. The answer policy now
states unambiguously that `current_request` is primary and permits general
knowledge for impersonal questions, while retaining the existing prohibition
on fabricated personal facts and the untrusted-content/no-tools boundary. The
prediction compatibility rule treats one terminal statement period and
long-stem inflection of fixed general-framing words such as `mention` to
`mentioned` as cosmetic; topic anchors, ordering, direct intent, correction,
provenance, memory, continuity and turn-finalized invalidation remain strict.
The local gate passes **445 backend / 28 frontend tests**, lint, strict
TypeScript, production build and all three deterministic evaluations.

The final R6 target-Windows checkpoint passed on 2026-10-18. A real
`gemini-3.5-flash-lite` prediction became ready with three bounded candidates
in 3,593 ms and remained current across seven compatible active-turn
extensions; it was ready 2,344 ms before authoritative turn finalization. A
subsequent Redis-to-DynamoDB correction cleared the advisory state and did not
flash stale output. An unrelated general question was answered directly, and
the post-refresh cache-miss question produced exactly one authoritative answer.
Refresh itself created no paid prediction or answer request. The reconnect
correctly marked prediction continuity unsafe until genuine new input, without
altering memory or Answer History. Stop returned the UI to Ready, released the
microphone, cleared prediction state and produced no unhandled backend error.
Realtime continuity remained Normal in the clean live checks. This completes
Phase J; the successful controlled benchmark remains a tiny curated result,
not general prediction accuracy.
Phase records are in `docs/MILESTONE_5_5_PHASE_0.md` through
`docs/MILESTONE_5_5_PHASE_I.md`.

## End-to-end system now verified

```text
Microphone PCM16 audio
  -> provider-neutral STT
  -> canonical transcript
  -> evolving immutable ActiveConversationTurn
       -> advisory PredictionRuntime + bounded speculative context
       -> optional stateless PredictionProvider -> Likely next UI
  -> authoritative finalized ConversationTurn
  -> logical-session ConversationMemory -> immutable MemorySnapshot
  -> deterministic bounded authoritative ContextPlanner
  -> positive AssistanceDecision + stable AnswerRequest
  -> source + recent + relevant older untrusted context
  -> existing AnswerPolicy and provider-neutral AnswerProvider
  -> unchanged logical-session AnswerRuntime
  -> bounded serialized events and separate idempotent answer/prediction UI
```

Ordinary statements do not create answers. Replay/resume and duplicate
submission do not create duplicate paid requests. Generated answers remain in
Answer History and never become conversation-memory facts automatically.

## Milestone 5.5 final architecture decisions

- `backend/app/services/prediction/` is a provider-neutral side-car domain.
  `TranscriptionSession` owns at most one same-session runtime when the feature
  is enabled; it never transfers ownership of M3 or M5 state.
- One stable UUIDv5 prediction ID derives from logical session ID plus active
  turn ID. Browser sockets, STT connections, input revisions and provider
  attempts are not part of that identity.
- A SHA-256 material fingerprint covers normalized active text, stable turn and
  ordered utterance provenance, source/speaker, continuity and
  `memory_revision`. Mutable canonical sequence/revision, timings and
  finalization-wait state are recorded separately and do not turn equivalent
  same-text provider-final input into a paid-call candidate.
- `input_revision` identifies materially changed input; `attempt` identifies an
  actual provider execution. Both are explicit and monotonic runtime contracts.
- Candidate output has hard absolute domain bounds: at most five candidates,
  240 characters per candidate, eight unique anchor terms and 64 characters per
  anchor. Production requests use at most three candidates and 512 output
  tokens.
- `TENTATIVE` and `STABLE` are operational readiness, never probabilities.
  `STABLE` requires candidate consistency across at least two material input
  revisions, an active turn awaiting finalization and normal continuity.
- Immutable snapshots represent scheduled/running/ready/invalidated/failed;
  idle is an empty logical-session snapshot. Invalidated/failed snapshots carry
  no prediction output bodies.
- Prompt policy and untrusted user content are structurally separate. M5.5
  conversation context is forced to `UNTRUSTED`.
- `ConversationTurnRuntime.observe()` returns M3's immutable update. WebSocket
  orchestration offers its active turn to `observe_nowait()` only after M3 has
  processed the canonical utterance; provider work never blocks STT.
- The logical-session runtime owns one latest slot, one supervisor and at most
  one executor task. Equality-gated completion, cancellation, timeout, hard
  attempt ceilings and exact lifecycle cleanup make newer input authoritative.
- The local trigger requires bounded meaningful input, suppresses exact
  backchannels, weak partials, ordinary final statements and degraded
  continuity, coalesces for 350 ms and enforces a 1,200 ms minimum interval.
  Attempts are capped at two per turn and 64 per logical session with one
  five-second timeout and no automatic retry. Following the Windows live
  partial-revision race, a cancelled in-flight attempt now delays the next
  paid attempt in the same turn by 4,000 ms; corrections still clear old output
  immediately and finalization cancels scheduled work. The backend reports a
  content-free per-turn attempt/cancellation/readiness summary.
- While an attempt is already running or ready, at most 96 normalized changed
  characters may retain its basis revision only when a deterministic local
  policy proves that the full earlier lexical prefix remains intact. Cosmetic
  case/comma/hyphen churn, one unfinished-token completion and general framing
  terms are allowed; questions, corrections, reordered/deleted words, pivots,
  unknown terms and all provenance/context changes invalidate. This is
  operational compatibility, not semantic similarity or confidence.
- Context is planned only in the worker after eligibility. It budgets active
  input first, then two recent turns and up to two topic-relevant older turns
  under 3,200 total characters (1,200 active; 800 per memory turn). A fresh
  mismatched `memory_revision` invalidates before an attempt is consumed.
- Disconnect clears/cancels prediction and resume alone schedules no call.
  Stop/reset/expiry/shutdown and degraded continuity have explicit reasons.
- `PredictionProvider` remains a one-shot protocol separate from
  `AnswerProvider`. Deterministic fake and stateless Gemini Interactions
  adapters implement that boundary without tools/search/grounding.
- Additive `prediction.snapshot` events are coalesced by prediction ID. A pure
  reducer rejects stale/cross-session/malformed events and keeps live prediction
  separate from Answer History. The minimal UI labels output as advisory.
- Browser disconnect cancels and clears prediction; resume emits/replays no
  prediction and schedules no paid call until genuine safe canonical input.
- `PREDICTION_ENABLED=false` constructs no provider/runtime/task/event and is
  covered as the exact verified M5 rollback.
- The offline 11-case corpus passed all lifecycle/context checks. Its scripted
  anchor usefulness is not a claim of general model accuracy.
- Speculative answer generation was rejected at the Phase H decision gate. No
  production path or flag exists and `F-045` remains planned.

The final automated gate is 445 backend tests and 28 frontend tests, plus lint,
strict TypeScript, production build, the M5 deterministic memory evaluation,
the M5.5 prediction evaluation and the speculative decision gate. All passed.
No dependency was added or upgraded. The final target-Windows microphone,
provider, reconnect, correction, answer and Stop checks also passed. M5.5 is
complete and verified; `docs/MILESTONE_5_5_HANDOFF.md` is the closeout record.

## Milestone 5 architecture decisions

### Memory domain, identity and trust

- `ConversationMemory` is provider-neutral and owned by the logical
  `TranscriptionSession`, never a WebSocket, provider connection, Gemini
  interaction, answer provider or frontend reducer.
- It observes immutable finalized M3 `ConversationTurn` objects only and never
  mutates transcript or conversation history.
- Stable session/turn identities are validated. Duplicate/replay and stale input
  do not change state or revision; cross-session and invalid identities are
  rejected.
- One committed turn increments monotonic `memory_revision` exactly once.
- Snapshots, entries, gaps and provenance are frozen and tuple-backed.
- M5 entries are `VERBATIM_CONVERSATION` and `UNTRUSTED`. Reserved
  `DERIVED_MEMORY` is also constrained to untrusted provenance.
  `FUTURE_VERIFIED_CONTEXT` is a distinct reserved source for M6.
- A remembered claim records only that it was said. It is not a verified
  profile, resume, project or document fact.

### Hard bounds and eviction

- Storage defaults: 256 retained finalized turns, 160,000 combined text
  characters and 4,000 characters per memory entry.
- Context defaults: source, four recent turns, up to four relevant older turns,
  2,000 characters per selected turn and 6,000 total characters.
- Storage and answer-context bounds are independent and validated.
- Oldest entries are evicted deterministically until both storage bounds hold.
  Eviction and forward sequence gaps remain explicit and degrade continuity.
- Entry truncation is a deterministic prefix with explicit metadata. Memory has
  no unbounded historical ID set or hidden raw-copy list.

### Context planning and follow-ups

- `ContextPlanner` is a replaceable provider-neutral strategy.
- The source always receives budget first. Four immediately preceding retained
  turns handle short references such as “Why?” and “How does that work?”
- Non-recent candidates use bounded Unicode-normalized topic terms and exact
  overlap. They rank by overlap then recency and serialize chronologically.
- No-match adds no older context; unavailable or mistranscribed topics are not
  invented.
- Unicode format controls are normalized out. Planner re-extraction is a bounded
  fallback only when derived term metadata is unexpectedly empty.
- Topic terms are lossy untrusted retrieval metadata. Full entity tracking,
  topic transitions and Conversation Radar remain future features.

### Answer integration

- `MemoryAnswerContextAssembler` maps an immutable snapshot/planner result into
  internal `AnswerContext`; `AnswerProvider` and `AnswerRuntime` are unchanged.
- Prompt JSON separates current, recent and relevant-older untrusted content
  from trusted policy and carries revision/continuity/gap metadata.
- Missing/inconsistent memory safely falls back to the verified M4 assembler.
- Observation and planning are local bounded work; provider generation remains
  an independent task and does not block STT.
- Logs contain timings/revisions/aggregate counts and characters, never memory,
  transcript or answer bodies.

### Lifecycle, privacy and retention

- Browser disconnect retains memory only within the existing 30-second resume
  lease. Resume reuses identity/revision and does not re-observe replayed turns.
- STT provider rotation and answer-provider failure do not replace memory.
- Stop, reset, expiry and shutdown logically delete memory with the session.
- Backend restart intentionally loses memory. M5 adds no database, disk memory,
  Redis, vector database or browser persistence of memory bodies.
- Logical deletion is not a claim of cryptographic process-RAM wiping.

### Summary/compaction decision

Deterministic bounded memory is sufficient for M5. Controlled evaluation passed
the required follow-up/topic-return cases without an extra API call. No
summarizer or background compaction task was added. Any future derived summary
must have a separate provider-neutral bounded lifecycle, stale-result protection
and untrusted source-range provenance.

## Verification record

- Backend: **261 passed** on the final automated gate; two known dependency
  deprecation warnings. The initial target-Windows checkpoint ran 259 tests
  before two retrieval-hardening tests were added; corrected behavior was then
  rechecked on Windows.
- Frontend: **21 passed**; ESLint, strict TypeScript and production build passed.
- Offline 300-turn/120-minute evaluation passed. Turn pressure retained 256
  turns/28,218 characters with 44 explicit evictions; character pressure stopped
  exactly at 160,000 characters.
- Fixed older-topic context used 567 characters (2.01% of retained text). The
  character/4 token figures are explicit proxies, not provider token counts.
- Final local medians were 0.0488 ms observation and 0.1408 ms planning in this
  environment; they are not cross-machine guarantees.
- Target-Windows microphone verification passed recent follow-up, ordinary
  statement suppression, refresh/resume, post-resume answering, older-topic
  selection with `selected_relevant_turn_count >= 1`, Stop/microphone release and
  no unhandled exception.
- A controlled Windows attempt also verified honest no-match: STT rendered the
  intended topic anchor as unrelated text and retrieval correctly stayed zero.

## Stable contracts — do not change without reason

- Backend owns transcript, finalized turns, assistance decisions, memory and
  answer truth.
- `STTProvider`, `ConversationTurnEngine`, `AssistanceDetector`,
  `ContextPlanner`, `AnswerContextAssembler`, `AnswerProvider`,
  `PredictionProvider`, `PredictionTriggerPolicy` and
  `PredictionContextPlanner` remain provider-neutral boundaries.
- Stable IDs/revisions/sequences, provenance, replay, supersession,
  cancellation and terminal-state semantics remain unchanged.
- Conversation Memory and Answer History are separate. Generated answers must
  never enter conversation memory automatically.
- Prediction remains advisory, RAM-only and separate from canonical transcript,
  finalized turns, Conversation Memory, verified facts, Answer History and
  application policy.
- Conversation/derived memory remains untrusted, never system policy or verified
  personal truth.
- Browser transcript/turn/question/answer events remain backward compatible;
  M5 adds no frontend memory event or persisted body.
- Logical session, browser lease, STT connection, provider interaction and
  answer stream remain separate lifetimes.
- `MEMORY_CONTEXT_ENABLED=false` restores M4 bounded context.
- `ANSWER_GENERATION_ENABLED=false` restores M1–M3 behavior.
- `CONVERSATION_ANALYSIS_ENABLED=false` restores the M2 transcript path.
- `PREDICTION_ENABLED=false` constructs no prediction runtime/provider/task/event
  and restores the exact verified M5 path.

## Deferred engineering register

### Carried forward

- **M3-DEFER-01 — broader assistance-language coverage.** Broad implicit,
  ambiguous and multilingual intent understanding remains deferred.
- **STT accuracy — provider/audio dependent.** Memory cannot recover a topic the
  provider did not transcribe. The M3 accuracy profile remains authoritative.
- **M4-DEFER-01 — durable sessions/tasks.** Backend restart cannot resume
  transcript, memory or answers. Durable retention belongs with later users,
  history, encryption and deletion design.
- **M4-DEFER-03 — progressive answers.** Two-pass generation remains outside M5.
- **M4-DEFER-04 — explicit regeneration/retry UX.** No automatic retry or browser
  regeneration control is added.
- **M4-DEFER-05 — richer rendering/timeline.** Session Timeline/Q&A navigation
  remains M5.6.
- **M4-DEFER-06 — production persistence/scale.** Multi-worker coordination
  requires durable ownership.
- **M4-DEFER-07 — provider latency variance.** Real latency remains network and
  provider dependent.

### Added/resolved by Milestone 5

- **M4-DEFER-02 — richer memory: PARTIALLY RESOLVED.** M5 completes bounded
  current-session memory and retrieval. Summaries, verified documents/RAG and
  durable history remain deferred.
- **M5-DEFER-01 — derived summary/compaction.** Not justified by M5 evaluation;
  revisit only with controlled quality evidence.
- **M5-DEFER-02 — full topic/entity model.** Bounded normalized terms and active
  correction/topic-transition invalidation now exist; persistent topic state,
  open threads and Radar remain future work.
- **M5-DEFER-03 — authoritative-history bounds.** ConversationMemory is bounded,
  but canonical transcript, finalized-turn replay and answer-history collections
  retain current-session state. Do not silently evict these domains without
  explicit replay/UX requirements.
- **M5-DEFER-04 — full dependency lock.** `google-genai==2.23.0` is constrained;
  platform-dependent transitive packages remain range-resolved.

### Added by Milestone 5.5

- **M5.5-DEFER-01 — provider-calibrated operational limits.** Deterministic
  stress, the four-call controlled benchmark and one successful live prediction
  support the current conservative bounds. They do not establish a provider
  latency distribution; future changes may not silently raise ceilings.
- **M5.5-DEFER-02 — multilingual semantic trigger coverage.** Phase C includes
  bounded English and common-Hinglish signals, not general multilingual intent
  understanding. Broader language handling requires corpus evidence and must
  not become an unbounded or provider-coupled heuristic.
- **M5.5-DEFER-03 — speculative answer generation.** The strict fake-provider
  gate accepted only exact full-evidence compatibility and showed no measured
  net benefit. No production implementation or flag was added; `F-045` remains
  planned.
- **M5.5-DEFER-04 — calibrated prediction confidence.** M5.5 exposes only
  deterministic `TENTATIVE`/`STABLE` readiness. Statistical probability remains
  unavailable until a representative labeled corpus and calibration exist.
- **M5.5-DEFER-05 — cancelled cloud-call billing visibility.** Provider-side
  billing for client-cancelled in-flight requests remains unknown. The runtime
  bounds attempts and records cancellation counts but never claims cancelled
  work was free.

## Dependencies and environment

M5 adds no runtime package. `backend/constraints.txt` constrains
`google-genai==2.23.0`; Windows setup installs through it.

M5 environment controls:

- `MEMORY_CONTEXT_ENABLED`
- `MEMORY_MAX_RETAINED_TURNS`
- `MEMORY_MAX_RETAINED_TEXT_CHARS`
- `MEMORY_MAX_TURN_CHARS`
- `MEMORY_CONTEXT_RECENT_TURNS`
- `MEMORY_CONTEXT_RELEVANT_TURNS`

Existing answer-context limits continue to bound provider input.

M5.5 adds independent provider/model, trigger, coalescing, turn/session-call,
timeout, output and context-character controls documented in
`backend/.env.example`. Production consumes them only inside the optional
prediction boundary.

## Next milestone boundary

M5.5 is closed. M5.6 may navigate separate Answer History without rewriting
prediction or memory; live prediction state can coexist with historical answer
browsing. M6 may add verified profile/document context as a distinct provenance
source without changing `PredictionProvider` or `AnswerProvider`. Before either
milestone starts, inspect this file, `docs/FEATURE_ROADMAP.md` and
`docs/MILESTONE_5_5_HANDOFF.md`; do not merge prediction candidates into facts,
ConversationMemory or Answer History.

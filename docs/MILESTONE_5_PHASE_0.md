# Milestone 5 Phase 0 — preflight and architecture decision

**Status:** COMPLETE. Milestone 5 runtime implementation has not started.

**Date:** 2026-09-13

## Authoritative inputs and inspection

Phase 0 used the supplied `mentara-milestone-4-complete` archive as the
implementation baseline and the separately supplied feature roadmap as the
planned-feature register. The source archive contained 149 regular repository
files and no unsafe archive paths or symbolic links.

The inspection covered:

- `PROJECT_STATE.md`, `README.md`, all milestone handoffs, every M4 phase
  document, the M4 model benchmark, architecture and troubleshooting docs, and
  the deferred-engineering register;
- every backend application module, including WebSocket/outbound coordination,
  configuration/logging/events, STT, canonical transcript, logical-session
  registry, conversation analysis, answer context/policy/provider/runtime and
  application startup;
- all 26 backend test modules;
- frontend event types, transcript/conversation/answer reducers, reconnect
  policy, streaming hook, transcription console, worklet, all frontend tests,
  lint/TypeScript/build configuration and package lock;
- environment examples, requirements, setup/start/verify/configuration/
  diagnostic/benchmark/accuracy helpers and `.gitignore`.

No genuine M4 correctness defect was found, so M5 may proceed after this Phase 0
checkpoint.

## M4 closeout consistency

The implementation supports the recorded M4 architecture and closeout claims:

- M3 derives immutable, deterministic `ConversationTurn` and
  `AssistanceDecision` objects downstream of canonical transcript state.
- A positive decision creates a deterministic `AnswerRequest`; browser JSON is
  not an answer-generation authority.
- `AnswerRuntime` is owned by the logical `TranscriptionSession`, runs provider
  work in an independent task, permits one active generation and implements
  latest-meaningful-request-wins.
- Browser detach retains the same session and answer task during the bounded
  30-second lease. Resume replays transcript, conversation and answer snapshots
  without rerunning detection or generation.
- Stop, reset, fatal teardown, expiry and shutdown cancel answer work. STT
  provider rotation and answer-provider failure do not replace session state.
- `BoundedAnswerContextAssembler` sends the source turn plus at most two recent
  preceding turns, with validated per-turn and total character limits.
- `ConciseAnswerPolicy` keeps trusted application policy structurally separate
  from serialized untrusted transcript content and prohibits invented personal
  facts, secrets and tools.
- `AnswerProvider` remains provider-neutral. Gemini uses async stateless
  Interactions with streaming and `store=false`; it sends no provider-history
  ID or tools.
- The bounded prioritized outbound writer is the only WebSocket sender and
  coalesces answer deltas. Frontend reducers are pure, session-bound and
  idempotent.
- Normal logs contain state, sequences, timings, categories and aggregate token
  usage—not transcript, question or answer bodies. Browser `sessionStorage`
  contains only the opaque resume token and active-session marker.

### Non-blocking discrepancies and risks

1. The separately supplied feature roadmap did not yet travel in the M4 ZIP.
   It is now present as `docs/FEATURE_ROADMAP.md` with all stable IDs preserved.
2. Project and roadmap current-state labels still said M5 was next; they now say
   M5 is in progress without promoting any unimplemented M5 feature.
3. Roadmap feature `F-013` depended on unrelated desktop feature `F-071`. The
   dependency now points to provider-neutral STT and future profile/document
   sources; ID, target and status are unchanged.
4. `backend/app/main.py` still reports M1 in the informational root response.
   Health and product behavior are unaffected. Runtime code is intentionally not
   changed in Phase 0; update this metadata during M5 closeout.
5. Canonical transcript history, M3 finalized-turn history and M4 answer history
   remain current-session, in-RAM histories. Their existing lists are distinct
   from the new bounded `ConversationMemory`. M5 must not claim that all logical
   session state is globally bounded or silently evict replay/domain history.
   Product semantics for bounding those authoritative histories remain a
   separate future decision.

## Automated preflight result

The clean Linux-equivalent of `verify.bat` passed before Phase 0 changes and
again after the roadmap, state and dependency-constraint changes:

- backend: **216 passed**, with the same two dependency deprecation warnings;
- frontend reducer suite: **21 passed**;
- frontend ESLint: **passed**;
- frontend strict TypeScript check: **passed**;
- frontend production build: **passed**.

The automated environment used Python 3.12.14 and Node 24.19.0. The target setup
continues to require Python 3.11 on Windows, so the final M5 gate still requires
the short target-Windows checkpoint. No real microphone, browser permission or
private Gemini credential was available or needed for Phase 0.

## Dependency reproducibility decision

The frontend already has an exact npm lock and setup uses `npm ci`. Backend
requirements intentionally express compatible ranges, but the M4 provider
benchmark was verified specifically with `google-genai 2.23.0`. Silent movement
within the 2.x range is a material adapter risk.

Phase 0 therefore introduces `backend/constraints.txt` and makes Windows setup
install requirements through it. Only `google-genai==2.23.0` is constrained.
This preserves simple setup and the declared compatibility ranges without
blindly freezing platform-dependent transitive packages. It is a foundation,
not a claim of fully reproducible cross-platform dependency resolution.

## M5 ownership and flow

The approved ownership remains:

```text
Logical TranscriptionSession
├── TranscriptAggregator
├── ConversationTurnEngine
├── AssistanceDetectionEngine
├── AnswerRuntime
└── ConversationMemory
```

The intended runtime flow is:

```text
Finalized ConversationTurn
  -> ConversationMemory.observe(turn)
  -> immutable MemorySnapshot + memory_revision
  -> deterministic ContextPlanner
  -> source + recent + relevant older context
  -> existing AnswerPolicy
  -> existing AnswerProvider
  -> existing AnswerRuntime
```

`ConversationMemory` is never owned by a browser socket, provider connection,
Gemini interaction, answer provider or frontend reducer. It observes finalized
M3 turns only and never mutates canonical transcript or turn objects.

## Provider-neutral domain contracts

Phase A will introduce `backend/app/services/memory/` with small immutable
contracts:

- `ContextSourceKind`: `VERBATIM_CONVERSATION`, `DERIVED_MEMORY`, and reserved
  `FUTURE_VERIFIED_CONTEXT`;
- `ContextTrust`: `UNTRUSTED` and reserved `VERIFIED`;
- `ContextProvenance`: source kind, trust, source turn IDs and source sequence
  range. Validation forbids conversation or derived content from being marked
  verified;
- `MemoryEntry`: logical session ID, stable turn ID and sequence, speaker/source,
  M3 continuity quality, bounded text, truncation metadata, canonical source
  utterance/sequence provenance and bounded deterministic topic terms;
- `MemorySnapshot`: session ID, tuple of entries, monotonic `memory_revision`,
  stored counts/chars and explicit eviction/sequence-gap metadata;
- `MemoryObservationStatus`: `COMMITTED`, `DUPLICATE`, or `STALE_IGNORED`;
- `ConversationMemory`: synchronous bounded observe/snapshot/clear behavior;
- `ContextPlanner`: replaceable local selection protocol; and
- `PlannedAnswerContext`: source, recent, relevant older, provenance, continuity,
  revision, selected counts and bounded text size.

Dataclasses/views will be frozen and collection fields will be tuples. A caller
can read a `MemorySnapshot` but cannot append, remove or replace memory entries.

### Observation, identity and ordering

- Only immutable finalized `ConversationTurn` values are accepted. Active or
  partial turn state has no observation path.
- Session mismatch raises a domain error and changes nothing.
- The stable turn ID is the dedupe key. Re-observing it returns `DUPLICATE` and
  neither changes stored state nor increments revision.
- A reused sequence with different identity/provenance is an invariant error.
- An unknown turn older than the latest committed sequence returns
  `STALE_IGNORED`; it cannot reorder memory.
- A forward sequence gap may be committed, but the snapshot records degraded
  continuity and the missing range honestly.
- Repeated identical text with different valid turn IDs is committed as distinct
  conversation because textual equality is not identity.
- One successful observation is one atomic memory commit. Revision increments
  exactly once, including any deterministic evictions caused by that commit.
  Duplicate, stale, rejected, snapshot and lifecycle-clear operations do not
  increment it.

## Hard storage and context bounds

The Phase A starting limits are explicit, validated and environment-driven:

| Bound | Initial value | Meaning |
|---|---:|---|
| retained memory turns | 256 | Maximum committed entries per session |
| retained memory text | 160,000 chars | Maximum combined stored entry text |
| one memory entry | 4,000 chars | Deterministic prefix cap, marked truncated |
| recent context turns | 4 | Maximum preceding recent selections |
| relevant older turns | 4 | Maximum non-recent relevance selections |
| answer context total | 6,000 chars | Existing hard prompt text ceiling |
| one answer-context turn | 2,000 chars | Existing per-turn prompt ceiling |

These are implementation starting values, not performance claims. Phase E must
exercise synthetic 60–120+ minute corpora and may tune defaults before M5
closeout while preserving explicit hard caps.

After a commit, oldest entries are evicted first until both retained-turn and
retained-character limits hold. The snapshot preserves cumulative evicted turn
count and the highest evicted sequence. It never represents evicted text as
available. Source continuity from M3 remains on each entry; eviction and observed
sequence gaps are separate snapshot-level continuity signals.

Storage bounds and model-context bounds are independent. The memory may retain
far more bounded history than one provider request receives.

## Context selection policy

The first `ContextPlanner` uses no embedding, vector database, model call or new
dependency:

1. The current/source turn is always selected and receives first budget.
2. Up to four immediately preceding retained turns form the recent window. This
   resolves short pronoun/reference follow-ups such as “Why?” and “How does that
   work?” without a new classifier.
3. Non-recent candidates are scored from bounded normalized terms: Unicode
   case-folding, deterministic tokenization, a fixed stop-word set, exact
   distinctive-term overlap and recency as the final tie-breaker.
4. Up to four positive-score older turns are selected; ties resolve by stable
   turn sequence. Final prompt order is chronological even though ranking is by
   relevance.
5. No-match queries add no older turns. A short follow-up with no distinctive
   terms intentionally relies on the recent window.
6. Per-turn and total character caps are applied after selection. No plan may
   exceed the hard total.

The small `topic_terms` tuple is lossy, untrusted metadata derived locally from
conversation text. It is not entity truth, a profile fact or a full Conversation
Radar. The extraction strategy remains replaceable for M5.5/M6.

## Answer integration and rollback boundary

M5 will add a memory-aware `AnswerContextAssembler` implementation behind the
existing protocol. It receives a read-only snapshot provider and the
`ContextPlanner`; the `AnswerProvider` still receives only the existing
provider-neutral `AnswerPrompt`.

The single composition decision is `MEMORY_CONTEXT_ENABLED`:

- `true`: attach `ConversationMemory` to the logical session and use the
  memory-aware assembler;
- `false`: attach no memory and construct the verified M4
  `BoundedAnswerContextAssembler` with its current recent-window behavior.

The flag will be resolved where a logical session and its answer runtime are
composed, not checked throughout domain/runtime code. Existing
`ANSWER_GENERATION_ENABLED=false` and `CONVERSATION_ANALYSIS_ENABLED=false`
rollback layers remain unchanged.

M5 may add fields to internal `AnswerContext`, but it will not change answer ID,
attempt, lifecycle, task ownership, cancellation, supersession, replay, provider
stream events or browser answer events. Trusted policy and each untrusted
context section remain structurally separate.

## Lifecycle semantics

- **Browser disconnect:** detaches route-owned sinks/timers/provider and retains
  the same session-owned memory during the existing 30-second lease.
- **Browser resume:** leases the same `TranscriptionSession`; it does not rebuild
  or re-observe memory from outbound replay.
- **STT provider rotation:** changes only the provider generation; memory object,
  entries and revision are unchanged.
- **Answer-provider failure:** changes only answer state; memory is unchanged.
- **Stop/fatal teardown/reset/registry expiry/shutdown:** cancel relevant tasks,
  logically clear memory bodies and release the logical session. Reset receives
  a fresh memory identity and revision zero; previous entries cannot leak.
- **Backend restart:** loses all M5 memory intentionally. No persistence,
  database, Redis, local memory file or browser memory body is introduced.

Logical deletion means references are removed as part of session cleanup. It is
not a claim of cryptographic process-RAM wiping.

## Trust, provenance and poisoning boundary

Finalized conversation is `VERBATIM_CONVERSATION / UNTRUSTED`. Mentara may
remember that someone said “I handled ten million requests per second,” but it
cannot convert the claim into a verified personal fact. Prompt-injection text is
stored only as untrusted conversation and cannot overwrite application policy,
reveal secrets, enable tools or acquire verified status.

Generated answers never enter `ConversationMemory`: the only ingress is the M3
finalized-turn callback. Existing `AnswerSessionSnapshot` history remains a
separate domain for later UI work. Any future “accepted/used answer” feature
requires a new explicit provenance-bearing event.

`DERIVED_MEMORY` is reserved for future lossy summary/extraction and remains
untrusted with source-range provenance. `FUTURE_VERIFIED_CONTEXT` is reserved for
M6 profile/resume/document facts and is not stored by `ConversationMemory`.

## Summary/compaction decision process

Phase E will first test deterministic bounded memory on controlled short
follow-ups, long-range named-topic returns, no-match cases, eviction gaps,
prompt-size growth and local planning latency. The default decision is **A:
deterministic memory is sufficient for M5** if those cases pass within bounds.

Decision **B** is permitted only if measured failures demonstrate that a derived
summary materially improves M5 correctness. Before a real provider call, B
requires a separate `MemoryCompressor`/`MemorySummarizer` protocol, fake
implementation and lifecycle tests for asynchronous non-blocking execution,
bounded task count, timeout/failure/cancellation, stale completion, atomic
commit, provenance and untrusted status. It must not use `AnswerRuntime`, block
STT/answers or discard raw source before successful summary commit.

## Future compatibility hooks

### M5.5 Predictive Next-Turn

Prediction will read `session.memory_snapshot()` plus
`session.conversation_snapshot().active_turn`. The frozen snapshot and monotonic
revision support cheap cache invalidation without giving prediction ownership or
mutation rights. No prediction or speculative request is implemented in M5.

### M5.6 Session Timeline / Q&A Navigator

Conversation memory remains separate from answer history. Existing answer
snapshots retain stable answer/detection/source-turn identity, so a future
navigator can map Q&A, browse previous/next and return to live while current STT
and new answers continue. M5 adds no timeline UI and does not collapse generated
answers into conversation truth.

### M6 Profile, documents and Truth Lock

The context-orchestration boundary can later accept additional typed sources:
verified profile facts, verified documents and authorized screen context.
Their provenance/trust labels remain distinct from untrusted conversation and
derived memory. `AnswerPolicy`, not the WebSocket route or provider, decides how
those sections are serialized and constrained. `AnswerProvider` remains
unchanged.

## Metrics and privacy verification plan

M5 logs/metrics may include only content-free values:

- `memory_observe_ms`, `context_assembly_ms`, `memory_revision`;
- `stored_turn_count`, `stored_text_chars`;
- `selected_recent_turn_count`, `selected_relevant_turn_count`; and
- `context_text_chars`.

No memory, transcript, question or answer body; topic term; resume token; API
key; or full provider error is logged. Phase F must test prompt injection,
unverified claims, feature rollback, lifecycle cleanup, absence of browser
persistence and log capture with sentinel text.

## Minimum later Windows checkpoint

No Windows work is required for Phase 0. After all M5 automated phases pass, the
only manual target checkpoint is:

1. run `verify.bat` in a Command Prompt at the project root;
2. start backend and frontend using their existing `.bat` helpers;
3. start transcription, establish one topic, ask “Why?”, briefly change topic,
   then return to the original named topic;
4. confirm an ordinary statement creates no answer;
5. refresh within the resume lease, ask another follow-up, then Stop; and
6. confirm microphone release, no duplicate request/state and no unhandled
   backend exception.

This is deliberately short; long-session bounds belong to synthetic automated
tests. No API key should be shown or sent anywhere.

## Contracts that remain untouched

- PCM16 browser audio and provider-neutral `STTProvider`;
- canonical transcript IDs/revisions/sequences and immutable finalization;
- M3 turn/detection identity, provenance, active-turn snapshot and detector
  policy;
- answer request/ID/attempt and all answer lifecycle transition semantics;
- independent `AnswerRuntime`, single-active/latest-request-wins policy and
  failure/cancellation/timeout behavior;
- provider-neutral `AnswerProvider` and stateless Gemini adapter;
- transcript/turn/question/answer WebSocket events, outbound ordering,
  coalescing/backpressure and idempotent frontend reducers;
- logical-session lease/resume semantics and provider-rotation independence;
- normal log privacy and backend-only credentials; and
- M2 and M1–M3 rollback flags.

Phase A must stop rather than weaken any of these contracts.

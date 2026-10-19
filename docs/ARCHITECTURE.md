# Mentara AI architecture

## Verified Milestone 1 runtime pipeline

1. Chrome requests microphone permission through `getUserMedia()`.
2. A Web Audio `AudioContext` runs at 16,000 samples per second with one channel.
3. `public/audio/pcm16-worklet.js` converts browser `Float32` samples into signed
   little-endian PCM16 chunks of approximately 100 ms.
4. The frontend sends binary audio frames to FastAPI over `/ws/transcribe`.
5. The backend selects an adapter through the `STTProvider` factory and opens an
   authenticated server-side Gemini Live API WebSocket. The API key never enters
   frontend code or browser storage.
6. Gemini transcription messages become provider-neutral `TranscriptResult`
   values.
7. `TranscriptAggregator` converts provider results into canonical utterance
   revisions and suppresses duplicate/no-op events.
8. Canonical utterances become `transcript.partial` or `transcript.final` browser
   events.
9. Stop releases browser media resources and sends `audioStreamEnd` so Gemini can
   flush the final transcript.

## Stable boundaries

- `frontend/src/hooks/use-streaming-transcription.ts` owns browser media resources
  and the browser WebSocket lifecycle.
- `backend/app/api/websocket.py` coordinates connections without containing
  provider-specific protocol details.
- `backend/app/services/stt/base.py` defines the provider-neutral STT contract.
- `backend/app/services/stt/factory.py` selects the configured adapter.
- `backend/app/services/stt/gemini.py` contains Gemini protocol details.
- `backend/app/services/stt/deepgram.py` is an inactive future option.
- `/ws/health` remains independent of STT, API keys, microphone capture and audio
  formatting.

Browser-to-backend audio uses binary frames. Provider-specific Base64 JSON framing
occurs only inside the Gemini adapter.

## Network events

Backend-to-browser messages retain these event names:

- `status`
- `transcript.partial`
- `transcript.final`
- `error`
- `pong`

Phase B3 adds `session.ready` for the opaque resume token and logical-session
identity. It does not rename any existing status or transcript event.

Milestone 3 adds `turn.finalized` and `question.detected`. They are downstream,
additive events; existing clients may ignore them without changing M2 behavior.

Milestone 4 adds `answer.started`, `answer.delta`, `answer.completed`,
`answer.cancelled`, `answer.superseded`, `answer.failed` and `answer.snapshot`.
They expose Mentara answer state and provenance, never Gemini stream structures
or provider interaction IDs.

Phase A2 extends transcript payloads additively without renaming the verified
events. Both transcript events carry canonical IDs, sequence, revision, source,
speaker role and application-observed timing. Optional values are omitted when
unknown.

## Milestone 2 canonical transcript flow

```text
Raw STT Provider Events
        ↓
TranscriptAggregator
        ↓
Canonical Transcript State
        ↓
Canonical Application Events
        ↓
FastAPI WebSocket
        ↓
Frontend Transcript Reducer
        ↓
Existing UI
```

The backend is the authoritative transcript-state owner. The frontend is a
rendering and client-state layer.

These lifetimes must remain distinct:

```text
MENTARA LOGICAL SESSION
≠ BROWSER WEBSOCKET CONNECTION
≠ STT PROVIDER CONNECTION
```

Phase A1 implemented and tested `backend/app/services/transcript/` in isolation.
Phase A2 now creates one aggregator inside each `/ws/transcribe` coordinator and
routes all provider results through it before browser events are emitted.

Phase B1 makes the first separation concrete in code. `TranscriptionSession`
owns the canonical aggregator, connection state and provider-generation counter.
Phase B2 now replaces provider connections without replacing that logical
session or transcript state. `RotatingSTTProvider` implements the unchanged
`STTProvider` contract and receives fresh adapters from the existing factory.
Phase B3 adds the bounded registry so the same logical session can also survive
browser WebSocket replacement without moving canonical ownership into either
connection object.

The backend lifecycle states are `connecting`, `connected`, `reconnecting`,
`degraded`, `error` and `stopped`. The browser preserves its existing `ready`
status event for initial connection compatibility and additionally understands
`reconnecting` and `degraded` events for Phase B2.

## Canonical utterance model

The canonical state supports:

- `session_id`
- `utterance_id`
- `sequence`
- `revision`
- `audio_source`
- `speaker_role`
- `text`
- `is_final`
- `first_seen_ms`
- `last_updated_ms`
- `finalized_ms`
- optional `confidence`

Milestone 2 currently uses `audio_source=microphone` and
`speaker_role=local_user`. Both are enums that already reserve future system
audio and remote-speaker values without implementing those features now.

Phase A3 stores this payload in a pure frontend reducer keyed by
`utterance_id`. Rendering still exposes the existing interim/final UI, but those
views are now selectors over canonical state instead of independent text arrays.

The reducer accepts only positive sequences and revisions, rejects events older
than the latest accepted session sequence, rejects non-increasing revisions for
an existing utterance, and never modifies an utterance after finalization. Once
bound to a `session_id`, it rejects another session until the hook explicitly
resets state for a new transcription run.

## Identity and ordering

- Mentara generates UUIDs for sessions and utterances.
- One utterance keeps one ID across every partial revision and finalization.
- `revision` starts at 1 and changes only when canonical utterance state changes.
- Finalization is a state change even when final text equals the latest partial.
- `sequence` is session-wide and increases only for emitted canonical changes.
- Empty and identical partial events consume no revision or sequence.
- Provider-specific identifiers do not enter the public application model.

## Timing semantics

`first_seen_ms`, `last_updated_ms` and `finalized_ms` are measured relative to a
monotonic Mentara session clock. They describe when the application observed a
provider event; they are not exact audio or speech boundaries.

No `speech_start_ms` or `speech_end_ms` is invented. Confidence remains absent
unless a provider actually supplies it.

## Duplicate policy

The current provider result contains no provider utterance ID. Phase A1 therefore
uses the smallest explicit heuristic needed for duplicate handling:

- Only exact text equality is considered; there is no similarity matching.
- An exact repeat of the most recently finalized text is ignored only when no
  utterance is active and it arrives inside a bounded 1,000 ms window.
- The same text after the window is treated as a new utterance.
- A final always finalizes an active utterance, even if it equals an older final.

This policy is covered by deterministic tests and remains replaceable if future
provider boundary metadata removes the ambiguity.

## Privacy and cost boundaries

- Provider API keys remain backend-only.
- Raw audio is not persisted.
- Normal diagnostic logs must not contain transcript text.
- Automated tests use fake provider events and consume no Gemini quota.
- Canonical state is in memory for the MVP; no Redis, PostgreSQL or queue is added.

## Provider longevity decision

The exact `gemini-3.5-transcribe-live` documentation specifies a 10-minute
maximum audio session. Generic Live API documentation describes WebSocket
session resumption and `GoAway` messages, but the model-specific guide does not
say resumption extends the model's maximum duration. Mentara will therefore use
controlled new-provider rotation, preferably after a finalized utterance.

Phase B2 adds a bounded maximum of 20 current audio chunks (approximately two
seconds) while switching. Overflow produces a degraded state and an honest
possible-audio-loss message; no zero-loss claim or unbounded buffer is allowed.

The connection-rotation flow is:

1. The initial Gemini adapter connects through the existing factory.
2. Audio always enters a 20-chunk bounded in-memory FIFO and is drained by the
   active provider generation.
3. At 540 seconds, Mentara rotates immediately if no partial utterance is active;
   otherwise it waits at most 10 seconds for that utterance's final boundary.
4. Audio sending pauses, the old adapter closes and a fresh adapter connects.
5. The same `TranscriptionSession` and aggregator process results from the new
   generation, so session ID, sequences and finalized history continue.
6. Buffered audio drains in FIFO order through the replacement adapter.

If no final boundary arrives, rotation still proceeds before the 600-second
provider limit and reports degraded continuity. A provider interruption also
reports degraded continuity because already-accepted audio cannot be proven to
have produced a result. If the bounded buffer fills, only the oldest unsent
chunk is discarded and the warning is emitted once per connection generation.

Only explicitly transient failures (`STTProviderTransientError`, network I/O or
timeout) are retried. Provider-declared protocol, authentication and quota
errors are terminal. Replacement attempts are capped at three with bounded
exponential delay. Stopping while a replacement is connecting cancels that
connection cleanly instead of waiting for the retry loop.

The wrapper does not store raw audio on disk, does not log transcript text and
does not change the public transcript events.

## Browser reconnection

`InMemoryTranscriptionSessionRegistry` owns detached logical sessions for a
bounded 30-second grace period behind the replaceable
`TranscriptionSessionRegistry` interface. A random opaque token identifies the
entry and an exclusive lease prevents two browser sockets from mutating one
aggregator concurrently.

On browser loss, the browser-bound provider closes and the logical session enters
`reconnecting`. On resume, a fresh provider is created through the unchanged
factory, the existing session enters `connected`, and its canonical snapshot is
replayed. Finalized utterances and the latest active partial keep their original
IDs, revisions and sequences. The frontend reducer therefore rebuilds an empty
page after refresh while treating replay to an existing page as a no-op.

The browser retains only the opaque token in tab-scoped session storage. Raw
audio and transcript text are never placed there. Audio is not buffered while
the browser WebSocket is down; explicit degraded status communicates that gap.

## Combined failure cleanup

Phase B4 keeps the architecture unchanged and strengthens its cancellation
boundary. If a browser disappears while `RotatingSTTProvider` is connecting a
replacement adapter, closing the browser-bound wrapper cancels that connect task,
closes both provider generations and retains only the canonical logical session
inside the bounded registry. Resume then creates a fresh provider through the
existing factory and continues from the stored canonical sequence.

Malformed browser text commands after a valid handshake are ignored unless they
are a recognized Stop command. They never enter the provider or aggregator.
Malformed provider protocol messages remain terminal `STTProviderError` values;
they do not cause an unbounded retry loop.

See `docs/MILESTONE_2_PHASE_B0_ANALYSIS.md` for the complete evidence and staged
implementation decision.

## Milestone 3 conversation flow

```text
CanonicalUtterance
        ↓
ConversationTurnRuntime
        ↓
ConversationTurnEngine
        ↓
ConversationTurn + turn.finalized
        ↓
AssistanceDetectionEngine
        ↓
question.detected (positive decisions only)
```

The canonical transcript engine remains the sole owner of transcript truth.
Conversation analysis observes canonical events after their transcript event is
sent; it cannot rewrite canonical text, IDs, revisions, sequences or history.

`TranscriptionSession` owns the turn and detection engines alongside—but
downstream of—the aggregator. This keeps derived snapshots alive across provider
rotation and the bounded browser-resume window. The `/ws/transcribe` route owns
only the cancellable timer runtime for its current browser lease.

## Turn contract and policy

A finalized `ConversationTurn` has a deterministic UUIDv5 derived from logical
session ID plus independent turn sequence. It records source canonical utterance
IDs and final transcript sequences, audio source, speaker role, derived text,
application-observed timing, finalization reason, continuity quality and measured
transcript-final-to-turn latency.

The default `TurnFinalizationPolicy` waits 250 ms after the latest canonical
final so adjacent provider-split finals can form one semantic turn. The value is
configurable and validated between 0 and 2,000 ms. A new same-source contribution
replaces the one deadline; source/speaker change finalizes an all-final previous
turn immediately. There is never more than one deadline task per attached route.

Active state is available through `ConversationTurnEngine.active_turn()` and
`ConversationSnapshot.active_turn`. This is the read-only future hook for
Predictive Next-Turn. Prediction itself is outside M3.

Stop flushes only canonical-final content before `stopped`; partial-only content
is cancelled. A browser disconnect pauses the timer and preserves active engine
state for resume. A resumed runtime rearms the existing deadline, preserving the
turn ID. Fatal provider failure flushes final content as degraded before the
existing error event. Terminal cleanup cancels and joins both peer tasks and the
deadline task.

## Assistance contract

`AssistanceDetector` is a replaceable provider-neutral protocol. The initial
implementation is a local deterministic heuristic for direct questions,
auxiliary forms, request/imperative prompts, short follow-ups and focused common
Hinglish cues. It suppresses explicit backchannels and ordinary statements.

`AssistanceDecision` contains `should_assist`, `question`/`request`/`none`, stable
source-turn identity, application-observed detection timing and an internal
reason code. It contains no invented probabilistic confidence and does no topic
routing. Only positive decisions become `question.detected` browser events.
Detection IDs are deterministic UUIDv5 values derived from turn IDs.

## Derived replay and frontend ownership

The conversation snapshot retains immutable finalized turns and positive
detections. On browser resume, the backend replays canonical transcript state
first, then derived turns and detections with their original IDs. No replay path
allocates new identity or re-runs detection.

The frontend conversation reducer keys state by turn/detection ID, enforces one
session, monotonic turn ordering and valid source-turn references, and ignores
duplicates. React renders backend decisions; it never classifies transcript text.

## M3 continuity, latency, privacy and rollback

An active turn becomes sticky `degraded` when provider or browser continuity is
uncertain. If there is no active turn, the degradation applies to the next
canonical-final contribution. Detection still runs and carries a source turn
whose quality future answer logic can inspect.

`transcript_final_to_turn_ms` and `turn_to_detection_ms` are measured with the
existing monotonic application clock. Normal analysis logs contain only turn
sequence, durations and the boolean decision—never spoken text, resume tokens or
audio.

The detector adds no external call, dependency or mandatory API cost. Set
`CONVERSATION_ANALYSIS_ENABLED=false` to preserve the M2 transcription-only
runtime. `CONVERSATION_TURN_MERGE_WINDOW_MS` controls the one bounded latency
policy.

## Milestone 3 closeout invariants

At the verified M3 boundary:

- the backend owns canonical transcript truth;
- M3 consumes `CanonicalUtterance` downstream and never mutates canonical
  transcript history;
- turn identity, independent order and canonical provenance are stable;
- `question.detected` refers to a stable source turn;
- browser replay is idempotent, provider rotation does not duplicate derived
  state, and browser resume preserves derived identity;
- active-turn state remains available through a read-only snapshot for future
  Predictive Next-Turn work;
- degraded continuity remains explicit rather than inferred away;
- deadline and peer tasks are paused, cancelled or joined on Stop, failure,
  disconnect, reset and expiry according to the documented policy;
- a future answer layer can consume `AssistanceDecision` and `ConversationTurn`
  without knowing Gemini or STT protocol details; and
- `CONVERSATION_ANALYSIS_ENABLED=false` restores the verified M2
  transcription-only path.

Milestone 3 remains **COMPLETE AND VERIFIED**. Milestone 4 consumes its stable
`AssistanceDecision` and `ConversationTurn` objects strictly downstream.

## Milestone 4 answer flow

```text
Positive AssistanceDecision + source ConversationTurn
        ↓
Stable AnswerRequest
        ↓
Bounded AnswerContextAssembler + AnswerPolicy
        ↓
Provider-neutral AnswerProvider
        ↓
Logical-session-owned AnswerRuntime task
        ↓
Backend AnswerLifecycle state
        ↓
Bounded OutboundEventWriter
        ↓
Pure frontend answer reducer + minimal streaming UI
```

`backend/app/services/answer/` owns domain models, identity, lifecycle, context,
policy, provider protocol, fake provider, runtime and the Gemini adapter. The
answer layer knows nothing about raw audio, STT protocol payloads or frontend
state. Internally it receives authoritative M3 objects; it never parses the
browser's `question.detected` JSON.

## Answer identity and lifecycle

One logical answer UUIDv5 is derived from the stable assistance-detection ID.
Attempt `1` is the only automatic M4 generation. This preserves logical identity
across replay while leaving a separate positive attempt field for future
explicit regeneration.

The explicit lifecycle is:

```text
requested -> starting -> streaming -> completed
     |           |           |
     +-----------+-----------+-> cancelled | superseded | failed
```

Revisions describe answer-state changes; stream sequences order text deltas.
Terminal states are honest and immutable: failure, cancellation and supersession
are not completion, and no terminal answer accepts more text.

## Non-blocking runtime and supersession

`AnswerRuntime` is owned by `TranscriptionSession`. The M3 finalized-turn
callback does only bounded local construction and a synchronous `request_answer`
handoff. Provider start, SSE iteration and completion run in a separate asyncio
task, so microphone/STT/transcript/turn work remains responsive during multi-
second generation.

At most one generation is active for a logical session. A newer positive
detection cancels the provider stream for the older active answer, marks it
`superseded` and starts the new request. Completed answers remain immutable.
M4 has no automatic provider retry; restarting after visible output could
duplicate or contradict it.

## Answer task and browser lifecycle

Answer state and active generation belong to the logical session rather than a
browser lease or STT connection. On browser disconnect the event sink detaches,
but generation may continue through the existing 30-second resume grace period.
Resume first replays transcript and conversation state, then authoritative
answer snapshots, and only then attaches the live sink. The deterministic answer
ID prevents a duplicate provider call.

Stop, session reset, fatal session teardown, resume expiry and backend shutdown
cancel and join active answer tasks and close provider streams/clients. STT
provider rotation has no ownership effect on an active answer. A provider answer
failure changes only answer state; healthy M1–M3 processing continues.

## Serialized bounded outbound events

`OutboundEventWriter` is the sole sender for `/ws/transcribe`. Producers publish
synchronously into a fixed-size per-browser buffer. Important status, session,
transcript, turn, detection and answer-lifecycle events are served before answer
deltas so token traffic cannot starve critical state.

Only one pending delta per answer is retained. Contiguous small chunks are
coalesced up to the configured character bound; Mentara does not send a browser
message per character. A terminal answer event flushes its pending text first.
If the fixed buffer cannot accept important work, the writer cancels the slow
browser lease rather than allowing unlimited memory growth. The logical session
remains eligible for bounded snapshot resume.

## Context and prompt boundary

`BoundedAnswerContextAssembler` includes the current source turn and at most two
recent finalized turns by default. Per-turn and total character caps are
validated configuration. This deterministic window is not full memory and does
not depend on provider interaction history.

`ConciseAnswerPolicy` creates two separate fields: trusted application/system
instruction and serialized untrusted conversation content. Spoken prompt-
injection text cannot change the application's secret, truth or no-tools policy.
M4 requests concise, speakable, scan-friendly plain text, prohibits invented
personal facts and requires generic/missing-context language when verified
personal facts are absent. The current request is always primary: unrelated
earlier turns may supply context but cannot redirect it. Impersonal general or
technical questions may use model general knowledge even when their subject is
absent from conversation memory; that allowance never turns conversational
claims into verified personal facts.

M5 can replace or extend the context assembler without changing answer identity,
lifecycle or provider contracts. M6 can inject verified fact-bearing context
through the same boundary.

## Gemini answer adapter

The production adapter uses the official `google-genai` 2.x async Interactions
API. It sends structured user input separately from `system_instruction`,
streams asynchronously and explicitly sets `store=false`. It does not send
`previous_interaction_id`, tools, search, grounding, credentials, resume tokens
or unrelated full transcript history.

Only text deltas and safe aggregate usage become provider-neutral events.
Authentication/configuration, rate limit, transient network, provider/server,
timeout, cancellation, safety and malformed-stream failures are sanitized. Raw
provider bodies remain outside browser state and normal logs.

The selected M4 default is `gemini-3.5-flash-lite` with `minimal` thinking,
based on the documented eight-call non-sensitive stateless comparison. Model,
thinking level, timeout, token cap and context bounds remain environment-driven.

## Answer replay and frontend ownership

The frontend answer reducer is pure and keyed by stable answer ID. It binds to
one logical session, checks detection/turn provenance, enforces revision and
stream ordering, ignores duplicates/stale/gapped/cross-session events and never
mutates a terminal answer. Snapshot replay is therefore idempotent. React only
renders backend-owned state; it does not classify questions or generate answers.

## M4 privacy, cost and rollback

- API credentials are backend-only.
- Raw audio is not persisted.
- Normal logs contain timings, state and optional aggregate usage, not transcript,
  question or answer bodies.
- Automated tests use deterministic fake providers and consume no quota.
- One positive detection creates at most one initial provider request.
- Provider storage is disabled, and provider history is not application memory.
- `ANSWER_GENERATION_ENABLED=false` removes the answer-provider call at one
  boundary while preserving M1–M3 and `question.detected`.
- `CONVERSATION_ANALYSIS_ENABLED=false` continues to preserve the M2 rollback.

Milestone 4 — Answer Engine + Streaming — remains **COMPLETE AND VERIFIED**.

## Milestone 5 memory and context flow

```text
Immutable finalized ConversationTurn
        -> logical-session ConversationMemory
        -> frozen MemorySnapshot + memory_revision
        -> provider-neutral ContextPlanner
        -> source + recent + relevant older context
        -> existing AnswerPolicy -> AnswerProvider -> AnswerRuntime
```

`backend/app/services/memory/` owns the M5 provider-neutral domain. The logical
`TranscriptionSession` owns exactly one optional `ConversationMemory` instance.
The WebSocket route wires that dependency and observes a turn after M3
finalization; it does not own memory. Browser leases, STT sockets, Gemini
interactions and answer tasks therefore cannot replace memory identity.

## Memory identity, observation and snapshot

Memory accepts only immutable finalized `ConversationTurn` objects for the same
logical session. A stable turn ID can commit at most once. A replay/duplicate or
stale sequence leaves memory and revision unchanged; cross-session and malformed
identity input is rejected. Repeated text with different valid turn identities
is retained because identity, not text equality, defines duplication.

One successful commit increments `memory_revision` exactly once. Entries,
provenance, gap records and snapshots are frozen dataclasses, and collections
are exposed as tuples. A reader such as future M5.5 prediction can observe a
snapshot without owning or modifying memory.

Forward sequence gaps, degraded source turns, truncation and eviction all leave
explicit continuity/gap evidence. M5 does not invent speech timestamps or claim
availability for data that was evicted.

## Independent hard bounds

The default memory-storage envelope is 256 finalized turns, 160,000 total text
characters and 4,000 characters per entry. Each entry is deterministically
prefix-truncated if necessary. After commit, the oldest entries are evicted
until both aggregate limits hold. Counts, character totals and eviction state
remain bounded; there is no hidden unlimited raw-copy or all-time-ID list.

The answer-context envelope is separate: source first, four preceding recent
turns, up to four relevant older turns, 2,000 characters per serialized turn
and 6,000 characters overall. All values are validated settings. Stored memory
can therefore be larger than any one provider request without causing unbounded
prompt growth.

## Deterministic context planner

`ContextPlanner` is a replaceable local strategy. It reserves context capacity
for the source, then walks immediately preceding retained turns for short
follow-ups. Older candidates are matched using bounded Unicode-normalized topic
terms. Exact term overlap determines relevance; overlap count and recency define
a deterministic rank, after which selected turns serialize chronologically.

Unicode format controls are removed during normalization. Topic terms are
lossy, untrusted retrieval metadata, not a full entity model or verified fact.
The planner can boundedly reconstruct missing derived terms for compatibility,
but the normal path reuses terms committed with each memory entry. No match
selects no older turn; it never fabricates the missing anchor.

`MemoryAnswerContextAssembler` converts a snapshot/plan into internal
`AnswerContext`. If memory is disabled or unavailable, one clean fallback invokes
the verified M4 `BoundedAnswerContextAssembler`. `AnswerProvider`, answer ID,
task ownership, cancellation, supersession and browser event schemas do not
change.

## Memory provenance and trust

M5 committed entries are `VERBATIM_CONVERSATION` with stable source-turn
provenance and `UNTRUSTED` trust. This means only that the statement occurred in
conversation. It does not establish that a personal, resume, project or document
claim is true.

`DERIVED_MEMORY` is reserved for a future lossy untrusted summary with source-
range provenance. `FUTURE_VERIFIED_CONTEXT` is a separate reserved source for M6
profile/document facts. These sources can later meet at the answer-context
boundary without changing `AnswerProvider` and without promoting conversation
claims into verified truth.

Generated answer state belongs to Answer History, not Conversation Memory. No
provider output is automatically re-observed as conversation, accepted as a
fact or recursively fed back as authoritative memory.

Remembered prompt-injection attempts remain inside serialized untrusted context.
They cannot change the separately supplied system instruction, disclose secrets,
enable tools or acquire verified provenance. Normal logs expose only content-
free latency, revision, count, selection and character metrics.

## Memory lifecycle and retention

- Browser disconnect detaches only the event sink. The same logical memory is
  retained during the existing 30-second resume lease.
- Browser resume reuses the logical session and its memory revision. Canonical
  replay does not re-commit memory and does not create another provider call.
- STT provider rotation and answer-provider failure have no memory ownership
  effect.
- Stop, reset, registry expiry, fatal teardown and shutdown logically clear or
  release memory with the session and join owned work.
- Backend restart intentionally loses memory. M5 creates no database, Redis,
  vector index, local-disk memory file or frontend persisted memory body.

Logical cleanup does not claim cryptographic wiping of process RAM.

## Evaluation and deferred summary boundary

The fixed 300-turn/120-minute synthetic evaluation exercised both turn and
character pressure, older-topic retrieval, prompt bounds and local timing. It
retained exactly 256 turns under turn pressure, stopped at exactly 160,000 text
characters under character pressure and selected 567 context characters for the
fixed topic-return case. The final recorded local medians were 0.0488 ms per
memory observation and 0.1408 ms per plan; these are environment measurements, not
cross-machine guarantees.

Deterministic memory was sufficient for M5, so no rolling summary or additional
paid model lifecycle was introduced. A future summarizer must be a separate
provider-neutral, asynchronous, task-bounded component with untrusted source-
range provenance, cancellation and stale-result protection. It must never block
STT or discard raw source before a successful commit.

## Future-compatible domain boundaries

### M5.5 advisory prediction side-car — complete

`backend/app/services/prediction/` defines an immutable provider-neutral
side-car domain and logical-session runtime. Stable prediction identity is
UUIDv5-derived from logical session plus active turn. Material fingerprints use
normalized active text, stable ordered utterance/turn provenance,
source/speaker, continuity and memory revision; exact changing canonical
sequences remain explicit request provenance. Fingerprints are internal
invalidation keys and never provenance truth.

`PredictionRequest`, bounded `PredictionContext`, `PredictionCandidate`,
`PredictionSnapshot`, `PredictionSessionSnapshot`, operational
`PredictionReadiness`, explicit invalidation/failure categories and the
one-shot `PredictionProvider` protocol are separate from M4 answer contracts.
Conversation-derived prediction context is forced to `UNTRUSTED`; trusted
policy and untrusted provider content use separate prompt fields. Idle has no
logical prediction snapshot. Invalidated and failed snapshots expose no
candidate/usage bodies.

M3's runtime now returns its immutable engine update. Only after canonical M3
processing, WebSocket orchestration makes a synchronous
`PredictionRuntime.observe_nowait(...)` submission with the active turn,
triggering canonical utterance and current memory revision. The runtime owns one
replaceable latest slot, one supervisor, at most one executor task, hard
turn/session ceilings, timeout, equality-gated stale rejection and exact
disconnect/Stop/reset/expiry/shutdown cleanup. Resume alone schedules no work.

An explicit conservative input-compatibility policy distinguishes bounded
completion of the same neutral lexical preface from a material change only
while an attempt is already `RUNNING` or `READY`. Every earlier token must
remain an exact prefix, except that the last unfinished token may be completed
and a fixed general-framing word may receive a long-stem inflection such as
`mention` to `mentioned`; case, comma, one terminal statement period and
intra-token hyphen rendering are treated as cosmetic. Newly added topic terms
must be drawn only from a fixed general-framing allowlist.
Compatible continuation retains the same logical `input_revision`, provider
attempt, basis fingerprint and bounded context; it never rewrites the provider
request after launch. Direct intent, deleted/reordered words,
correction/pivot/negation language, an internal or non-statement boundary, a new topic
term, more than 96 changed normalized characters, source/speaker/provenance
change, degraded continuity or memory revision change fails closed and uses
the existing invalidation path. A provider-final/awaiting-merge transition may
preserve an already-running or ready attempt only when that same compatibility
check succeeds; it cannot start a new attempt or bypass authoritative turn
finalization. Scheduled work still
coalesces against the latest exact input. Setting the character limit to zero
restores strict cancellation on every text change. Provider completion remains
equality-gated against the preserved basis, and the first material change
clears candidates before any newer attempt can run. A content-free per-turn
compatibility count supports diagnosis without logging active text or candidate
bodies.

Phase C adds a deterministic local trigger that suppresses short/backchannel,
weak ordinary and degraded-continuity input before context work. Eligible input
uses one latest coalescing slot, a minimum call interval and explicit per-turn /
per-session ceilings. Context planning occurs only in the independent worker:
active input receives budget first, then two recent turns and up to two
topic-relevant older turns under a 3,200-character operational ceiling. The
planner reads only an immutable `MemorySnapshot`; it carries untrusted
provenance and exact `memory_revision`/continuity/gap evidence.

A fresh snapshot revision mismatch, malformed context or unavailable planner
invalidates before an attempt is consumed. `PredictionProviderExecutor` then
builds one bounded request using trusted `LikelyNextTurnPolicy` plus untrusted
JSON conversation content. `FakePredictionProvider` owns deterministic tests;
`GeminiPredictionProvider` is a separate one-shot Interactions adapter using
structured output, `store=false`, no prior interaction, no tools, no Search and
no grounding. The installed constrained SDK supports the call shape without an
upgrade.

The production Gemini adapter is composed behind
`EventLoopIsolatedPredictionProvider`. One temporary worker thread owns one
asyncio loop and exactly one already-bounded provider call. This prevents
third-party SDK setup, serialization, transport or teardown work from starving
the realtime STT/browser event loop. Cancellation is forwarded to the inner
async task and the worker is joined before the provider call returns. The
wrapper adds no retry, queue, identity, context, candidate or cost authority;
the logical-session runtime still owns timeout, call ceilings, cancellation and
stale-result rejection. Fake providers remain unwrapped and deterministic.

When enabled, WebSocket orchestration constructs the provider/executor/runtime
inside the logical session and projects immutable snapshots as additive
`prediction.snapshot` events. The bounded outbound writer coalesces prediction
revisions by stable prediction ID behind important transcript/status/answer
events. Internal memory revision is not exposed to the browser; its change is a
generic `context_changed` invalidation.

The pure frontend reducer owns only current ephemeral prediction state. It
rejects stale, cross-session, provenance-inconsistent and malformed wire data.
The minimal `Likely next` UI explicitly distinguishes bounded guesses from
detected questions, verified facts and authoritative answers. It never touches
`answerOrder`, `answersById` or browser storage.

Disconnect cancels and clears prediction before retaining the logical session.
Resume replays canonical transcript/turn/Answer History but neither replays a
prediction nor causes a provider call. A new call requires genuine post-resume
canonical input and safe continuity. Stop/reset/expiry/shutdown clear state and
join owned work. Provider/STT failures and sink failures remain isolated.

The deterministic 11-case corpus measures trigger/context/lifecycle behavior,
stale rejection, calls, lead-time simulation, local overhead and cost proxy. It
does not claim general model accuracy. Phase H explicitly defers speculative
answer generation; no predicted candidate can be promoted to Answer History.
See `docs/MILESTONE_5_5_PHASE_D.md` through
`docs/MILESTONE_5_5_PHASE_I.md`.

The final target-Windows checkpoint verified the same boundaries with physical
microphone input. One real prediction returned three bounded candidates in
3,593 ms, survived seven deterministic compatible extensions and was ready
2,344 ms before turn finalization. A later topic correction cleared advisory
state. Refresh scheduled no provider work by itself, post-gap unsafe continuity
suppressed prediction, authoritative answers remained one-per-request, and Stop
released the microphone without an unhandled exception. These measurements
demonstrate one successful bounded live path; they are not a calibrated
accuracy or latency guarantee.

- M5.5 may read `MemorySnapshot` + `memory_revision` alongside M3
  `ConversationSnapshot.active_turn`; prediction cannot own/mutate memory.
- M5.6 may navigate the separate existing Answer History while transcript and
  new answers continue live; Conversation Memory is not a timeline store.
- M6 may inject separately verified profile/document facts through the context
  boundary. Conversation and derived memory remain untrusted.

Milestones 5 and 5.5 are **COMPLETE AND VERIFIED**. Speculative answers, full
topic/radar UI, timeline navigation, verified documents and durable account
history remain outside this implementation.

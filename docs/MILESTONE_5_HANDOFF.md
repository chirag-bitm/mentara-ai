# Milestone 5 handoff

MILESTONE:

5 — Provider-Neutral Session Memory + Context Orchestration

STATUS:

COMPLETE AND VERIFIED on 2026-09-13.

WHAT WE BUILT:

A provider-neutral in-RAM `ConversationMemory`, immutable provenance-bearing
snapshots with monotonic revision, deterministic local context planning, logical-
session lifecycle integration, one-boundary M4 rollback, content-free metrics,
synthetic long-session evaluation and complete M5 documentation/roadmap
reconciliation.

END-TO-END FLOW NOW WORKING:

Finalized M3 turns commit once to logical-session memory. A positive assistance
decision builds a stable M4 answer request. The M5 planner allocates bounded
context to the source, recent turns and matching older turns, then hands that
provider-neutral context through the existing policy/provider/runtime. Browser
events and frontend answer reduction remain unchanged.

VERIFIED WORKING:

Duplicate/replay/stale/cross-session protection; deterministic order/revision;
hard turn/character/context limits; explicit eviction/gaps; recent follow-ups;
older named-topic return; honest no-match; disconnect/resume; Stop/reset/expiry/
shutdown cleanup; provider isolation; prompt-injection containment; feature-off
fallback; immutable future-prediction snapshots; separate answer history; safe
content-free logs; and no browser persistence of memory text.

TESTS PERFORMED:

- Final backend suite: 261 passed with two known dependency deprecation warnings.
- Frontend: 21 reducer/policy tests passed.
- Frontend lint, strict TypeScript and Next.js production build passed.
- Offline 300-turn/120-minute synthetic evaluation passed all assertions.
- Target-Windows `verify.bat`, Chrome, physical microphone and real configured
  providers passed the short context/resume/Stop checkpoint.
- Final archive integrity, exclusions and common-secret scans passed.

FILES CREATED:

- `backend/constraints.txt`
- `backend/app/services/memory/__init__.py`
- `backend/app/services/memory/models.py`
- `backend/app/services/memory/terms.py`
- `backend/app/services/memory/memory.py`
- `backend/app/services/memory/planner.py`
- `backend/tests/test_conversation_memory.py`
- `backend/tests/test_memory_context_planner.py`
- `backend/tests/test_memory_privacy_boundaries.py`
- `backend/tests/test_memory_session_lifecycle.py`
- `docs/FEATURE_ROADMAP.md`
- `docs/MILESTONE_5_MEMORY_EVALUATION.json`
- `docs/MILESTONE_5_PHASE_0.md`
- `docs/MILESTONE_5_PHASE_A.md`
- `docs/MILESTONE_5_PHASE_B.md`
- `docs/MILESTONE_5_PHASE_C.md`
- `docs/MILESTONE_5_PHASE_D.md`
- `docs/MILESTONE_5_PHASE_E.md`
- `docs/MILESTONE_5_PHASE_F.md`
- `docs/MILESTONE_5_PHASE_G_CHECKLIST.md`
- `docs/MILESTONE_5_PHASE_G.md`
- `docs/MILESTONE_5_PHASE_H.md`
- `docs/MILESTONE_5_HANDOFF.md`
- `scripts/evaluate_memory_context.py`
- `scripts/m5-checkpoint.ps1`
- `m5-checkpoint.bat`

FILES MODIFIED:

- `PROJECT_STATE.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `backend/.env.example`
- `backend/app/api/websocket.py`
- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/app/services/answer/__init__.py`
- `backend/app/services/answer/context.py`
- `backend/app/services/answer/models.py`
- `backend/app/services/answer/policy.py`
- `backend/app/services/transcript/session.py`
- `backend/tests/test_answer_context_policy.py`
- `backend/tests/test_answer_websocket.py`
- `backend/tests/test_stt_config.py`
- `scripts/setup.ps1`

No frontend runtime source was modified.

DEPENDENCIES ADDED:

None. `backend/constraints.txt` fixes the already-used provider SDK to the M4-
verified `google-genai==2.23.0`; other direct requirements remain bounded ranges.

ENVIRONMENT VARIABLES ADDED/CHANGED:

Added `MEMORY_CONTEXT_ENABLED`, `MEMORY_MAX_RETAINED_TURNS`,
`MEMORY_MAX_RETAINED_TEXT_CHARS`, `MEMORY_MAX_TURN_CHARS`,
`MEMORY_CONTEXT_RECENT_TURNS` and `MEMORY_CONTEXT_RELEVANT_TURNS`. Defaults are
respectively true, 256, 160000, 4000, 4 and 4. Existing answer context caps still
bound serialized provider input.

FEATURE ROADMAP UPDATES:

The separate register was reconciled into `docs/FEATURE_ROADMAP.md` without
renumbering. F-036 through F-041 are COMPLETE. F-049 is FOUNDATION READY for
bounded retrieval terms only. F-042 summary remains DEFERRED. Prediction,
Conversation Radar, Timeline/Q&A navigation, verified profile/documents, Truth
Lock and all later product modes remain planned at their stated boundaries.

MEMORY DOMAIN CONTRACT:

Memory observes only immutable finalized turns. Stable identity—not text
equality—defines duplication. Each unique valid ordered commit changes revision
once. Duplicates/replay/stale observations do not; cross-session/invalid identity
is rejected. Snapshots, entries, gaps and provenance are frozen and tuple-backed.

MEMORY OWNERSHIP / LIFECYCLE:

The logical backend `TranscriptionSession` owns memory. A browser lease, STT
socket, provider interaction, answer provider/runtime and frontend never do.
Disconnect preserves it only during the existing resume lease. Stop/reset/
registry expiry/fatal teardown/shutdown clear or release it with the session.

MEMORY BOUNDS / EVICTION POLICY:

Defaults: 256 retained finalized turns, 160,000 retained text characters and
4,000 characters per entry. Oldest entries are deterministically evicted until
both aggregate limits hold. Entry truncation is a marked deterministic prefix.
Eviction/sequence loss leaves explicit degraded continuity and gap provenance.

MEMORY PROVENANCE / TRUST MODEL:

M5 commits `VERBATIM_CONVERSATION` as `UNTRUSTED` with source-turn provenance.
`DERIVED_MEMORY` is reserved as lossy/untrusted with source-range provenance.
`FUTURE_VERIFIED_CONTEXT` is distinct and reserved for M6. Remembered claims
record what was said; they are not verified facts.

CONTEXT SELECTION POLICY:

Source first; four immediately preceding recent turns; up to four matching older
turns. Older relevance is local Unicode-normalized exact term overlap, ranked by
overlap then recency and serialized chronologically. Caps are 2,000 characters
per context turn and 6,000 total. Strategy remains replaceable.

FOLLOW-UP RESOLUTION:

Recent context resolves bounded short references such as “Why?” and “How does
that work?”. Named terms can retrieve older retained turns after intervening
discussion. Missing or mistranscribed anchors produce an honest no-match rather
than invented context.

TOPIC / ENTITY FOUNDATION:

Bounded normalized content terms are stored as lossy, untrusted retrieval
metadata. Unicode format controls are removed. This is deliberately not a full
NER, topic-transition, open-thread or Conversation Radar subsystem.

DERIVED SUMMARY / COMPACTION DECISION:

Choice A: deterministic memory is sufficient for M5. The controlled long-session
evaluation met quality, bounds and local-latency objectives without another API
call. A future separate asynchronous provider-neutral summarizer hook is
documented, but no summarizer/task/provider call exists in M5.

ANSWER ENGINE INTEGRATION:

`MemoryAnswerContextAssembler` implements the existing internal assembly
boundary. `AnswerProvider`, `AnswerRuntime`, IDs, lifecycle, cancellation,
supersession, timeouts, state replay and browser answer events remain unchanged.
Generated answers are never committed to Conversation Memory automatically.

BROWSER DISCONNECT / RESUME:

Disconnect detaches the sink; the logical session keeps memory during the
30-second lease. Resume restores the same session/revision and replays canonical
state without re-observing turns or making a duplicate paid request.

BACKEND RESTART SEMANTICS:

Restart intentionally loses transcript/session memory and answer state. M5 adds
no persistence and makes no durable-retention claim.

M5.5 PREDICTION HOOK:

Future prediction can read immutable `MemorySnapshot` + `memory_revision` with
M3 `ConversationSnapshot.active_turn`. Revision allows cheap cache invalidation.
Prediction must not own or modify memory. No predictive execution is implemented.

M5.6 Q&A NAVIGATOR HOOK:

Answer History remains a separate multi-answer domain with stable replay. A
future UI can browse previous/next Q&A and return live while transcript/new
answers continue; it need not rewrite Conversation Memory.

M6 TRUTH-LOCK / DOCUMENT HOOK:

Future verified profile/document facts can enter context through the reserved
distinct provenance source without changing `AnswerProvider`. Conversation and
derived memory cannot silently become verified truth.

LATENCY FINDINGS:

In the fixed local evaluation, median observation was 0.0488 ms, p95 0.0813 ms;
median planning was 0.1408 ms, p95 0.2421 ms. These are controlled environment
measurements, not cross-machine guarantees. Real model first-text latency remains
provider/network dominated.

COST FINDINGS:

Core M5 adds no mandatory API/model call. The fixed topic-return request selected
567 context characters, 2.01% of retained memory. The recorded character/4
figures are rough input-growth proxies, not billed provider token measurements.

PRIVACY / RETENTION / DELETION:

Memory is backend RAM only and is never written to a new database, local disk or
browser persistent storage. Normal logs contain no transcript/memory/answer
bodies. Stop/reset/expiry/shutdown provide logical deletion/session cleanup; no
cryptographic RAM-wipe claim is made.

PROMPT-INJECTION / MEMORY-POISONING NOTES:

Stored conversation and any future derived memory remain serialized untrusted
content, separate from system policy. They cannot disclose policy/secrets,
enable tools or become verified facts. Adversarial stored-instruction tests pass.

BACKWARD-COMPATIBILITY:

M1–M4 provider-neutral boundaries, event shapes, stable IDs, replay, answer
history, cancellation/supersession/timeout/failure and frontend reducers remain
compatible. M5 adds no browser memory event.

ROLLBACK:

`MEMORY_CONTEXT_ENABLED=false` restores M4 bounded context. Existing
`ANSWER_GENERATION_ENABLED=false` and `CONVERSATION_ANALYSIS_ENABLED=false`
restore M1–M3 and M2 respectively. No migration rollback is needed.

KNOWN LIMITATIONS / TECH DEBT:

STT accuracy is upstream/provider dependent. Relevance is deterministic lexical
matching, not semantic embeddings. Canonical transcript/finalized-turn replay
and Answer History collections retain current-session state independently of
bounded Conversation Memory. Full dependency locking and durable multi-worker
state remain later work.

KNOWN BUGS:

None verified at closeout. Two non-failing dependency deprecation warnings are
tracked. An absent/mistranscribed topic correctly produces no relevant match.

DEFERRED ENGINEERING REGISTER UPDATES:

M4 richer memory is partially resolved by bounded current-session memory. Added
M5-DEFER-01 derived summary, M5-DEFER-02 full topic/entity model,
M5-DEFER-03 independent authoritative-history bounds and M5-DEFER-04 full
cross-platform dependency lock. Carried M3 detector-language, durable session,
progressive answer, regeneration, timeline, production scale and provider-
latency items forward.

WHAT SHOULD NOT BE CHANGED WITHOUT REASON:

Backend ownership of authoritative domains; immutable finalized-turn input;
stable identity/revision/provenance; explicit trust separation; bounded storage
and context; separate Conversation Memory/Answer History; provider-neutral
planner/assembler/provider contracts; logical-session task ownership; replay and
terminal-answer semantics; and layered rollback flags.

RECOMMENDED NEXT MILESTONE:

M5.5 — Predictive Next-Turn, in a new milestone workflow after MASTER review.

NEXT MILESTONE PREREQUISITES:

Use this final ZIP as the sole baseline; re-run its full gate; inspect the M5
snapshot/revision and M3 active-turn contracts; define prediction identity,
confidence, invalidation, cancellation, privacy/cost ceilings and feature
rollback before implementation; keep predictions non-authoritative.

FINAL SANITIZED ZIP:

`mentara-milestone-5-complete.zip`, created outside the repository only after the
final gate and documentation reconciliation, then checked for integrity,
excluded artifacts and common secret patterns.

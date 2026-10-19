# Mentara AI — Milestone 4 handoff

MILESTONE:

4 — Provider-Neutral Answer Engine + Low-Latency Streaming

STATUS:

COMPLETE AND VERIFIED on 2026-09-13. M5 was not started.

WHAT WE BUILT:

A provider-neutral answer domain and explicit lifecycle; deterministic answer
identity derived from stable M3 provenance; bounded context and policy
boundaries; a deterministic fake provider; an independent logical-session-owned
answer runtime; latest-request-wins cancellation; one bounded serialized
WebSocket writer; additive answer events; a pure idempotent frontend reducer and
minimal streaming UI; and an async stateless Gemini Interactions adapter.

END-TO-END FLOW NOW WORKING:

```text
Meaningful speech
  -> canonical transcript
  -> stable finalized turn
  -> positive assistance decision
  -> stable AnswerRequest
  -> bounded AnswerContext + AnswerPolicy
  -> AnswerProvider async stream
  -> backend AnswerLifecycle
  -> bounded/coalesced answer events
  -> incremental idempotent answer UI
```

VERIFIED WORKING:

- One positive detection creates one stable answer request and at most one
  initial provider call.
- Statements, partials, finals alone, replay and duplicate detections do not call
  the answer provider.
- The M3 callback returns after a local task handoff and never awaits generation.
- Streaming text reaches the browser incrementally without concurrent WebSocket
  sends or an unbounded queue.
- Latest meaningful request deterministically supersedes active older work.
- Stop/reset/fatal teardown/expiry cancel provider work; browser resume does not
  regenerate; answer failure does not kill STT.
- Context and prompt construction are bounded, deterministic and separated into
  trusted policy and untrusted conversation content.
- Feature-disabled M4 preserves M1–M3 including `question.detected`.

TESTS PERFORMED:

- Full backend gate: 216 passed; two known third-party deprecation warnings.
- Full frontend gate: 21 passed.
- Frontend ESLint, TypeScript and production build passed.
- 53 focused tests in the answer/fake/Gemini/outbound modules, plus expanded
  WebSocket, registry, resilience, rotation, configuration and detector tests.
- Windows-only scheduler issue was reproduced, corrected and the exact STT
  rotation test passed a 100-run stress check.
- Minimal real stateless provider diagnostic succeeded with completed/text
  events and no printed API key.
- Eight-call non-sensitive, stateless real-model benchmark completed 8/8.
- Short physical microphone/browser checkpoint passed statement/no-answer,
  question/request streaming, concurrent STT responsiveness, supersession,
  refresh/no-duplicate, Stop/cancellation and no-unhandled-error checks.

FILES CREATED:

- `backend/app/api/outbound.py`
- `backend/app/services/answer/` (domain, identity, lifecycle, context, policy,
  provider protocol, fake provider, runtime, factory and Gemini adapter)
- `backend/tests/test_answer_context_policy.py`
- `backend/tests/test_answer_domain.py`
- `backend/tests/test_answer_events.py`
- `backend/tests/test_answer_lifecycle.py`
- `backend/tests/test_answer_runtime.py`
- `backend/tests/test_answer_websocket.py`
- `backend/tests/test_fake_answer_provider.py`
- `backend/tests/test_gemini_answer_adapter.py`
- `backend/tests/test_outbound_events.py`
- `frontend/src/lib/answer-reducer.ts`
- `frontend/tests/answer-reducer.test.ts`
- `benchmark-answers.bat`
- `scripts/benchmark-answers.ps1`
- `scripts/benchmark_answers.py`
- `scripts/diagnose_answer_provider.py`
- `scripts/diagnose_answer_provider_minimal.py`
- `docs/MILESTONE_4_PHASE_0.md` through `docs/MILESTONE_4_PHASE_H.md`
- `docs/MILESTONE_4_MODEL_BENCHMARK.json`
- `docs/MILESTONE_4_HANDOFF.md`

FILES MODIFIED:

- `.gitignore`, `PROJECT_STATE.md`, `README.md`
- `backend/.env.example`, `backend/requirements.txt`
- `backend/app/api/websocket.py`, `backend/app/core/config.py`,
  `backend/app/main.py`, `backend/app/schemas/events.py`
- `backend/app/services/conversation/detector.py`
- `backend/app/services/transcript/registry.py` and `session.py`
- Existing browser/reconnect/conversation/resilience/STT/config/registry tests
  needed for M4 integration and deterministic Windows timing coverage
- `frontend/package.json`, reducer-test build configuration and test runner
- `frontend/src/types/transcription.ts`, streaming hook, transcription console and
  minimal answer styling
- `scripts/configure-gemini.ps1`, `scripts/setup.ps1`, `scripts/verify.ps1`
- `docs/ARCHITECTURE.md`

DEPENDENCIES ADDED:

- `google-genai>=2.3,<3.0` for the official async Interactions client.
- `anyio>=4.10,<5.0` for shielded ASGI/WebSocket teardown.

ENVIRONMENT VARIABLES ADDED/CHANGED:

- `ANSWER_GENERATION_ENABLED=true`
- `ANSWER_PROVIDER=gemini`
- `GEMINI_ANSWER_MODEL=gemini-3.5-flash-lite`
- `GEMINI_ANSWER_THINKING_LEVEL=minimal`
- `ANSWER_MAX_OUTPUT_TOKENS=512`
- `ANSWER_GENERATION_TIMEOUT_SECONDS=20`
- `ANSWER_CONTEXT_RECENT_TURNS=2`
- `ANSWER_CONTEXT_MAX_TOTAL_CHARS=6000`
- `ANSWER_CONTEXT_MAX_TURN_CHARS=2000`
- `ANSWER_OUTBOUND_BUFFER_ITEMS=128`
- `ANSWER_DELTA_MAX_COALESCED_CHARS=4096`

The existing backend-only `GEMINI_API_KEY` is reused. No frontend secret was
added.

ANSWER PROVIDER / MODEL DECISION:

`AnswerProvider` is the application boundary. The production default is
`gemini-3.5-flash-lite` with `minimal` thinking because it delivered sufficient
quality with lower latency, verbosity and estimated cost than
`gemini-3.8-flash`/`low` on the fixed M4 corpus. The selection is configurable.

PROVIDER API / STORAGE DECISION:

Use the official `google-genai` async Gemini Interactions API with
`stream=true`, `store=false`, no `previous_interaction_id`, no tools/search/
grounding and no provider-owned Mentara memory. SDK/application automatic
retries are disabled for M4.

ANSWER DOMAIN CONTRACT:

`AnswerRequest` is built only from an authoritative positive
`AssistanceDecision` and matching `ConversationTurn`. Its deterministic answer
ID, session/detection/turn provenance, source turn order, assistance kind,
attempt and monotonic timing are validated. `AnswerContext`, `AnswerPrompt`,
provider events, usage, sanitized failure and `AnswerSnapshot` remain
provider-neutral.

ANSWER LIFECYCLE:

`requested -> starting -> streaming -> completed`, with `cancelled`,
`superseded` and `failed` terminal alternatives. Revisions and stream sequences
are monotonic. Empty completion is valid; malformed/discontinuous streams fail
honestly. Terminal state is immutable and cannot accept later deltas.

SUPERSESSION / CANCELLATION SEMANTICS:

Only one answer generation may be active per logical session. Latest meaningful
request wins. An active prior answer becomes `superseded`, its task is cancelled
and provider stream/client closure is awaited. Stop produces `cancelled` rather
than `completed`. Completed answers never change.

OUTBOUND EVENT / BACKPRESSURE DESIGN:

One `OutboundEventWriter` owns every `/ws/transcribe` send. It has a fixed
per-browser capacity, prioritizes critical state over answer deltas, retains at
most one pending delta per answer, coalesces contiguous small chunks and flushes
pending text before terminal lifecycle events. Overflow ends the slow browser
lease instead of growing memory; session state can still resume.

BROWSER DISCONNECT / RESUME SEMANTICS:

The answer runtime belongs to the logical 30-second resumable session. A browser
disconnect detaches only its sink; active generation may continue. Resume
replays authoritative snapshots with original IDs and makes no provider call.
Expiry cancels/joins work. Audio during the browser gap remains unbuffered and
continuity is marked degraded honestly.

CONTEXT ASSEMBLY POLICY:

The source turn plus at most two recent finalized turns by default, capped at
2,000 characters per turn and 6,000 total. Ordering and provenance are
deterministic. The provider never owns or retrieves Mentara memory.

TRUTH / PROMPT-INJECTION POLICY:

Application instructions and serialized untrusted transcript content are
separate fields. The policy refuses disclosure of system instructions,
environment values, credentials and resume tokens; M4 has no tools/actions.
Missing personal facts must not be fabricated or called verified. Output must be
generic or acknowledge unavailable verified context. Default output is concise,
speakable, scan-friendly plain text.

LATENCY FINDINGS:

Local transcript-final-to-turn remained approximately 250–266 ms and turn-to-
detection 0 ms. Benchmark median first/total text was 1,723/2,693 ms for
Flash-Lite and 3,399/5,533.5 ms for 3.8 Flash. Manual first text varied from
2,454–7,406 ms, demonstrating provider/network variability. The microphone/STT
pipeline remained responsive during generation.

COST FINDINGS:

Across four prompts per model, estimated paid Standard cost was $0.0009309 for
Flash-Lite (878 input, 267 output tokens) and $0.00267225 for 3.8 Flash (878
input, 537 output tokens). These are estimates, not a bill; free-tier behavior
and terms differ.

SECURITY / PRIVACY NOTES:

Secrets remain backend-only. `configure-gemini` validates hidden input and never
prints the key. Provider storage is explicitly disabled. No raw audio is
persisted. Normal logs contain no transcript/question/answer content. Benchmark
content is non-sensitive, and final packaging excludes `.env`, environments,
dependencies, logs, caches and build output.

BACKWARD-COMPATIBILITY NOTES:

All answer processing is additive and downstream. Existing PCM/audio,
`/ws/transcribe`, `/ws/health`, transcript, turn, detection, provider rotation,
browser-resume and canonical identity semantics remain intact. Existing clients
may ignore answer events.

ROLLBACK NOTES:

Runtime rollback: set `ANSWER_GENERATION_ENABLED=false` and restart the backend.
M1–M3 continue, including `question.detected`, with no answer-provider call.
`CONVERSATION_ANALYSIS_ENABLED=false` remains the M2 rollback. Source rollback
can remove the M4 answer package/writer/events/UI integration while restoring the
M3 WebSocket/session files; do not rewrite verified M1–M3 contracts.

KNOWN LIMITATIONS / TECH DEBT:

- In-memory logical state does not survive backend restart or coordinate across
  multiple workers.
- Context is a tiny recent-turn window, not durable memory.
- No automatic retry, explicit regeneration UX or progressive two-pass answer.
- Minimal UI shows only latest plain-text answer, not rich history/Markdown.
- Provider/network latency varies.
- The deterministic request detector is intentionally bounded; broad implicit,
  ambiguous and multilingual intent remains future work.
- STT accuracy remains dependent on provider/audio conditions.

KNOWN BUGS:

No open M4 correctness bug was observed at closeout. The two backend warnings
are dependency deprecations. A resumed browser gap may honestly show degraded
continuity, and STT can misrecognize wording; both are documented limitations.

DEFERRED ENGINEERING REGISTER UPDATES:

Added durable session/task ownership, richer memory, progressive answers,
explicit regeneration/retry UX, rich answer rendering, multi-worker
coordination and provider-latency optimization. M3's request-language limitation
was partially remediated with a bounded explicit-verb audit; broad language
understanding remains deferred. See `PROJECT_STATE.md`.

WHAT SHOULD NOT BE CHANGED WITHOUT REASON:

Backend authority; provider-neutral boundaries; deterministic IDs/provenance;
answer terminal immutability; one-generation latest-wins policy; logical-session
task ownership; bounded sole-writer behavior; stateless `store=false` provider
use; backend-only credentials; content-free normal logs; M3 event/audio/resume
contracts; and the two clean rollback flags.

FUTURE EXTENSION HOOKS:

- M5 Memory + Context: extend `AnswerContextAssembler`.
- M5.5 Predictive Next-Turn: consume active-turn snapshots and use a separate
  bounded preload policy without changing logical answer identity.
- M6 Profile/Documents/Truth Lock: inject verified, provenance-bearing facts
  through context/policy.
- M7 Desktop Overlay: render the same backend-owned answer events.
- M8 System Audio: extend canonical audio-source/speaker provenance upstream.
- M9 Screen Intelligence: add bounded, explicitly trusted context inputs.
- M10 Coding Engine: implement a specialized policy/provider mode without
  rewriting `AnswerRuntime`.

RECOMMENDED NEXT MILESTONE:

Milestone 5 — Memory + Context.

NEXT MILESTONE PREREQUISITES:

Begin in a new chat from the final M4 archive and this handoff. Reinspect the
repository, preserve all stable M1–M4 contracts, define memory ownership/
retention/privacy before persistence, and extend the context boundary rather
than provider state.

FINAL SANITIZED ZIP:

`mentara-milestone-4-complete.zip`, created outside the source repository after
the final gate. The SHA-256 is reported alongside delivery because an archive
cannot embed its own final digest without changing that digest. The archive must
contain no `.env`, secret, virtual environment, dependency tree, cache, log or
build-output entry; the final delivery records the completed inspection.

Return to 00 — MASTER and paste this MASTER CHAT HANDOFF before starting another milestone.

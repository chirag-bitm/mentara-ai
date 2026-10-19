# Milestone 3 completion handoff

MILESTONE:
3 — Conversation Turn + Meaningful Question / Assistance Detection

STATUS:
Complete. Automated verification and the target-Windows physical-microphone,
browser-resume and clean-Stop checkpoint passed on 2026-09-12.

WHAT WE BUILT:

- Provider-neutral conversation domain contracts with immutable finalized turns,
  active-turn visibility, canonical provenance, independent turn ordering,
  application-observed timing and continuity quality.
- A deterministic `ConversationTurnEngine` with one configurable/cancellable
  merge deadline.
- A replaceable `AssistanceDetector` and initial local deterministic
  English/Hinglish heuristic.
- Additive `turn.finalized` and positive-only `question.detected` browser events.
- Derived snapshot/replay across browser resume and provider replacement.
- An idempotent frontend conversation reducer and minimal diagnostic UI.
- Safe latency instrumentation without transcript text in logs.
- A clean feature-disable boundary restoring the M2 transcription-only path.
- A safe, repeatable STT accuracy-profile helper and separate findings document.

END-TO-END FLOW NOW WORKING:

`Microphone → PCM16 → /ws/transcribe → STTProvider → TranscriptResult → TranscriptAggregator → CanonicalUtterance → transcript event → ConversationTurnEngine → turn.finalized → AssistanceDetector → question.detected → frontend conversation reducer → diagnostic UI`

The canonical transcript event is emitted before its downstream M3 events. M3
never consumes Gemini-specific payloads or mutates canonical transcript history.

VERIFIED WORKING:

- One logical completed prompt produces one stable finalized turn.
- Partial revisions retain one active turn; duplicate/stale canonical events are
  ignored.
- Nearby same-source final segments can merge with complete provenance.
- Direct questions, auxiliary forms, request-style prompts, imperatives,
  follow-ups and focused common Hinglish cues are detected in the curated corpus.
- Tested statements and backchannels are suppressed.
- Stable turn/detection IDs and monotonic turn order survive replay.
- Browser refresh replays transcript, finalized turns and positive detections
  idempotently.
- Provider replacement and duplicate finals do not duplicate derived events.
- Degraded continuity remains attached to affected turns instead of being hidden.
- Stop, failure, disconnect, resume, reset and expiry clean up timer/task state.
- M3 adds no required paid classifier or LLM call.
- Existing M1/M2 audio, transcript, provider and resilience contracts remain
  compatible.

TESTS PERFORMED:

- Local coding-environment gate: 127 backend tests passed; 14 frontend tests
  passed; frontend lint, TypeScript and production build passed.
- Target-Windows `verify.bat`: the same 127 backend tests, 14 frontend tests,
  lint, TypeScript and production build passed.
- Fake-provider integration coverage includes direct/imperative/request/follow-up
  prompts, multi-sentence input, negatives, partial corrections, final without
  partial, repeated/duplicate final policy, nearby final merging, distinct turns,
  source/speaker propagation, degraded state, replay/resume, provider rotation,
  Stop, disconnect/pause/resume, fatal provider failure, expiry/reset, malformed
  events, stable IDs/order and timer cleanup.
- Target-Windows physical test: statement became Turn 1 without assistance;
  question became Turn 2 with assistance; request became Turn 3 with assistance;
  refresh restored Turn 3 without replay increment; a new request became Turn 4;
  Stop released the microphone without an unhandled backend error.
- Observed physical latency: 250–266 ms transcript-final-to-turn and 0 ms local
  turn-to-detection.

FILES CREATED:

- `backend/app/services/conversation/__init__.py`
- `backend/app/services/conversation/models.py`
- `backend/app/services/conversation/identity.py`
- `backend/app/services/conversation/engine.py`
- `backend/app/services/conversation/runtime.py`
- `backend/app/services/conversation/detector.py`
- `backend/tests/test_conversation_models.py`
- `backend/tests/test_conversation_turn_engine.py`
- `backend/tests/test_assistance_detector.py`
- `backend/tests/test_conversation_events.py`
- `backend/tests/test_conversation_websocket.py`
- `backend/tests/test_stt_accuracy_profile.py`
- `frontend/src/lib/conversation-reducer.ts`
- `frontend/tests/conversation-reducer.test.ts`
- `scripts/stt_accuracy_profile.py`
- `scripts/stt-accuracy.ps1`
- `stt-accuracy.bat`
- `docs/MILESTONE_3_PHASE_0.md`
- `docs/MILESTONE_3_STT_ACCURACY.md`
- `docs/MILESTONE_3_PHASE_A.md`
- `docs/MILESTONE_3_PHASE_B.md`
- `docs/MILESTONE_3_PHASE_C.md`
- `docs/MILESTONE_3_PHASE_D.md`
- `docs/MILESTONE_3_PHASE_E.md`
- `docs/MILESTONE_3_HANDOFF.md`

FILES MODIFIED:

- `.gitignore`
- `README.md`
- `PROJECT_STATE.md`
- `docs/ARCHITECTURE.md`
- `backend/.env.example`
- `backend/app/core/config.py`
- `backend/app/api/websocket.py`
- `backend/app/schemas/events.py`
- `backend/app/services/transcript/aggregator.py`
- `backend/app/services/transcript/session.py`
- `backend/tests/test_browser_reconnection.py`
- `backend/tests/test_resilience_integration.py`
- `backend/tests/test_transcript_websocket.py`
- `backend/tests/test_transcription_registry.py`
- `backend/tests/test_transcription_session.py`
- `frontend/src/types/transcription.ts`
- `frontend/src/hooks/use-streaming-transcription.ts`
- `frontend/src/components/transcription-console.tsx`
- `frontend/src/app/globals.css`
- `frontend/scripts/test-transcript-reducer.mjs`
- `frontend/tsconfig.reducer-tests.json`

DEPENDENCIES ADDED:

None.

ENVIRONMENT VARIABLES ADDED/CHANGED:

- Added `CONVERSATION_ANALYSIS_ENABLED=true`. Set it to `false` for the M2-only
  runtime path.
- Added `CONVERSATION_TURN_MERGE_WINDOW_MS=250`, validated from 0 through 2,000.
- Existing local `.env` files require no edit because both have safe defaults.
- The controlled STT gate retained the user's original effective profile and
  `GEMINI_TRANSCRIPTION_MODE=VERBATIM`; no permanent provider-default change was
  justified.

STT ACCURACY FINDINGS:

Profiles A (automatic/VERBATIM), B (`en-IN,hi-IN`/VERBATIM) and the user's
original profile C were compared with the same four English, Indian-English,
Hinglish and technical phrases repeated twice. A rendered Hinglish in
Devanagari and captured background speech; B kept Hinglish in Latin script but
repeatedly substituted `cache` with `cash`; C preserved all intended content
words with only harmless technical compound spacing/capitalization. This small
product check is not a rigorous WER/CER study. It justified retaining C and
VERBATIM, not adding vocabulary, and not changing VAD in M3.

IMPORTANT ARCHITECTURE DECISIONS:

- Canonical transcript state remains the backend-owned source of truth.
- M3 is strictly downstream of `CanonicalUtterance` and provider-neutral.
- Turn sequence is independent from transcript sequence; aligned canonical IDs
  and final sequences provide provenance.
- UUIDv5-derived turn and detection identity is stable without persistence.
- Application-observed monotonic timing is reported honestly; no exact speech or
  word timestamps are fabricated.
- Active-turn state is exposed read-only for future prediction.
- Finalized turns are immutable and positive decisions are retained for replay.
- The route owns at most one deadline task per attached browser lease and joins
  all peer tasks on every exit path.
- Detailed topic classification and answer generation remain outside M3.

TURN DETECTION SEMANTICS:

- Default final merge window: 250 ms after the latest canonical final.
- Same-source/speaker canonical contributions within the window remain one turn.
- A clear source/speaker change immediately finalizes an all-final previous turn.
- Stop and provider failure flush all-final pending state immediately.
- Partial-only terminal state is cancelled; it is never fabricated as final.
- Disconnect pauses the deadline without discarding resumable active state;
  resume rearms the same identity and finalizes it at most once.
- Continuity degradation is sticky for the affected turn.

QUESTION/ASSISTANCE DETECTION SEMANTICS:

- The initial detector is local, deterministic and replaceable.
- It uses interrogatives, auxiliary forms, request verbs, interview-style
  imperatives, follow-ups, punctuation as one signal and a focused Hinglish set.
- Explicit backchannels, short non-actionable fragments and ordinary statements
  are suppressed in the tested corpus.
- Results are `question`, `request` or internal `none`; no artificial probability
  is exposed.
- Each immutable turn is processed at most once. Only positive results emit
  `question.detected`, which refers to its stable source turn.
- The curated corpus does not prove general natural-language accuracy.

LATENCY FINDINGS:

- The configured default intentionally contributes approximately 250 ms after a
  canonical final to join provider-split segments.
- The Windows checkpoint observed 250–266 ms transcript-final-to-turn latency.
- The local detector observed 0 ms turn-to-detection latency.
- Hybrid/client-assisted VAD was not added because it would change the verified
  M1/M2 audio/provider lifecycle without a separate measured benefit.

KNOWN LIMITATIONS / TECH DEBT:

- `M3-DEFER-01`: heuristic detection can miss implicit, novel or
  unsupported-language requests
  and can produce false positives outside the curated corpus.
- `M3-DEFER-02`: the 250 ms policy can join unusually close distinct finals or
  fail to merge widely separated pieces; it is configurable for future measured
  tuning.
- `M2-DEFER-03`: the existing M2 bounded exact-text dedupe may conflate an
  intentionally repeated identical phrase inside 1,000 ms.
- `M3-DEFER-04`: detached sessions and derived state remain in-memory with a
  30-second resume window and are lost on backend restart.
- `M1/M3-DEFER-05`: Gemini Live supplies no exact word timestamps or speaker
  diarization.
- No answers, prediction execution, topic router, long-term memory, documents,
  system audio or screen intelligence exist yet.

The authoritative owner and trigger for each deferred item are recorded in
`PROJECT_STATE.md`. They are not confirmed M3 correctness bugs.

KNOWN BUGS:

None confirmed through the deterministic suite and final Windows checkpoint.
The one observed 403 was the intended origin policy rejecting a temporary
`localhost:3001` frontend while an older frontend occupied port 3000; launching
the M3 frontend on configured port 3000 resolved it.

COST IMPACT:

No mandatory M3 API/model call and no new dependency. Automated M3 tests use
fake providers and consume no Gemini quota. Only the controlled accuracy check
and final microphone smoke test used the existing STT provider.

SECURITY / PRIVACY NOTES:

- Gemini credentials remain backend-only and are excluded from project ZIPs.
- No raw audio is persisted.
- Normal M3 logs contain turn sequence, latency and boolean decision only; they
  contain no transcript text or resume token.
- Resume tokens remain opaque, tab-scoped capabilities and do not provide user
  authentication.
- Derived state remains in memory and is not sent to any additional third party.

BACKWARD-COMPATIBILITY NOTES:

- Signed little-endian PCM16, 16 kHz mono, approximately 100 ms chunks, binary
  browser frames, `/ws/transcribe`, `/ws/health`, provider factory and existing
  transcript/status/error/session events retain their meaning.
- M3 events are additive; an M2 client can safely ignore unknown event types.
- Canonical utterance IDs, revisions, ordering, duplicate policy and replay remain
  authoritative and unchanged in meaning.
- M2 regression route tests explicitly exercise the feature-disabled path.

ROLLBACK NOTES:

- Preferred runtime rollback: set `CONVERSATION_ANALYSIS_ENABLED=false` in
  `backend/.env` and restart the backend. Transcription continues through the
  verified M2 path.
- A source rollback should restore the verified M2 checkpoint into a clean
  directory and separately retain the private `backend/.env`.
- Do not extract the M2 ZIP over the M3 tree as a complete rollback; it would
  leave M3-only files behind.

WHAT SHOULD NOT BE CHANGED WITHOUT REASON:

- Backend ownership of canonical transcript truth.
- The separation of logical session, browser socket and provider connection.
- PCM16/16 kHz/mono/approximately-100-ms binary audio contracts.
- Stable canonical and derived IDs/order/provenance.
- Provider-neutral `STTProvider`, `ConversationTurnEngine` and
  `AssistanceDetector` boundaries.
- Bounded rotation/retry/resume/timer behavior and honest degraded continuity.
- Transcript-free normal diagnostic logs and backend-only credentials.
- The retained STT profile, VERBATIM mode and 250 ms turn policy without new
  controlled evidence.

FUTURE EXTENSION HOOKS:

- M4 Answer Engine: consume positive `question.detected` plus its source turn;
  keep answer generation downstream and independently cancellable.
- M5 Memory: consume immutable finalized turns and stable provenance.
- M5.5 Predictive Next-Turn: read `ConversationSnapshot.active_turn` without
  mutating transcript/turn state.
- M6 Documents/Profile: provide authorized context downstream of routing; do not
  place document vocabulary directly in the WebSocket route.
- M8 System Audio: use existing `audio_source=system` and
  `speaker_role=remote_speaker` contracts with an authorized capture boundary.
- M9 Screen Intelligence: add authorized screen context as a separate source;
  do not overload transcript events.

RECOMMENDED NEXT MILESTONE:

Milestone 4 — Answer Engine + Streaming, only in a new dedicated milestone chat
after master roadmap review and a fresh preflight. It is **NOT STARTED**. Do not
begin it from this handoff.

NEXT MILESTONE PREREQUISITES:

- Bring this complete repository and handoff to 00 — MASTER.
- Reconcile M4 scope with the latest roadmap and current repository.
- Freeze the `question.detected`/source-turn consumption contract before adding
  generation.
- Analyze answer-provider limits, credentials, latency, streaming cancellation,
  cost/privacy, prompt-injection boundaries, replay/idempotence and rollback.
- Preserve the feature-disabled M2 path and keep M4 downstream of M3.
- Decide explicit answer acceptance metrics and fake-provider tests before real
  model usage.

Return to 00 — MASTER and paste this MASTER CHAT HANDOFF before starting another milestone.

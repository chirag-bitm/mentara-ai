# Milestone 5.5 handoff

## MILESTONE

5.5 — Predictive Next-Turn + Safe Speculative Context Preparation

## STATUS

COMPLETE AND VERIFIED — 2026-10-18

## WHAT WE BUILT

A provider-neutral, RAM-only advisory prediction side-car that observes the
authoritative evolving M3 active turn and immutable M5 memory snapshot. It
produces a small bounded set of likely next questions/topics, prepares bounded
untrusted context, rejects stale work, and exposes a minimal replay-safe
`Likely next` UI. It never becomes transcript, memory, verified fact, policy or
answer truth.

## END-TO-END FLOW NOW WORKING

Canonical utterance -> M3 active-turn update -> non-blocking prediction
observation -> local trigger/coalescing -> bounded context planner -> isolated
provider call -> equality-gated immutable prediction snapshot -> additive
browser event -> idempotent advisory UI. Finalized M3 turns, M5 memory and M4
answers retain their existing authoritative paths.

## VERIFIED WORKING

- Stable per-active-turn prediction identity and monotonic input revisions and
  attempts.
- Latest-input-wins cancellation, timeout, stale completion rejection and hard
  per-turn/session ceilings.
- Bounded active/recent/relevant-older context over read-only memory snapshots.
- Provider-final compatible continuation without accepting material changes.
- Correction, topic, provenance, continuity, memory, lifecycle and finalization
  invalidation.
- Disconnect/reconnect, Stop/reset/expiry/shutdown cleanup and no replay-paid
  call.
- Separate fake and stateless Gemini prediction providers.
- Event-loop isolation for the real SDK so prediction cannot starve STT.
- Minimal bounded `Likely next` UI that never mutates Answer History.
- Exact rollback through `PREDICTION_ENABLED=false`.

## TESTS PERFORMED

- Final backend suite: **445 passed**.
- Frontend reducer suite: **28 passed**.
- Frontend lint, strict TypeScript and production build: passed.
- M5 300-turn / 120-minute deterministic memory evaluation: passed.
- M5.5 11-case deterministic fake-provider evaluation: all checks passed.
- Speculative-answer decision evaluation: all safety checks passed; production
  generation deferred.
- Controlled real-provider benchmark: 4/4 bounded requests completed; one
  ordinary statement suppressed.
- Target-Windows Chrome/physical-microphone checkpoint: passed, including live
  prediction, correction, general answer, refresh/no duplicate, subsequent
  answer and Stop/microphone release.
- Final archive integrity, exclusion and secret scans: recorded below after
  packaging.

## FILES CREATED

- `backend/app/services/prediction/` domain, compatibility, context, executor,
  provider adapters, runtime and trigger modules.
- Prediction-specific backend tests, including provider isolation, races,
  lifecycle, context, browser events, evaluation and probe tests.
- `frontend/src/lib/prediction-reducer.ts` and its reducer test.
- M5.5 Phase 0/A–I, Windows, live-timing, evaluation and handoff documents.
- Prediction benchmark/evaluation/probe scripts and Windows helpers.

## FILES MODIFIED

- `PROJECT_STATE.md`, `README.md`, `docs/ARCHITECTURE.md`,
  `docs/FEATURE_ROADMAP.md`, `.env.example` and verification scripts.
- Backend configuration, schemas, outbound/WebSocket orchestration, logical
  session registry/session, M3 runtime return boundary and M4 answer policy.
- Frontend event types, streaming hook, console UI, CSS, reducer test harness
  and TypeScript reducer-test configuration.
- Existing integration/config/outbound/conversation/answer regression tests.

## DEPENDENCIES ADDED

None. `google-genai==2.23.0` remains constrained; no upgrade was required.

## ENVIRONMENT VARIABLES ADDED/CHANGED

Added the `PREDICTION_*` and `GEMINI_PREDICTION_*` controls documented in
`backend/.env.example`: enable/provider/model/thinking, content thresholds,
coalescing and interval, cancellation cooldown, compatible-extension bound,
attempt/session ceilings, timeout, candidate/output bounds, and independent
context bounds. Existing M1–M5 flags and defaults remain intact.

## FEATURE ROADMAP UPDATES

- `F-043`, `F-044`, `F-046`, `F-147`: COMPLETE.
- `F-050`, `F-145`: FOUNDATION READY only.
- `F-045`, `F-047`, `F-146`, `F-148`, `F-032`, `F-034`: remain PLANNED.
- No feature ID was renumbered.

## PREDICTION DOMAIN CONTRACT

Immutable `PredictionRequest`, `PredictionContext`, `PredictionCandidate`,
`PredictionSnapshot` and session snapshot contracts sit behind a separate
one-shot `PredictionProvider`. Output types/lengths/counts are validated.
Conversation-derived fields are always `UNTRUSTED`.

## PREDICTION IDENTITY / REVISION / ATTEMPT

`prediction_id` is deterministic UUIDv5 over logical `session_id` plus active
`turn_id`. `input_revision` increases only for material input changes.
`attempt` increases only when a provider execution starts. A SHA-256 material
fingerprint covers normalized active text, ordered provenance, source/speaker,
continuity and `memory_revision`; it is an internal invalidation key, not truth.

## ACTIVE-TURN OBSERVATION DESIGN

`ConversationTurnRuntime.observe()` returns the immutable M3 update. Only after
canonical/M3 processing, WebSocket orchestration offers the current active turn
to `PredictionRuntime.observe_nowait()`. Prediction neither owns the engine nor
duplicates turn assembly, and raw provider STT events never enter prediction.

## PREDICTION RUNTIME OWNERSHIP

The logical transcription session owns at most one prediction runtime, one
latest observation slot, one supervisor and one provider executor task. The
real Gemini adapter is wrapped by one temporary worker event loop per bounded
call so third-party SDK work cannot block realtime STT.

## PREDICTION CONTEXT POLICY

Active input is budgeted first, then at most two recent and two relevant older
memory turns. Limits are 3,200 total characters, 1,200 active characters and
800 per memory turn. The planner reads immutable memory only, records the exact
`memory_revision`, and never commits partial speech.

## PROVIDER / MODEL DECISION

Production prediction uses the separate Gemini Interactions adapter with
`gemini-3.5-flash-lite`, minimal thinking, structured output, `store=false`, no
previous interaction, tools, Search or grounding. The constrained SDK supports
the call shape. A single `gemini-2.5-flash-lite` probe failed and was not retried;
it did not justify a model change.

## TRIGGER / THROTTLE / COST CEILINGS

Defaults: 12 active characters, three lexical tokens, 350 ms coalescing, 1,200
ms minimum call interval, 4,000 ms post-cancellation cooldown, at most two
attempts per turn, 64 calls per session, one active task, five-second timeout,
three candidates and 512 output tokens. Duplicate/replay/unchanged/short/weak/
ordinary/degraded/disabled input creates no call. There is no automatic retry.

## READINESS / CONFIDENCE SEMANTICS

No probability is exposed. `TENTATIVE` means a current validated provider
result exists. `STABLE` additionally requires candidate consistency across at
least two material revisions, an active turn awaiting finalization and Normal
continuity.

## INVALIDATION SEMANTICS

Material text correction, provenance/source/speaker change, new turn, memory
revision change, degraded continuity, turn finalization, disconnect, Stop,
reset, expiry, shutdown, timeout and provider failure invalidate or fail the
snapshot. Completion is equality-gated, so an older attempt cannot overwrite a
newer revision. Bounded lexical compatibility preserves only one current
running/ready basis across demonstrably neutral continuation.

## BROWSER DISCONNECT / RESUME

Disconnect cancels and clears ephemeral prediction while M5 memory and M4
Answer History retain their existing logical-session behavior. Resume replays
no prediction and makes no paid call. Genuine post-resume canonical input is
required, and unsafe audio-gap continuity suppresses speculation.

## STT ROTATION / DEGRADED CONTINUITY

Prediction identity derives from canonical turn/session state, not STT socket
identity. Rotation cannot duplicate prediction identity. Degraded continuity
fails closed and cannot promote a speculative result.

## PREDICTION QUALITY FINDINGS

The named 11-case deterministic corpus passed all trigger, suppression,
context, stability, stale-race and cleanup checks. Eight expected cases had
scripted top-k anchor usefulness and three suppression cases made no call. This
is pipeline evidence only, not general model prediction accuracy. The tiny
four-call real benchmark had 4/4 curated anchor usefulness and must be described
with the same limitation.

## LATENCY FINDINGS

The controlled four-call benchmark median was 2,792.5 ms. A separate bounded
probe measured 2,963 ms for one complete non-stream result; streaming delivered
first text at 2,628 ms but valid JSON only at 3,938 ms and completion at 4,071
ms. The final live result completed in 3,593 ms and was ready 2,344 ms before
turn finalization. Actual answer first text remained roughly three to four
seconds, so no answer-latency improvement is claimed.

## COST FINDINGS

The four successful benchmark requests used 1,658 input and 571 output tokens
(2,229 total), estimated at USD 0.0019249 using the recorded pricing basis. The
offline corpus cost proxy was USD 0.0018002. Cancelled-call provider billing is
unknown; ceilings and cancellation metrics bound exposure but do not imply
cancelled calls are free.

## SPECULATIVE GENERATION DECISION

Deferred. The fake gate accepted only exact text plus unchanged identity,
provenance, memory, stable readiness and continuity; semantic paraphrase was
rejected. No production implementation or feature flag was added, no hidden
generation entered Answer History, and `F-045` remains planned.

## PRIVACY / RETENTION

Prediction is backend RAM-only and is not persisted to disk, database,
`localStorage` or `sessionStorage`. Normal logs contain only content-free
identity/timing/count/size/state metrics. Requests use only bounded active-turn
and selected memory context; no full session, answer history, credentials,
resume token or unrelated environment value is sent. Backend restart loses it;
no cryptographic RAM wiping is claimed.

## PROMPT-INJECTION NOTES

Trusted policy and untrusted conversation JSON are structurally separated.
Prediction has no tools/actions and cannot reveal credentials, change flags,
become policy, create verified facts, write memory or create an answer.
Adversarial tests cover these boundaries.

## ANSWER HISTORY / M5.6 COMPATIBILITY

Prediction state remains separate from `answerOrder`, `answersById` and
ConversationMemory. Answer identity/order semantics are unchanged; predictions
never become answers automatically. M5.6 can implement previous/next/back-to-
live navigation while transcription, answering and live prediction continue,
without rewriting M5.5.

## M6 TRUTH-LOCK COMPATIBILITY

Prediction memory inputs remain untrusted and outputs non-authoritative. Future
verified profile/document context can be added as a separate provenance source
through the context boundary; no PredictionProvider rewrite is required.

## BACKWARD-COMPATIBILITY

All M1–M5 ownership, identity, replay, memory, answer, outbound, privacy and
provider-neutral contracts remain intact. No database migration exists.

## ROLLBACK

`PREDICTION_ENABLED=false` constructs no prediction provider/runtime/task/event
and restores verified M5 behavior. Existing memory, answer and conversation
rollback flags are unchanged. Setting
`PREDICTION_MAX_COMPATIBLE_EXTENSION_CHARS=0` restores strict cancellation on
every active-text change without disabling prediction.

## KNOWN LIMITATIONS / TECH DEBT

Cloud latency varies; many short or rapidly corrected turns may produce no
visible candidate. Trigger coverage is bounded English/common-Hinglish rather
than general multilingual understanding. Cancelled-call billing is unknown.
No calibrated probability, production local predictor, full topic model,
Radar/open threads, speculative answer, persistence or multi-worker ownership
is included.

## KNOWN BUGS

None known in the verified M5.5 scope. Provider/audio-dependent STT
mistranscriptions remain an existing system limitation and are not silently
rewritten by prediction.

## DEFERRED ENGINEERING REGISTER UPDATES

`M5.5-DEFER-01` provider calibration remains evidence-bounded;
`M5.5-DEFER-02` broader multilingual triggers, `M5.5-DEFER-03` speculative
answers, `M5.5-DEFER-04` calibrated confidence and `M5.5-DEFER-05` cancelled
cloud-call billing visibility remain open.

## WHAT SHOULD NOT BE CHANGED WITHOUT REASON

Do not weaken canonical transcript/turn ownership, material-change
invalidation, equality-gated completion, memory provenance, Answer History
separation, hard call/context/output bounds, isolated provider execution,
content-free logging or the feature-flag rollback. Do not replace readiness
with fabricated probability or treat prediction as fact/answer truth.

## RECOMMENDED NEXT MILESTONE

M5.6 — Session Timeline / Q&A Navigator. Do not start it as part of this
closeout.

## NEXT MILESTONE PREREQUISITES

Start from the final sanitized ZIP; inspect `PROJECT_STATE.md`, architecture,
roadmap and this handoff; preserve stable answer identity/order and keep live
prediction separate from historical navigation. Re-run the complete gate before
runtime changes.

## FINAL SANITIZED ZIP

`mentara-milestone-5-5-complete.zip` — the final delivery message records its
SHA-256 and completed integrity/exclusion/secret scan results.

Return to 00 — MASTER and provide the final M5.5 ZIP before starting another
milestone.

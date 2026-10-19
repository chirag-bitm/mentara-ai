# Milestone 5.5 live prediction timing review

Status: COMPLETE — final evidence recorded 2026-10-18. This document preserves
the diagnostic history that led to the final bounded runtime; the authoritative
closeout is `MILESTONE_5_5_HANDOFF.md`.

## Verified observations

- The target Windows r3 checkpoint passed 389 backend tests, 28 frontend
  tests, lint, strict TypeScript and a production build. The earlier four-call
  stateless Gemini benchmark succeeded at 2,588, 2,642, 2,943 and 3,975 ms.
  It did not test simultaneous evolving speech.
- The 2026-09-20 browser recheck showed a Live connection, Normal finalized
  turn continuity, and one completed answer. In that normal logical session,
  Turn 2 and Turn 3 each made exactly one prediction attempt; neither logged
  `Prediction ready`. Both finalized with `state=scheduled`, cumulative
  cancelled-call count two, and no measured prediction lead time. The real
  Turn 3 answer reached first text after 3,641 ms. The earlier degraded
  connection is a separate episode.
- The normal recheck's attempt started 4,892 ms before Turn 2 finalized and
  5,042 ms before Turn 3 finalized. These are *available turn windows*, not
  completed provider latencies. Later input invalidated each attempt, so
  the presence of a multi-second window did not make its old result current.
- The 11-case offline fake-provider quality evaluator waits for each provider
  to finish *before* submitting the next prefix. Its 1,000 ms simulated lead
  time is conditional on that artificial order, not a live-speech result.
- A separate ten-times-accelerated fake timing test now sends continuing
  partials faster than the scripted provider can return. It confirms that
  the old call cancels, no stale candidate becomes ready, the per-turn call
  ceiling holds, and shutdown leaves no tasks. Another test confirms stable
  input can become ready, and a subsequent correction immediately clears it.
  These tests do not estimate Gemini quality or billing.
- The local regression after adding timing checks and content-free cancellation
  timing logs is 391 backend and 28 frontend tests, lint, strict TypeScript,
  build, M5 memory evaluation, M5.5 fake prediction evaluation and the
  speculative decision evaluation, all passed. Runtime prediction policy,
  call bounds, output, transcript, memory and answer contracts were unchanged.

## Diagnosis and constraints

An authoritative material change in active text, provenance or memory
invalidates the current prediction. A completed provider result from an older
revision cannot be displayed as current. With 2.6–4.0 s measured single-shot
provider latency and partials often changing roughly every 0.5–1.0 s, a call
can be correct, cancel promptly, and still produce no visible candidate.
The 4 s cooldown saved a second immediate call in the normal Windows turns;
it cannot make a cancelled result ready. Costs of cancelled network calls are
unknown. The STT provider may also finalize a preface as one logical turn and
start the actual question as another; M3 turn identity/merge behavior remains
authoritative and must not be adjusted for this demonstration.

Changing only the 350 ms coalescing interval, 4 s cooldown, or two-call ceiling
cannot make a 2.6–4.0 s old-revision result current after a material change.
Starting later can save spend, but does not establish useful lead time.
Increasing the call ceiling spends more without fixing stale-result safety.
The sequential quality corpus cannot be used to justify claiming M5.5 is
complete. Never infer that the cloud canceled before being billed.

## Bounded paths to evaluate

| Path | Required proof | Current decision |
| --- | --- | --- |
| Lower-latency, tiny stateless structured output or an early *complete* streamed candidate | Current constrained SDK supports it; fake correction and streaming races pass; controlled non-sensitive provider test beats the observed partial cadence with bounded calls and useful candidates | Research only; do not change model or upgrade SDK without evidence |
| Preserve one basis attempt across a neutral append-only preface | Explicit compatibility semantics must still reject corrections, direct questions, topic/source/speaker/memory changes, replay and older-revision completions | Implemented conservatively after the faster-model path failed; target-Windows recheck remains |
| Local deterministic next-topic hints | Provider-neutral quality, suppression, bounded output and strong correction tests | Production local prediction is explicitly outside M5.5 scope; do not silently add it |
| Keep current strict cloud sidecar | Explain best-effort visibility and limit cost | Safe fallback while Phase J remains open; not evidence of useful live prediction |

Continue M5.5 only with a measured path that respects the user-approved
contracts. Keep speculative answer generation disabled. M5.6 Answer History
and M6 verified-context boundaries remain separate. If no bounded provider
path can meet the live checkpoint under strict invalidation, report the
evidence and leave the milestone open until an explicit scope/contract
decision is made; do not weaken stale-result guarantees or claim completion.

## 2026-09-20 independent provider-path experiment

Current official Gemini documentation and the installed `google-genai==2.23.0`
SDK support streaming structured JSON using `step.delta` text events and a
terminal `interaction.completed` event. A bounded, **benchmark-only** probe
(`probe-prediction-latency.bat`) now compares one-candidate nonstream and
one-candidate stream on one fixed non-sensitive corpus case. It uses `store=false`,
no tools or previous interaction ID, at most 256 output tokens and 12 seconds
per call, with **at most two calls total and no retry**. The streamed text
buffer is capped at 4,096 characters. The output saves only timing/usage and
fixed statuses, never the candidate, speech or key. The first valid JSON
timestamp is exploratory; only fully completed valid output could be
considered for authoritative *prediction* readiness, after the runtime's
unchanged current-input check.

Four fake transport cases verify streaming shape, success, incomplete/malformed
stream rejection, client cleanup and fail-closed reporting. Full local
regression: **395 backend, 28 frontend, lint, TypeScript, build and both
deterministic evaluations passed**. This is not evidence that a live speaker
will see a suggestion. No production runtime, trigger, model, answer or
memory behavior changed. One controlled Windows measurement is the next
technical step; a single fast sample alone will not establish reliability
against 0.5–1.0 s speech revisions. Review real completed latency, observed
first-text timing and token usage before any production change or further
browser recheck. The current safe implementation remains available.

### Windows probe launch correction

The first Windows invocation exited with `ModuleNotFoundError: No module named
'scripts'` before any Gemini request or result file. Executing a Python file
by its path places the file's directory on `sys.path`, not its project parent.
The probe now explicitly inserts the project root and backend root before
importing its fixed benchmark helper. A subprocess test launches the script's
imports from another working directory with Python isolated mode, so the
regression catches this packaging/launch error without calling a provider.
The corrected gate passed 396 backend and 28 frontend tests, lint, strict
TypeScript, build and all three deterministic evaluations. Use the r2 probe
checkpoint, not the earlier archive, for the one remaining private-provider
measurement.

## 2026-09-20 target-Windows latency measurement and model gate

The corrected two-request probe succeeded. The user supplied the sanitized
machine-readable result in `MILESTONE_5_5_LATENCY_PROBE.json`: one-candidate
nonstreaming `gemini-3.5-flash-lite` returned a complete valid result in
**2,963 ms** (393 input, 69 output tokens). Streaming the same fixed demo case
returned first text in **2,628 ms**, its first complete valid JSON at
**3,938 ms**, and the terminal completed result at **4,071 ms** (393 input,
39 output tokens). Both requests had `store=false`, no tools, no previous
interaction and a 256-token output ceiling. No candidate bodies or private
speech appear in the saved result.

Streaming's first text is not a complete validated prediction. This sample
does not support changing production to streaming or a one-candidate mode for
live readiness. The production three-candidate predictor remains unchanged;
its earlier measured 2.6–4.0 s runtime and the 0.5–1.0 s evolving-partial
cadence still explain cancellations. The two responses are single sequential
measurements rather than controlled repeated latency distributions, so the
data do not prove streaming generally slower than nonstreaming or establish
general prediction quality. Repeating the same two-call experiment just to
obtain a favorable sample would add cost without resolving the design issue.

Official Gemini documentation lists `gemini-2.5-flash-lite` as an Interactions
model whose default thinking is off; it supports structured output and has a
stable model ID. A separate **one-request, non-sensitive, benchmark-only**
comparison will check whether a completed validated candidate can return
substantially sooner on the same bounded prompt and constrained SDK. It
does not change the runtime, upgrade the SDK or assume eventual live success.
If this path also cannot beat the observed partial cadence, retain current
strict invalidation and report the product limitation accurately rather than
shipping stale predictions, increasing call ceilings or starting M5.6/M6.
The local gate for this separate one-call helper passed 400 backend tests,
28 frontend tests, lint, strict TypeScript, the production build and the M5
memory, M5.5 fake prediction and speculative decision evaluations. An isolated
process import test and fake provider tests ensure no repeat of the earlier
Windows import failure, no tools, `store=false`, capped output, one request,
no thinking setting for the 2.5 model, fail-closed output and client cleanup.
Real alternative-model latency is still unknown.

## 2026-09-29 alternative-model result and bounded runtime recovery

The single permitted `gemini-2.5-flash-lite` call produced only the sanitized
`probe_failed` result in `MILESTONE_5_5_FAST_MODEL_PROBE.json`. The report does
not expose provider text and therefore cannot safely distinguish transport,
completion, schema or zero-candidate failure. The call was not retried. It
provides no latency measurement and no basis for changing the production model,
which remains `gemini-3.5-flash-lite` with minimal thinking.

The runtime now applies an explicit provider-neutral compatibility rule to the
measured continuous-partial race. It may preserve exactly one existing
`RUNNING` or `READY` attempt only when newer canonical text is a strict,
short append to the same basis and the suffix remains a neutral unfinished
preface. The production bound is 96 normalized characters. The basis request,
fingerprint, input revision, context and provider task are not rewritten.
Scheduled work continues to coalesce normally.

The rule fails closed for a direct question/request signal (including bounded
common-Hinglish signals), correction, pivot, negation, sentence boundary,
unknown/new topic term, named token, finalization wait, source/speaker or
utterance-provenance change, memory revision change, degraded continuity or a
longer suffix. A material change immediately clears any ready candidate and
uses the existing revision/cancellation path. Setting
`PREDICTION_MAX_COMPATIBLE_EXTENSION_CHARS=0` restores the prior strict
cancel-on-every-text-change behavior independently of `PREDICTION_ENABLED`.

The accelerated race now proves that a 2.8-second-equivalent delayed provider
can complete once across several safe 0.5-second-equivalent preface extensions,
and that the first appended direct question clears it. The older correction
storm continues to cancel without showing stale output. The complete revised
local gate passed 425 backend tests, 28 frontend tests, lint, strict TypeScript,
production build and all three deterministic evaluations. This is safety and
timing evidence, not real-provider usefulness; one short Windows microphone
recheck remains required before Phase J can close.

## 2026-10-16 real-STT replay correction

The first microphone run against that append-only recovery still showed no
ready candidate. Its content-free log proved that one bounded attempt started
and was safely cancelled **766 ms** later with `active_input_changed`; the
normal authoritative answer path remained unaffected and no stale result was
published. The session-wide cancellation count was cumulative and did not
represent an unbounded queue for that turn.

Review found a deterministic false incompatibility rather than a lifecycle or
provider defect. Because the provider call may begin late in the preface, its
basis can already end in `interested in the` or the unfinished token `trade`.
The earlier allowlist required the entire appended suffix to begin with one of
a few fixed phrases, so a later `trade-offs` completion—or a cosmetic comma or
hyphen rewrite—could cancel otherwise current work.

The compatibility policy now operates on a bounded lexical prefix. It allows
case/comma/hyphen-only churn, completion of the single final unfinished token,
and newly appended terms from a fixed general-framing set. It does **not** use
fuzzy matching or a model. Deleted/reordered words, a new named or topic term,
direct question/request language (including the existing Hinglish signals),
negation, correction/pivot language, strong sentence boundaries, excessive
growth and every existing provenance/context/continuity change still fail
closed. The provider request, basis fingerprint, context and input revision are
never rewritten after launch.

An accelerated replay now starts the delayed fake provider from the same late
`interested in the` basis, supplies `trade-offs` on a later partial, proves one
ready result with no cancellation, and then proves that an appended direct
question clears it immediately. The full local result is **434 backend and 28
frontend tests**, lint, strict TypeScript, production build, plus passing M5
memory, M5.5 prediction and speculative-decision evaluations. No dependency,
model, timeout, attempt ceiling, context bound or provider prompt changed. One
final Windows microphone check remains; do not repeat either provider benchmark.

## 2026-10-18 realtime-loop isolation correction

The next R3 Windows recheck passed 434 backend tests and the complete frontend
gate, then produced no ready live candidate. The content-free log isolated two
distinct paths. The neutral prediction attempts were cancelled with
`continuity_degraded` after 5,687 ms and 2,093 ms, while the UI reported that
the existing two-second STT reconnect buffer filled. A later direct question
cancelled its own speculative attempt with `active_input_changed`, which is the
required fail-closed behavior, and produced exactly one authoritative answer.

This evidence does not justify weakening compatibility or increasing the audio
buffer. Instead, the real Gemini predictor now runs behind a provider-neutral
event-loop isolation wrapper. One temporary worker loop executes exactly one
bounded provider call. Outer cancellation is forwarded to the inner async SDK
task, and completion/failure/cancellation is returned without adding a retry or
queue. The STT sender, transcript engine and answer runtime remain on the main
application loop and retain their existing ownership.

A deterministic regression uses an intentionally blocking async provider and
proves that the main application loop still advances. Separate tests prove
cross-loop cancellation reaches the provider, the worker terminates, and
provider failures preserve their existing mapping. The full corrected local
gate passes **437 backend and 28 frontend tests**, lint, strict TypeScript,
production build and all three deterministic evaluations. This establishes the
local concurrency boundary, not real Windows readiness; one final microphone
recheck is still mandatory.

## 2026-10-18 R4 result and provider-final compatibility correction

R4 confirmed the isolation objective: the target browser remained Live with
Normal continuity, and the backend recorded no reconnect-buffer fill or
`continuity_degraded` prediction cancellation. It therefore closes the
realtime-loop starvation defect.

R4 did not yet produce a ready candidate. A neutral attempt was cancelled on
`active_input_changed` 1,047 ms after start, immediately before the same source
utterance entered its provider-final merge window. In the longer preface, an
early correction cancelled attempt one; the bounded cooldown allowed attempt
two, but authoritative turn finalization arrived 344 ms later. No stale output
appeared and no answer or memory state changed.

The remaining issue was the runtime's unconditional rejection of
`awaiting_finalization` inside the otherwise conservative append-only
compatibility path. That metadata transition is not itself a text correction.
The runtime now permits it to preserve one already-running or ready attempt
only if the complete earlier lexical prefix, fixed general-framing allowlist,
96-character bound, identical source/speaker/provenance, unchanged memory
revision and Normal continuity checks all pass. Provider-final corrections,
direct intent, topic changes and the authoritative finalized-turn callback
still invalidate immediately.

Two new deterministic races cover both sides: a compatible provider-final
extension reaches READY without a second call, while a provider-final DynamoDB
correction cancels the Redis-basis attempt and exposes no candidate. The full
R5 local gate passes **439 backend and 28 frontend tests**, lint, strict
TypeScript, production build and all three deterministic evaluations. This is
the narrow final live-readiness candidate; one Windows microphone check remains.

## 2026-10-18 R5 result and R6 bounded correction

R5 preserved Normal realtime continuity and generated one authoritative answer,
but it produced no ready prediction. The neutral preface consumed two attempts;
canonical partial evolution cancelled them after 578 ms and 532 ms. The turn
recorded one compatible extension, two cancelled calls, zero stale completions
and no prediction-ready lead time. This confirms that the event-loop isolation
works while the lexical compatibility rule remains narrower than real Gemini
Live partial churn.

The screenshots also exposed an independent M4 policy mismatch. “What do you
mean by sex?” was detected, submitted and completed normally, yet the model
redirected to the preceding Redis discussion. The documented policy already
allowed general answers, but its wording did not explicitly make the current
request primary. R6 adds that explicit priority and allows model general
knowledge only for impersonal general/technical questions. User-specific facts
must still come from supplied context, and missing personal facts remain
generic or explicitly unavailable.

For prediction, R6 does not introduce semantic similarity. It adds only two
deterministic cosmetic cases observed in live STT: one trailing statement
period, and a long common-stem inflection between fixed general-framing terms
such as `mention` and `mentioned`. Topic anchors and token order remain exact;
questions, corrections, new topics, provenance/context changes and finalized
turns still fail closed. The complete local gate passes **445 backend and 28
frontend tests**, lint, strict TypeScript, production build and all three
deterministic evaluations.

## 2026-10-18 final R6 live timing result

R6 completed the target checkpoint without weakening current-input safety. A
real three-candidate prediction completed in **3,593 ms**, remained valid across
**seven** deterministic compatible active-turn extensions and was ready
**2,344 ms before authoritative turn finalization**. A later material
Redis-to-DynamoDB correction cleared the advisory state and no stale result
returned. The clean session stayed Live with Normal continuity.

The final reconnect check opened a new WebSocket but produced no provider or
answer request from replay alone. Genuine post-gap input was conservatively
marked continuity-unsafe for prediction, while the authoritative cache-miss
question still received exactly one answer. Stop released the microphone and
left no visible prediction or unhandled backend error.

This single successful live observation demonstrates useful lead time for the
tested path, not a general provider-latency distribution or calibrated
prediction accuracy. Actual answer first-text latency remained about three to
four seconds in the recorded checks, so F-050 stays `FOUNDATION READY` and
speculative answer generation remains deferred.

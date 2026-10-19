# Milestone 5.5 Phase J — minimal target-Windows checkpoint

Status: COMPLETE AND VERIFIED — 2026-10-18. The historical attempts below are
retained because they explain the final bounded concurrency and compatibility
design; the final R6 result is authoritative for closeout.

## R6 checkpoint preparation

The previous live check was useful even though no candidate appeared: one
prediction request started and was cancelled 766 ms later by an active-input
change. The refined runtime now preserves that request across only bounded
lexical-prefix-compatible completion such as `trade` to `trade-offs` and
cosmetic comma/case/hyphen churn, one terminal period and a fixed general-term
inflection. It continues to fail closed on direct intent,
negation, correction, deletion/reordering, new topics and every existing
provenance/context/continuity change. A content-free
`compatible_extension_count` is included in each turn outcome log.

The revised local gate passes **445 backend tests, 28 frontend tests**, lint,
strict TypeScript, production build and all three deterministic evaluations.
The real Gemini predictor now executes on one temporary isolated worker loop so
SDK work cannot starve the realtime STT loop; cancellation still reaches the
inner request and no retry or queue was added. A compatible provider-final
merge-window update now preserves that isolated in-flight request without
weakening correction or finalized-turn invalidation. The answer prompt also
makes the current request primary while preserving personal-fact protection.
Use the latest R6 checkpoint and
perform the single short check below. Do not rerun either standalone provider
benchmark.

## Earlier checkpoint after 2026-09-29 runtime recovery

The one-call `gemini-2.5-flash-lite` comparison was executed once and returned
the sanitized `probe_failed` result. Do not rerun it. Production remains on
`gemini-3.5-flash-lite`; the failed call supplied neither a completed latency
nor evidence for a model change.

The revised runtime instead preserves one provider attempt across only a short,
neutral append-only preface. It still invalidates immediately on a direct
question, correction, pivot, new topic, source/speaker/provenance change,
memory change, degraded continuity or finalization. The local gate passes 425
backend and 28 frontend tests, lint, strict TypeScript, production build and all
three deterministic evaluations. Phase J remains open until this exact revised
runtime passes the short live sequence below. Do not run another standalone
paid benchmark.

## Earlier 2026-09-20 bounded timing probe

The corrected r2 timing probe finished its two non-sensitive calls. The
one-candidate nonstream result took **2,963 ms** to complete; streaming
delivered first text at **2,628 ms** but its validated JSON only at **3,938 ms**
and completed at **4,071 ms**. The result is preserved in
`MILESTONE_5_5_LATENCY_PROBE.json`. Do not rerun the old probe merely to seek
a faster sample, and do not repeat the microphone test on unchanged runtime.

The later one-call comparison described above is now complete and must not be
repeated. It made no production model change and did not complete the Windows
microphone checkpoint.

The first Windows run passed all 381 backend and 28 frontend tests, lint,
TypeScript and production build. Its four Gemini requests returned
`provider_server` / "Gemini did not complete prediction." The recorded report
did not include the provider's exact non-completion status, so this does not
establish the cause. The ordinary statement was correctly suppressed.

The corrected r2 checkpoint increased the still-bounded output allowance from
128 to 512 tokens because the Gemini limit includes thought tokens. It records
only a fixed, content-free completion reason. The benchmark stops after its
first failed paid call and records remaining cases as aborted. No original
benchmark result has been treated as success. On 2026-09-19, the r2 benchmark
completed four of four non-sensitive requests with 2,588–3,975 ms latency
(median 2,792.5 ms), an estimated total USD 0.0019249, and one ordinary
statement suppressed. The 4/4 top-1 anchor usefulness in this tiny curated
set does not imply general accuracy. Production microphone Turn 7 produced
two cloud attempts on successive partial revisions but no ready prediction;
the real question and exactly one answer continued normally. An earlier
audio-gap attempt was correctly invalidated with degraded continuity.

The follow-up revision adds a 4,000 ms per-turn cooldown after an in-flight
attempt is cancelled by newer active input. It retains the two-attempt turn
ceiling, current-input-only completion, and 64-call session ceiling; it cannot
guarantee useful predictions for turns shorter than the measured 2.6–4.0 s
provider latency. It records a content-free `Prediction turn outcome` log and
shows a waiting label instead of the technical `Invalidated` state. The live
microphone checkpoint remains pending; do not mark M5.5 complete from the
benchmark alone.

## 2026-09-20 follow-up evidence and decision

The r3 Windows gate passed **389 backend and 28 frontend tests**, lint, strict
TypeScript and the production build without rerunning the paid four-call
benchmark. The follow-up browser screenshots showed a **Live** connection,
**Normal** turn continuity, and exactly one completed authoritative answer.
The supplied content-free backend log showed that the new normal-continuity
session made one predictor attempt on Turn 2 and one on Turn 3. Both turns
ended with `state=scheduled` and no `Prediction ready` log or measured lead
time. The cumulative cancellation count was two. Turn 3's real answer reached
its first text 3,641 ms after question detection.

The earlier degraded connection correctly suppressed prediction, but cannot
explain this separate normal-continuity result. Continuous partial revisions
invalidate older cloud work; the four-second cooldown prevented an immediate
second attempt on each turn. The scripted 11-case quality evaluation waits for
the fake provider after each input revision, so its reported 1,000 ms lead time
does not measure this live race. A separate ten-times-accelerated timing test
now checks that rapid partials cancel an older delayed provider result without
showing stale candidates, while a stable input can become ready. These are
local engineering checks, not real prediction-latency measurements. The
revised local gate passed 391 backend and 28 frontend tests, including a
privacy check for the new content-free cancellation timing log. See
`MILESTONE_5_5_LIVE_TIMING_ANALYSIS.md` for the design review.

Earlier next step: run the newly prepared bounded provider latency comparison once, with
the already configured Windows Gemini environment. The offline fake checks and
full local gate passed **395 backend / 28 frontend**, lint, TypeScript, build,
and the deterministic evaluations. This is a two-request **measurement**, not
a production model or runtime change. Keep Phase J open and preserve the
original M5 verified fallback.

### Completed Windows checkpoint: two-call timing measurement

The first latency-probe package stopped at an import error **before any
provider call**. Use the corrected **latency-probe-r2 checkpoint**, which adds
an isolated direct-launch regression test. Existing r3 and first-probe archives
do not have that fix. Close server windows before replacing files. Extract
the corrected checkpoint archive over the existing project root so that the root
contains `probe-prediction-latency.bat`, `backend` and `frontend`. Retain the
existing private `backend\.env` and installed dependencies. In PowerShell at
that project root run exactly:

```powershell
.\probe-prediction-latency.bat
```

The helper needs no backend or frontend server. It makes at most two
non-sensitive stateless calls, stops after one error, and writes sanitized
`docs\MILESTONE_5_5_LATENCY_PROBE.json`. Provide **only that JSON**; do not
send an API key or transcript. The result will decide whether one-candidate
output or streaming offers a credible path to a useful, fully current live
prediction. Do not repeat this paid experiment simply to seek a fast sample.
The corrected package passed 396 backend and 28 frontend tests, lint,
TypeScript, production build and deterministic evaluations.

## Follow-up live checkpoint

Close the old backend and frontend windows. Extract the latest live-readiness
checkpoint ZIP *over* the existing `mentara-m5-5-phase-j-r2` project
root. `Expand-Archive -Force` replaces project files while retaining the
existing private `backend\.env`, installed dependencies and Git directory,
which are absent from the ZIP. Confirm the root contains
`m5-5-live-recheck.bat`, `backend` and `frontend`.

## One command

In a new PowerShell at the project root run:

```powershell
.\m5-5-live-recheck.bat
```

The helper runs the complete automated gate and starts backend/frontend in two
separate windows. It makes no benchmark request. Expected result: 437 backend
tests, 28 frontend tests, lint, TypeScript and production build pass. Keep both
server windows open.

## Short browser check

Open Chrome at `http://localhost:3000` and:

1. Start transcription. Say normally: “We use Redis for caching in our
   application.” Wait until that statement finalizes.
2. In one continuous slow utterance, without a long silence, say: “You mentioned
   Redis in your architecture and I am interested in the trade-offs.” Take about
   six seconds. Watch **Likely next** while speaking.
3. Record whether one to three advisory candidates become visible before the
   turn finalizes. They must remain separate from the real-answer panel.
4. Immediately continue: “What happens if Redis becomes unavailable?” The old
   advisory candidates must clear as soon as this direct question changes the
   prediction input. Exactly one authoritative answer should then appear.
5. Begin another harmless preface, then say “actually, DynamoDB” as a correction.
   Any earlier suggestion must disappear and must not flash back.
6. Refresh once. The refresh itself must not replay a prediction or create a
   paid predictor/answer request. Speak genuinely new input after reconnect.
7. Press Stop while prediction is idle or active. Confirm microphone release,
   responsive transcript behavior and no unhandled exception in either server.

Report: whether a candidate appeared during step 2, whether it cleared in steps
4 and 5, whether exactly one answer appeared, and the content-free
`Prediction turn outcome` backend lines. The step-2 line now includes
`compatible_extension_count`; copy that whole line. Never send the API key or
transcript bodies. Do not repeat the paid test merely to seek a favorable
sample.

## 2026-10-18 R3 result and required R4 recheck

The R3 automated gate passed, but the live check did not. Two neutral predictor
calls were cancelled with `continuity_degraded` after 5,687 ms and 2,093 ms,
coinciding with the existing bounded STT reconnect buffer filling. A later
direct-question attempt was correctly cancelled by `active_input_changed`, and
exactly one authoritative answer completed. No stale prediction was exposed,
but there was no `Prediction ready`, so Phase J remains open.

R4 isolates only the real Gemini prediction call from the realtime application
event loop. It does not enlarge the M2 audio buffer, loosen invalidation, change
the model/prompt/timeout/call ceilings or rerun the paid benchmark. Its local
gate is **437 backend / 28 frontend**, plus lint, TypeScript, build and the three
deterministic evaluations. Repeat the short browser check once against R4 and
report the same content-free outcome lines. A successful run must show normal
STT continuity, at least one `Prediction ready` for the neutral preface, safe
clearing on the direct question/correction, exactly one real answer and clean
Stop.

## 2026-10-18 R4 result and required R5 recheck

R4 fixed the concurrency failure: the browser stayed Live, continuity remained
Normal and no audio-buffer or `continuity_degraded` event appeared. It did not
complete Phase J because no call became ready. The content-free timing showed a
compatible provider-final transition cancelling one neutral attempt and a
later replacement attempt starting only 344 ms before authoritative turn
finalization.

R5 removes only the unconditional provider-final rejection from the existing
append-only compatibility gate. An in-flight attempt survives the merge-window
transition only when text remains a bounded neutral lexical continuation and
source, speaker, provenance, memory revision and continuity are identical.
Corrections, direct intent, topic changes and finalized turns still cancel.
The local R5 gate is **439 backend / 28 frontend**, plus lint, TypeScript,
production build and all three deterministic evaluations. Repeat the same one
short browser check; do not rerun either paid benchmark.

## 2026-10-18 R5 result and required R6 recheck

R5 kept the connection Live with Normal continuity, so the realtime-loop fix
remains effective. It did not complete Phase J: two prediction attempts were
cancelled after 578 ms and 532 ms as the canonical partial evolved, and no
candidate became ready. One compatible extension was preserved and no stale
candidate appeared.

The run also found that a general question reached the answer provider and
completed, but the generated response redirected to the earlier Redis context.
R6 explicitly prioritizes the current request and permits general knowledge for
impersonal questions while preserving all verified-personal-fact restrictions.
For prediction, R6 recognizes only a terminal statement period and fixed
general-framing inflection as additional cosmetic STT churn. The R6 local gate
is **445 backend / 28 frontend**, plus lint, TypeScript, production build and
all three deterministic evaluations. The short R6 check must verify both one
unrelated general question and the existing prediction/correction flow.

## Final R6 target-Windows result — passed

The final checkpoint used the physical microphone, Chrome and the constrained
`google-genai==2.23.0` environment. The automated Windows gate passed 445
backend tests, 28 frontend tests, lint, strict TypeScript and the production
build before the live check.

Verified live behavior:

- the browser remained responsive and a clean session showed Live / Normal
  continuity;
- one real `gemini-3.5-flash-lite` attempt returned three bounded candidates in
  3,593 ms;
- the ready result survived seven deterministic compatible active-turn
  extensions and preceded authoritative finalization by 2,344 ms;
- an active Redis-to-DynamoDB correction cleared prior advisory state without a
  stale flash;
- an unrelated general question was answered from general knowledge rather
  than redirected to earlier Redis context;
- the Redis-unavailability and post-refresh cache-miss requests each produced
  exactly one authoritative answer;
- refresh opened a new WebSocket but did not itself schedule a prediction or
  answer call; unsafe post-gap continuity suppressed speculative work;
- prediction remained absent from transcript, ConversationMemory and Answer
  History;
- Stop returned the UI to Ready, displayed `Transcription stopped`, released
  the microphone and produced no unhandled backend exception.

The live prediction was operationally `TENTATIVE`; no probability was exposed.
The earlier controlled four-request benchmark remains a tiny curated check and
must not be described as general prediction accuracy. No provider benchmark
needs to be rerun for this milestone.

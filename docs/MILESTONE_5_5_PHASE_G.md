# Milestone 5.5 Phase G — deterministic prediction evaluation

Date: 2026-09-13

Status: LOCAL EVALUATION COMPLETE; tiny real-model benchmark completed;
continuous microphone usefulness remains open in Phase J.

## Corpus and interpretation

The fixed 11-case corpus covers technical and behavioral follow-ups, an older
topic return, ambiguity, a midway topic change, a correction, an ordinary
statement, a backchannel, common Hinglish, a missing/mistranscribed anchor and
provider-final input awaiting merge. It includes microphone/local and
system/remote provenance.

This is an offline deterministic full-pipeline evaluation with scripted fake
candidates. Its top-k anchor result measures Mentara lifecycle/planner behavior
on the named corpus; it is **not** general model prediction accuracy.
The evaluator deliberately waits for the fake provider after each prefix.
Consequently its simulated lead time assumes the response finishes before the
next transcript revision. It does **not** represent continuous microphone
speech or establish live readiness under real model/network latency. A separate
rapid-partial timing race was added after the September 20 Windows recheck;
see `MILESTONE_5_5_WINDOWS_CHECKPOINT.md` and
`backend/tests/test_prediction_live_timing.py` for that evidence.

## Recorded results

- 11 cases: 8 prediction-expected and 3 suppression-expected.
- Unnecessary prediction rate on suppression cases: 0.0.
- Scripted top-1 and top-k anchor usefulness: 1.0.
- 11 provider calls total; mean 1.0 per case; maximum 2 per turn.
- One active provider call maximum; correction race cancelled one old call and
  discarded one stale completion.
- Simulated lead time before finalization: 1,000 ms for all eight expected
  cases.
- Latest local `observe_nowait` overhead: median 0.0622 ms, p95 0.1746 ms,
  maximum 0.1996 ms in this environment.
- Maximum selected context: 132 characters under the 3,200-character limit.
- Character/4 cost proxy: 5,034 input and 116 output tokens; estimated corpus
  cost USD 0.0018002 at the recorded pricing basis. These are not provider token
  counts.

Every evaluation check passed, including memory non-mutation and zero pending
tasks after cleanup. The machine-readable evidence is
`MILESTONE_5_5_PREDICTION_EVALUATION.json`; the corpus is stored separately.

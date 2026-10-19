# Milestone 5.5 Phase H — speculative answer decision gate

Date: 2026-09-13

Status: COMPLETE — speculative answer generation is explicitly deferred.

## Decision

M5.5 does not implement or expose speculative answer generation. Prediction and
context prefetch are useful advisory preparation, but M5 context planning is
already sub-millisecond and does not eliminate model/network answer latency.
Showing a predicted answer as authoritative would add correctness, privacy and
cost risk without measured safe benefit.

## Fake-provider experiment

A hidden local decision experiment exercised seven compatibility cases. Only an
exact match across normalized final text, logical session, turn, source/speaker,
memory revision, stable readiness and normal continuity was eligible (1/7).
Semantic paraphrase, memory change, source change, tentative readiness,
degraded continuity and correction were all discarded. Correction cancelled
the hidden task, maximum concurrency remained one and nothing entered Answer
History.

Strict compatibility alone would still add a second paid generation for every
speculative attempt. Real prediction benefit is not established in the target
environment, so no production speculative path and no experimental feature
flag were added.

`F-045` remains `PLANNED`; `F-032` and `F-034` are unchanged. The evidence is
recorded in `MILESTONE_5_5_SPECULATIVE_DECISION.json`.


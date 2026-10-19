# Milestone 5 Phase E — long-session evaluation and summary decision

## Status

Complete. Results are recorded in
`docs/MILESTONE_5_MEMORY_EVALUATION.json`; the reusable offline evaluator is
`scripts/evaluate_memory_context.py`.

## Controlled result

The fixed corpus represents 300 turns over 120 minutes. Default storage retained
the newest 256 turns (28,218 characters), reported 44 deterministic evictions
and revision 300. A separate character-pressure corpus stopped exactly at the
160,000-character cap with 160 retained entries.

The final named Redis return selected turn 100 plus turns 296–299 and the source,
using 567 characters—2.01% of retained text and about 142 tokens using an
explicit `ceil(chars/4)` proxy. This is not a provider token count. All storage,
context, short-follow-up, older-topic and degraded-continuity checks passed.

Observed local timings in this environment were:

| Operation | Samples | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| memory observation | 300 | 0.0488 ms | 0.0813 ms | 0.1653 ms |
| context planning | 1,000 | 0.1408 ms | 0.2421 ms | 0.7069 ms |

These are local synthetic measurements, not cross-machine guarantees.

## Summary/compaction decision

Choice A: deterministic bounded memory is sufficient for M5. It satisfies the
specified short follow-up and retained long-range topic-return cases with
negligible local work and no additional API cost. No `MemorySummarizer`, task or
model call is added. A future implementation can consume frozen snapshots and
commit explicitly derived, untrusted, provenance-bearing content behind its own
provider-neutral boundary if later evaluation justifies it.

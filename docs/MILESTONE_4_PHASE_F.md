# Milestone 4 Phase F — Model and latency benchmark

## Status

Complete on the target Windows machine on 2026-09-12. The sanitized raw result
is `docs/MILESTONE_4_MODEL_BENCHMARK.json`.

## Method

`benchmark-answers.bat` made eight non-sensitive stateless requests: both
candidates received the same four prompts covering a quick factual answer,
technical reasoning, speakable guidance and missing personal context. It used
the production prompt policy and async Interactions adapter with `store=false`,
no provider history and no tools.

The run used `google-genai` 2.23.0 and recorded first useful text, total latency,
aggregate usage and approximate paid Standard list cost. Human review considered
relevance, technical quality, speakability, unnecessary verbosity and the
missing-personal-context truth behavior.

## Results

| Candidate | Success | Median first useful text | Median total | Input | Output | Approx. paid Standard total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gemini-3.8-flash`, low | 4/4 | 3,399 ms | 5,533.5 ms | 878 | 537 | $0.00267225 |
| `gemini-3.5-flash-lite`, minimal | 4/4 | 1,723 ms | 2,693 ms | 878 | 267 | $0.0009309 |

On this corpus, Flash-Lite's median first text was approximately 49.3% faster,
median completion approximately 51.3% faster and estimated paid Standard total
approximately 65.2% lower. It was sufficiently relevant and technically useful,
more concise/speakable, and did not invent the missing employer achievement.

## Decision

The M4 default is:

```env
GEMINI_ANSWER_MODEL=gemini-3.5-flash-lite
GEMINI_ANSWER_THINKING_LEVEL=minimal
```

This best matched Mentara's M4 goal of low latency, sufficient answer quality
and reasonable cost. The choice remains environment-driven. The small benchmark
does not establish general model superiority and does not justify two-pass or
speculative generation.

## Runtime observations

The later short physical checkpoint observed first text between 2,454 ms and
7,406 ms depending on the request/provider conditions. Completed requests ranged
from 3,063 ms to 9,328 ms in the supplied observations. A Stop-during-generation
run showed first text at 4,360 ms and correctly omitted total completion latency
because it ended `cancelled`.

Meanwhile local M3 timing remained approximately 250–266 ms from transcript
final to turn and 0 ms from turn to detection, demonstrating that provider
generation did not block the microphone/conversation pipeline.

## Cost and privacy interpretation

The estimate uses the pricing basis recorded in the JSON and is not a bill.
Free-tier calls may be free, and provider data-use terms differ between free and
paid tiers. No sensitive prompt, credential, resume token or unrelated transcript
history was included in the benchmark result.

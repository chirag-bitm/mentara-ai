# Milestone 3 STT accuracy findings

## Scope

This document records the controlled Phase 0 product check. It is intentionally
separate from conversation-turn and assistance-detection correctness. The check
used one target-Windows microphone, one room and four phrases spoken twice per
profile; it is not a statistically rigorous WER/CER study.

## Profiles compared

| Profile | Language codes | Transcription mode |
| --- | --- | --- |
| A | automatic detection (empty value) | `VERBATIM` |
| B | `en-IN,hi-IN` | `VERBATIM` |
| C | the user's original effective safe configuration | its original mode |

The shared phrase set covered normal English, Indian English, Hinglish and
technical terminology (`Redis`, `FastAPI`, `WebSocket` and Gemini provider
rotation). Each profile produced eight final segments and stopped cleanly.

## Observations

| Profile | Observed result |
| --- | --- |
| A | English and deployment prompts were accurate. Hinglish was mostly accurate but rendered in Devanagari; nearby background speech was also captured. Technical wording was correct apart from compound-word formatting. |
| B | Hinglish stayed accurate in Latin script. Deployment and technical prompts were accurate apart from compound-word formatting. `cache` was repeatedly substituted with `cash` in both English-question runs. |
| C | All eight intended prompts preserved their content words. `cache` was correct twice, Hinglish stayed in Latin script, and technical prompts were correct apart from harmless spacing/capitalization. |

## Decision

- Retain profile C and `VERBATIM`.
- Do not add custom vocabulary based on this small corpus.
- Do not change server-side VAD or the verified audio/provider lifecycle in M3.
- Treat hybrid/client-assisted VAD as a separate measured latency experiment.
- Do not interpret formatting cleanup as better literal accuracy.

The comparison showed provider/run variation and justified preserving the
verified configuration rather than changing defaults. It does not establish
general multilingual transcription accuracy.

## Current provider facts used for the decision

Official Gemini documentation was rechecked on 2026-09-10. Empty language hints
enable automatic language detection/code-switching; `en-IN` and `hi-IN` are
supported hints; `VERBATIM` is literal while `SMART` intentionally transforms
speech; focused vocabulary biasing and hybrid/manual VAD are available; the
dedicated live-transcription session limit remains 10 minutes; and live word
timestamps/diarization are not supplied.

See `MILESTONE_3_PHASE_0.md` for the full preflight procedure and source links.

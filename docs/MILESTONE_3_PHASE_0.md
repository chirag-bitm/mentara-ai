# Milestone 3 Phase 0 — Preflight and STT accuracy gate

## Status

Complete. Repository preflight, automated M2 regression verification and the
controlled target-Windows physical-microphone comparison all passed.

No M3 runtime integration should change the verified M2 audio/STT boundary on
the basis of documentation alone.

## Repository findings

- `/ws/transcribe` accepts a session handshake before provider creation.
- `TranscriptionSession` owns the canonical `TranscriptAggregator` independently
  of browser sockets and provider generations.
- Canonical utterance IDs, revisions and transcript sequences are backend-owned.
- Snapshot replay reuses canonical identity and does not allocate new sequence
  values.
- The current active partial is already available through the transcript
  snapshot, which is the correct future input for predictive next-turn work.
- Provider rotation remains behind `STTProvider`; the route does not parse
  Gemini-specific messages.
- Continuity degradation is currently session/lifecycle state. M3 must preserve
  that fact in derived state without mutating canonical transcript history.
- No current component owns turn IDs, turn ordering, derived replay or question
  detection.

## Untouched baseline

Verified in the coding environment before M3 implementation:

- 61 backend tests passed.
- 8 frontend reducer/reconnection tests passed.
- frontend lint passed.
- frontend TypeScript/production build passed.

Environment note: this verification used Python 3.12 and Node.js 24. The
authoritative target-Windows M2 checkpoint used Python 3.11.9 and Node.js 22.
The backend emitted only two upstream deprecation warnings from the test-client
stack.

## Current official Gemini findings

Checked against the official Gemini documentation on 2026-09-10:

- `gemini-3.5-transcribe-live` emits interim and authoritative finalized input
  transcription events.
- Omitting `language_codes` or sending an empty list enables automatic language
  detection, including multilingual speech and code-switching.
- `en-IN` and `hi-IN` are supported BCP-47 language hints. Hints bias
  recognition; they are not a replacement for an A/B comparison.
- `VERBATIM` is the default and preserves fillers, repetitions and false starts.
- `SMART` performs disfluency removal, formatting and light cleanup. Cleaner
  output is therefore not evidence of better literal recognition.
- Live custom vocabulary supports up to 1,000 terms, with the documentation
  recommending a much smaller focused list for best results.
- Server-side automatic VAD is the default. The provider also supports hybrid
  VAD via client-detected silence plus `audioStreamEnd`, and manual VAD via
  explicit activity events when automatic VAD is disabled.
- Live transcription remains limited to 10 minutes per session.
- Live transcription does not support word-level timestamps or speaker
  diarization.

Sources:

- https://ai.google.dev/gemini-api/docs/live-api/live-transcribe
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe
- https://ai.google.dev/api/live
- https://ai.google.dev/gemini-api/docs/pricing

## Decision before the microphone comparison

- Keep the existing automatic-detection + `VERBATIM` default.
- Keep the existing 540-second rotation policy because the dedicated Live
  Transcribe documentation still states a 10-minute session limit.
- Do not add vocabulary hints yet.
- Do not add hybrid/client VAD in M3. It changes the verified audio/provider
  lifecycle and needs a separate measured latency experiment and rollback path.
- Keep STT accuracy work independent of turn/question correctness.

## Target-Windows comparison results

The same four phrases were spoken twice per profile. Each completed run emitted
eight final segments and stopped cleanly.

| Profile | Observed result |
| --- | --- |
| A | Both English questions were accurate. The deployment phrase was accurate, once rendered as `3:30`. Hinglish wording was mostly accurate but rendered in Devanagari; nearby background speech was also captured. The technical phrase was correct apart from compound-word formatting. |
| B | Hinglish was accurate and remained in Latin script. Both deployment phrases and both technical phrases were accurate apart from compound-word formatting. `cache` was repeatedly substituted with `cash` in both English-question runs. |
| C | All eight intended phrases preserved their content words. `cache` was correct twice, both Hinglish repetitions stayed in Latin script, and both technical repetitions were correct apart from harmless `FastAPI`/`WebSocket` spacing and capitalization. |

This is a small repeatable product check, not a statistically rigorous WER/CER
measurement. It shows normal run-to-run/provider variation and does not justify
changing the current profile to B.

Final decision:

- retain the original profile C;
- retain `VERBATIM`;
- do not add custom vocabulary based on this small corpus;
- do not change VAD or the verified audio/provider lifecycle during M3;
- revisit vocabulary and latency/VAD only as separate measured optimizations.

## Controlled comparison

Use the same microphone, room, speaking distance and pace for every profile.
Speak every phrase twice. Record obvious substitutions, dropped words, wrong
language/script, technical proper-name errors and finalization behavior. This is
a controlled product check, not a statistically rigorous WER/CER study.

Profiles:

| Profile | Language codes | Mode |
| --- | --- | --- |
| A | automatic detection | VERBATIM |
| B | `en-IN,hi-IN` | VERBATIM |
| C | original effective safe configuration | original effective mode |

Phrase set:

1. Normal English: `Can you explain why the cache expires after thirty seconds?`
2. Indian English: `Please schedule the deployment for Wednesday at half past three.`
3. Hinglish: `Agar Redis unavailable ho jaye, toh fallback kaise handle karoge?`
4. Technical terminology: `The FastAPI WebSocket reconnects after Gemini provider rotation.`

Observation sheet:

| Profile/run | Substitutions or drops | Wrong language/script | Technical terms | Finalization notes |
| --- | --- | --- | --- | --- |
| A/1 |  |  |  |  |
| A/2 |  |  |  |  |
| B/1 |  |  |  |  |
| B/2 |  |  |  |  |
| C/1 |  |  |  |  |
| C/2 |  |  |  |  |

## Safe Windows procedure

From the project-root VS Code PowerShell terminal:

```powershell
.\stt-accuracy.bat begin
.\stt-accuracy.bat A
```

Restart the backend, use the existing UI, and test the four phrases twice. Then
repeat with:

```powershell
.\stt-accuracy.bat B
```

and finally:

```powershell
.\stt-accuracy.bat C
```

After recording the results, restore the exact original safe values:

```powershell
.\stt-accuracy.bat finish
```

The helper changes only `GEMINI_LANGUAGE_CODES` and
`GEMINI_TRANSCRIPTION_MODE`. It stores only those two non-secret original values
in a git-ignored local file. It never reads or prints `GEMINI_API_KEY`.

## Phase 0 exit criteria

- Automated M2 baseline remains green.
- Current official provider semantics are recorded.
- All A/B/C observations are captured from the target microphone. **Passed.**
- Any default change is justified by the repeated observations.
- M3 domain contracts are reviewed before runtime integration.

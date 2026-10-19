# Mentara AI

Real-time conversation copilot.

## Current status

Milestones 1–5.5 are complete and verified. The final M5.5 target-Windows
provider, microphone, reconnect, correction and Stop checkpoint passed on
2026-10-18.

- M1 streams local microphone audio as signed little-endian PCM16, 16 kHz mono,
  in approximately 100 ms chunks through a provider-neutral STT boundary.
- M2 owns canonical transcript truth across bounded STT rotation and browser resume.
- M3 derives immutable turns and detects meaningful questions and requests.
- M4 creates at most one stable provider-neutral streamed answer per new positive
  assistance decision without blocking M1–M3.
- M5 adds backend-owned, bounded logical-session conversation memory and
  deterministic recent/relevant context selection without another model call.
- M5.5 adds an advisory provider-neutral next-turn side-car with stable
  active-turn identity, latest-input-wins cancellation, bounded context/cost,
  fake and stateless Gemini providers, additive replay-safe browser events and a
  separate minimal `Likely next` UI. Prediction never becomes transcript,
  memory, verified fact or answer truth.

```text
Microphone -> PCM16 -> STTProvider -> TranscriptAggregator
  -> CanonicalUtterance -> evolving ActiveConversationTurn
       -> bounded PredictionRuntime -> advisory Likely next UI
  -> finalized authoritative ConversationTurn
  -> logical-session ConversationMemory -> immutable MemorySnapshot
  -> AssistanceDetector -> stable AnswerRequest
  -> bounded ContextPlanner + AnswerPolicy -> AnswerProvider -> AnswerRuntime
  -> bounded serialized events -> idempotent transcript/answer UI
```

Authoritative references are `PROJECT_STATE.md`, `docs/ARCHITECTURE.md`,
`docs/FEATURE_ROADMAP.md`, `docs/MILESTONE_5_HANDOFF.md` and the current M5.5
handoff and phase records.

## Project structure

```text
mentara-ai/
├── backend/
│   ├── app/
│   │   ├── api/                    # WebSocket route and outbound writer
│   │   ├── core/                   # Validated settings and content-free logs
│   │   ├── schemas/                # Provider-neutral browser events
│   │   ├── services/stt/           # STT boundary and adapters
│   │   ├── services/transcript/    # Canonical transcript and logical session
│   │   ├── services/conversation/  # Turns and assistance detection
│   │   ├── services/memory/        # M5 memory, provenance and planner
│   │   ├── services/answer/        # Answer domain, runtime and adapters
│   │   ├── services/prediction/    # M5.5 side-car domain/runtime/providers
│   │   └── main.py
│   ├── tests/
│   ├── .env.example
│   ├── constraints.txt
│   └── requirements*.txt
├── frontend/
├── docs/
├── scripts/
├── setup.bat
├── configure-gemini.bat
├── benchmark-predictions.bat
├── m5-5-checkpoint.bat
├── m5-checkpoint.bat
├── start-backend.bat
├── start-frontend.bat
└── verify.bat
```

## Windows setup

Extract the archive so one folder directly contains `setup.bat`, `backend` and
`frontend`. Open PowerShell in that project root and run:

```powershell
.\setup.bat
```

This creates `backend\.venv`, installs backend/frontend packages and creates
missing local environment files without overwriting existing `.env` files.
Setup applies `backend/constraints.txt`, keeping the verified provider SDK at
`google-genai==2.23.0` without freezing platform-specific transitives.

Configure Gemini securely:

```powershell
.\configure-gemini.bat
```

The hidden prompt writes the key only to `backend\.env`. Never paste an API key
into chat, frontend files, logs or source control.

Relevant M5 defaults are:

```env
STT_PROVIDER=gemini
GEMINI_MODEL=gemini-3.5-transcribe-live
GEMINI_LANGUAGE_CODES=
GEMINI_TRANSCRIPTION_MODE=VERBATIM

CONVERSATION_ANALYSIS_ENABLED=true
CONVERSATION_TURN_MERGE_WINDOW_MS=250

MEMORY_CONTEXT_ENABLED=true
MEMORY_MAX_RETAINED_TURNS=256
MEMORY_MAX_RETAINED_TEXT_CHARS=160000
MEMORY_MAX_TURN_CHARS=4000
MEMORY_CONTEXT_RECENT_TURNS=4
MEMORY_CONTEXT_RELEVANT_TURNS=4

PREDICTION_ENABLED=true
PREDICTION_PROVIDER=gemini
GEMINI_PREDICTION_MODEL=gemini-3.5-flash-lite
GEMINI_PREDICTION_THINKING_LEVEL=minimal
PREDICTION_MIN_ACTIVE_CHARS=12
PREDICTION_MIN_LEXICAL_TOKENS=3
PREDICTION_LONG_PARTIAL_CHARS=48
PREDICTION_COALESCE_MS=350
PREDICTION_MIN_CALL_INTERVAL_MS=1200
PREDICTION_CANCELLED_ATTEMPT_COOLDOWN_MS=4000
PREDICTION_MAX_COMPATIBLE_EXTENSION_CHARS=96
PREDICTION_MAX_ATTEMPTS_PER_TURN=2
PREDICTION_MAX_CALLS_PER_SESSION=64
PREDICTION_PROVIDER_TIMEOUT_SECONDS=5
PREDICTION_MAX_CANDIDATES=3
PREDICTION_MAX_OUTPUT_TOKENS=512
PREDICTION_CONTEXT_RECENT_TURNS=2
PREDICTION_CONTEXT_RELEVANT_TURNS=2
PREDICTION_CONTEXT_MAX_TOTAL_CHARS=3200
PREDICTION_CONTEXT_MAX_ACTIVE_CHARS=1200
PREDICTION_CONTEXT_MAX_MEMORY_TURN_CHARS=800

ANSWER_GENERATION_ENABLED=true
ANSWER_PROVIDER=gemini
GEMINI_ANSWER_MODEL=gemini-3.5-flash-lite
GEMINI_ANSWER_THINKING_LEVEL=minimal
ANSWER_MAX_OUTPUT_TOKENS=512
ANSWER_GENERATION_TIMEOUT_SECONDS=20
ANSWER_CONTEXT_RECENT_TURNS=2
ANSWER_CONTEXT_MAX_TOTAL_CHARS=6000
ANSWER_CONTEXT_MAX_TURN_CHARS=2000
ANSWER_OUTBOUND_BUFFER_ITEMS=128
ANSWER_DELTA_MAX_COALESCED_CHARS=4096
```

`PREDICTION_MAX_COMPATIBLE_EXTENSION_CHARS=96` allows one already-running or
ready advisory attempt to survive only bounded, neutral completion of the same
lexical preface. Topic anchors and token order must remain intact; cosmetic
case/comma/hyphen churn, one terminal statement period, completion of the final
unfinished token and a long-stem inflection of a fixed general-framing term are
permitted. Direct questions, deleted/reordered topic words, corrections,
negation, pivots, unknown topic terms, internal sentence boundaries,
provenance/continuity changes, memory changes and finalization still invalidate
immediately. Set it to `0` to restore strict cancel-on-every-text-change
behavior without disabling the prediction side-car.

The M4 `ANSWER_CONTEXT_RECENT_TURNS` value remains the fallback when M5 memory
context is disabled. Empty STT language codes enable automatic detection.

## Start Mentara

Use two project-root PowerShell terminals.

Terminal 1:

```powershell
.\start-backend.bat
```

Terminal 2:

```powershell
.\start-frontend.bat
```

Open `http://localhost:3000` in Chrome.

## Automated verification

Stop development servers and run:

```powershell
.\verify.bat
```

The revised Phase J local gate is 445 backend tests and 28 frontend tests,
frontend lint, strict TypeScript and the production build. The final line is
`All automated checks passed.` Fake providers make this gate quota-free.

The offline synthetic memory evaluation can be rerun from the root with:

```powershell
backend\.venv\Scripts\python.exe scripts\evaluate_memory_context.py
```

The offline prediction and speculative-decision evaluations can be rerun with:

```powershell
backend\.venv\Scripts\python.exe scripts\evaluate_prediction.py
backend\.venv\Scripts\python.exe scripts\evaluate_speculative_decision.py
```

The target checkpoint uses `m5-5-checkpoint.bat`, which runs the automated gate,
at most four non-sensitive stateless prediction benchmark calls, and then starts
both servers. See `docs/MILESTONE_5_5_WINDOWS_CHECKPOINT.md`.
On the first provider failure it records a content-free reason and stops after
one paid request. The first 2026-09-15 Windows attempt returned zero of four
successful predictions. On 2026-09-19 the corrected benchmark passed 4/4 with
median 2,792.5 ms latency; the first live test did not show a ready prediction.
For the next short live check, use `m5-5-live-recheck.bat`: it verifies and
starts both servers without repeating the paid four-call benchmark.

## Advisory prediction behavior

- Prediction observes only backend-canonical M3 active-turn snapshots after M3
  processing; it never assembles turns or receives raw provider STT events.
- One stable prediction ID belongs to one logical active turn. Material changes
  increment input revision; only actual provider starts increment attempt.
- High-frequency partials replace one latest slot. Defaults coalesce 350 ms,
  enforce 1,200 ms between starts, cap two attempts per turn and 64 per logical
  session, and permit one provider task with a five-second timeout and no retry.
  A cancelled in-flight attempt defers another paid call in the same turn for
  4,000 ms; this bounds wasted calls under fast transcript corrections but
  does not guarantee a ready cloud prediction for a short turn.
- Context is read-only and bounded to 3,200 text characters: active turn first,
  then up to two recent and two relevant older untrusted memory turns.
- `TENTATIVE`/`STABLE` are operational readiness, not probability. Stable needs
  repeated candidate evidence, finalization wait and normal continuity.
- Correction, provenance/source/speaker/memory changes, new/finalized turns,
  degraded continuity, disconnect, Stop, reset, expiry and shutdown invalidate
  stale output. Equality checks discard late provider completions.
- Gemini prediction is a separate stateless Interactions call with structured
  output, `store=false`, no previous interaction, tools, Search or grounding.
- The UI reducer is separate from Answer History and persists no prediction.

## Memory and context behavior

- `ConversationMemory` belongs to the logical backend session, not a browser,
  STT connection, Gemini interaction, answer provider or frontend reducer.
- Only immutable finalized M3 turns are observed. Stable IDs deduplicate replay;
  cross-session input is rejected.
- Each commit increments `memory_revision` once. Frozen tuple-backed snapshots
  give future prediction a read-only input and cache-invalidating revision.
- Storage and answer context have independent validated hard bounds. Oldest-first
  eviction and sequence gaps explicitly degrade continuity.
- The source receives budget first, followed by four recent turns and up to four
  older turns ranked by normalized term overlap and recency.
- Short references use recent context; returning to a named older topic can
  select an older matching turn. A no-match result invents no context.
- M5 uses no embeddings, vector database, persistent store, summarizer or
  mandatory extra provider call.

## Answer behavior and domain separation

- `AnswerRequest` still derives from backend-owned `AssistanceDecision` and
  `ConversationTurn` objects with deterministic identity.
- Provider work still runs independently under logical-session `AnswerRuntime`;
  latest meaningful request wins.
- Browser disconnect preserves session/memory/answer state only through the
  existing 30-second resume lease. Replay makes no duplicate provider request.
- Answer-provider failure does not alter memory or healthy STT.
- Stop, reset, expiry and shutdown cancel owned work and logically release the
  session and memory.
- Generated answers remain separate Answer History. They never enter
  conversation memory automatically or become conversational truth.

## Trust, privacy and retention

Conversation memory is `VERBATIM_CONVERSATION` and `UNTRUSTED`. Remembering a
claim records only that somebody said it; it does not verify a profile, resume,
project or document fact. Transcript/memory JSON remains structurally separate
from trusted policy, so stored prompt injection cannot become system instruction,
expose secrets or enable tools.

M5 memory exists only in backend RAM. It is not written to database, disk,
`localStorage` or `sessionStorage`. Backend restart intentionally loses it.
Stop/reset/expiry/shutdown perform logical cleanup, not cryptographic RAM wiping.
Normal logs contain content-free timings, revisions, counts and sizes, never
transcript, memory or answer bodies.

The Gemini answer adapter remains stateless (`stream=true`, `store=false`) and
sends no provider history ID, tools, search, grounding, credentials, resume
tokens or unrelated full transcript history.

## Runtime rollback

- `PREDICTION_ENABLED=false` is the M5.5 rollback boundary. It constructs no
  prediction provider, runtime, task or event and restores exact M5 behavior.
- `MEMORY_CONTEXT_ENABLED=false` restores the verified M4 bounded context at one
  integration boundary.
- `ANSWER_GENERATION_ENABLED=false` preserves M1–M3 without answer calls.
- `CONVERSATION_ANALYSIS_ENABLED=false` restores the M2 transcript path.
- `GEMINI_ROTATION_ENABLED=false` restores one STT connection for diagnosis.

No database migration exists in M5.5.

## Known boundaries

- Transcript, memory and answers do not survive backend restart.
- Browser-gap audio is not buffered; degraded continuity is represented.
- STT accuracy is provider/audio dependent. Memory cannot retrieve an anchor
  that was not transcribed.
- Canonical transcript/finalized-turn replay and answer history retain their own
  current-session state independently of bounded M5 memory.
- Full topic/entity tracking, Conversation Radar, derived summaries, verified
  documents and durable history remain future work.
- Provider latency varies with network and service conditions.

## Next milestone

Milestone 5.5 is **COMPLETE AND VERIFIED**. The recommended next milestone is
M5.6 — Session Timeline / Q&A Navigator. Its previous/next/back-to-live controls
can consume the unchanged M4 Answer History while live M5.5 prediction remains
separate and ephemeral. Do not begin M5.6 or M6 from this closeout archive
without first reviewing `PROJECT_STATE.md`, `docs/FEATURE_ROADMAP.md` and
`docs/MILESTONE_5_5_HANDOFF.md`.

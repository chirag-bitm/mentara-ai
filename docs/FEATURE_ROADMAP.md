# Mentara — Canonical Feature Roadmap

**Purpose:** This file is the long-term product capability register for Mentara.  
It is intended to answer questions such as “Are we still planning this feature?”, “Which milestone owns it?”, “What does it depend on?”, and “Can it be added without rewriting existing layers?”

**Rules**
- The repository implementation and milestone handoffs remain authoritative for what is actually complete.
- This roadmap is authoritative for planned product capabilities and their intended architectural hooks.
- New features may be added later, but they must be assigned a stable feature ID, dependencies, target milestone, and an architecture hook before implementation.
- Do not mark a feature COMPLETE until its milestone handoff and repository verification support that status.
- Never implement security/proctoring bypass. “Share-safe/private overlay” means legitimate OS-supported capture exclusion/presentation privacy only.
- Preserve provider-neutral boundaries wherever practical.

## Status values

- **COMPLETE** — implemented and verified.
- **IN PROGRESS** — current milestone work.
- **FOUNDATION READY** — prerequisite architecture exists; feature itself is not complete.
- **PLANNED** — committed to roadmap, not yet implemented.
- **CANDIDATE** — useful idea under consideration; not committed yet.
- **DEFERRED** — intentionally postponed pending evidence/dependency.

## Current milestone state

- M1 — Audio + Streaming STT: **COMPLETE**
- M2 — Canonical Transcript Engine + Realtime Resilience: **COMPLETE**
- M3 — Turn + Meaningful Question / Assistance Detection: **COMPLETE**
- M4 — Provider-Neutral Answer Engine + Low-Latency Streaming: **COMPLETE**
- M5 — Session Memory + Context Orchestration: **COMPLETE**
- M5.5 — Predictive Next-Turn + Speculative Context Prefetch: **COMPLETE**
- M5.6 — Session Timeline / Q&A Navigator: **PLANNED**
- M6 — Profile / Documents / Truth Lock: **PLANNED**
- M7+ — Desktop, System Audio, Screen Intelligence, Coding, Modes, Multi-user Productization: **PLANNED**

## Repository reconciliation record

- **2026-09-13 / M5 Phase 0:** Compared every existing status against the M4
  repository, `PROJECT_STATE.md`, architecture documentation, milestone
  handoffs, M4 phase records, automated tests and the recorded model benchmark.
- The M1–M4 `COMPLETE` claims and existing `FOUNDATION READY` claims are
  supported by implementation and verification evidence. No M5 runtime feature
  is marked complete during Phase 0.
- `F-013` had an unrelated dependency on `F-071` (desktop compact/discreet
  mode). Its dependency is corrected to the implemented provider-neutral STT
  boundary plus the future profile and document sources (`F-003,F-056,F-061`).
  Its ID, status and target milestone are unchanged.
- `F-141` is advanced only to `FOUNDATION READY`: Windows setup now applies a
  narrow constraint for the compatibility-sensitive `google-genai` SDK version
  used by the verified M4 benchmark. A fully locked cross-platform backend
  environment remains later production work.
- **2026-09-13 / M5 closeout:** `F-036` through `F-041` are advanced to
  `COMPLETE` only after domain, lifecycle, context, privacy, rollback,
  long-session and target-Windows verification. `F-049` advances to
  `FOUNDATION READY` because bounded deterministic topic terms exist for
  retrieval, while full topic/entity tracking and Conversation Radar remain
  future work. `F-042` remains deferred: evaluation did not justify a summary
  model call or compaction lifecycle in M5.
- **2026-09-13 / M5.5 Phase 0:** The complete verified M5 archive was
  re-inspected and the full M1–M5 regression/evaluation gate passed. M5.5 is
  now `IN PROGRESS`, but `F-043`, `F-044`, `F-046` and all adjacent feature
  rows remain `PLANNED` until implementation and verification exist. No feature
  is advanced merely from the architecture foundation. Prediction remains a
  provider-neutral, non-authoritative, RAM-only side-car; M5.6 Answer History
  and future M6 verified-context provenance remain separate.
- **2026-09-13 / M5.5 Phase A:** Provider-neutral immutable domain, stable
  prediction identity/material fingerprints, revision/attempt provenance,
  operational readiness/invalidation enums, bounded output/context contracts,
  provider protocol and `PREDICTION_ENABLED` configuration are implemented and
  covered by the 275-test backend gate. There is still no runtime/provider/UI,
  so `F-043`, `F-044`, `F-046`, `F-050`, `F-145` and `F-147` remain `PLANNED`.
- **2026-09-13 / M5.5 Phase B:** The logical-session prediction lifecycle,
  non-blocking canonical-M3 active-turn handoff, latest-input-wins coalescing
  slot, equality-gated stale rejection, hard turn/session attempt ceilings and
  disconnect/Stop/reset/expiry/shutdown cleanup are implemented and covered by
  the 295-test backend gate. Production construction, planner, trigger policy,
  fake/cloud provider and browser surface remain absent, so `F-043`, `F-044`,
  `F-046`, `F-050`, `F-145` and `F-147` remain `PLANNED`.
- **2026-09-13 / M5.5 Phase C:** Deterministic local trigger/throttle policy,
  worker-only bounded context planning over immutable active-turn/memory
  snapshots, strict memory-revision validation and context/provenance bounds are
  implemented and covered by the 341-test backend gate. Production construction,
  fake/cloud provider and browser surface remain absent, so `F-043`, `F-044`,
  `F-046`, `F-050`, `F-145` and `F-147` remain `PLANNED`; `F-045` is unchanged.
- **2026-09-13 / M5.5 Phases D–F:** Deterministic fake-provider races,
  provider-neutral request/prompt composition, additive browser events,
  idempotent live prediction UI and the separate stateless Gemini Interactions
  adapter are implemented. The constrained SDK is unchanged. Production
  prediction now exists behind `PREDICTION_ENABLED`; false constructs no
  provider/runtime/task/event. Core rows advance only to `IN PROGRESS` pending
  the required target-Windows/provider checkpoint.
- **2026-09-13 / M5.5 Phases G–H:** The named 11-case deterministic corpus
  passes trigger/context/lifecycle/stale/cost-proxy checks, explicitly without a
  general model-accuracy claim. The strict speculative-answer gate does not
  establish safe net benefit, so no production speculative path or flag is
  added and `F-045` remains `PLANNED`.
- **2026-09-14 / M5.5 Phase I:** Recovery/privacy/stress verification passes 381
  backend tests and 28 frontend tests plus lint, strict TypeScript, production
  build and all local evaluations. Predictor failure cannot interrupt canonical
  turns/answers; reconnect replays no prediction and creates no paid call. Phase
  J is still required before any M5.5 feature becomes `COMPLETE`.
- **2026-10-18 / M5.5 closeout:** The final local gate passes 445 backend
  tests, 28 frontend tests, lint, strict TypeScript, production build and the
  M5 memory, M5.5 prediction and speculative-decision evaluations. The target
  Windows run produced a three-candidate real prediction in 3,593 ms, ready
  2,344 ms before turn finalization, preserved across seven compatible
  extensions and cleared on a material correction. Refresh created no replayed
  provider call, authoritative answers remained one-per-request, Stop released
  the microphone and no unhandled backend error occurred. `F-043`, `F-044`,
  `F-046` and the minimal UI `F-147` advance to `COMPLETE`. `F-050` and `F-145`
  remain `FOUNDATION READY`; actual answer latency was not reduced and full
  topic-transition tracking was not implemented. `F-045`, `F-047`, `F-146`,
  `F-148`, `F-032` and `F-034` remain planned.

---

# A. Realtime audio, STT and conversation foundation

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-001 | Browser microphone capture | COMPLETE | M1 | — | Web Audio API |
| F-002 | PCM16 16 kHz mono streaming | COMPLETE | M1 | F-001 | Stable audio contract |
| F-003 | Provider-neutral STT abstraction | COMPLETE | M1 | F-002 | `STTProvider` |
| F-004 | Gemini live transcription adapter | COMPLETE | M1 | F-003 | Replaceable provider adapter |
| F-005 | Partial + final transcript events | COMPLETE | M1 | F-004 | `transcript.partial/final` |
| F-006 | Canonical transcript engine | COMPLETE | M2 | F-005 | Backend-owned canonical truth |
| F-007 | Stable utterance IDs/revisions/sequences | COMPLETE | M2 | F-006 | Canonical provenance |
| F-008 | Browser resume without duplicate transcript | COMPLETE | M2 | F-006 | Logical session registry |
| F-009 | Provider rotation / long logical sessions | COMPLETE | M2 | F-003,F-006 | Mentara session != provider connection |
| F-010 | 60–120+ minute logical sessions | FOUNDATION READY | M2+ | F-009 | Requires later soak/production validation |
| F-011 | Indian-English / Hinglish STT tuning | FOUNDATION READY | M3+ | F-003 | Controlled profile; revisit from evidence |
| F-012 | Multilingual/code-switch STT | PLANNED | Later STT hardening | F-003 | Provider-neutral language config |
| F-013 | Technical vocabulary hints from profile/docs | PLANNED | M6+ | F-003,F-056,F-061 | Profile-derived STT hints; never route-specific hacks |
| F-014 | Word-level timestamps where provider supports them | DEFERRED | Provider hardening | F-003 | Optional capability; never fabricate |
| F-015 | Speaker/source separation | FOUNDATION READY | M8 | F-003 | Mic=`local_user`, system=`remote_speaker` |
| F-016 | Multi-speaker diarization | DEFERRED | Later meeting hardening | F-015 | Only if product need justifies it |

# B. Turn intelligence and answer trigger

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-017 | Conversation turn assembly | COMPLETE | M3 | F-006 | `ConversationTurnEngine` |
| F-018 | Stable turn identity + provenance | COMPLETE | M3 | F-017 | Deterministic IDs |
| F-019 | Meaningful question/request detection | COMPLETE | M3 | F-017 | Replaceable `AssistanceDetector` |
| F-020 | Request detection without `?` | COMPLETE | M3 | F-019 | Questions, requests, imperatives |
| F-021 | Hinglish assistance cues | FOUNDATION READY | M3+ | F-019 | Initial focused heuristic |
| F-022 | Better implicit/multilingual assistance classifier | PLANNED | Later detection hardening | F-019 | Local/small model can replace heuristic |
| F-023 | Adaptive semantic end-of-turn detection | DEFERRED | Latency hardening | F-017 | Replace/tune static merge policy only from evidence |

# C. Answer engine

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-024 | Provider-neutral answer generation | COMPLETE | M4 | F-019 | `AnswerProvider` |
| F-025 | Low-latency streamed answers | COMPLETE | M4 | F-024 | Independent `AnswerRuntime` |
| F-026 | Stable answer identity/lifecycle | COMPLETE | M4 | F-024 | Replay-safe |
| F-027 | Latest-request-wins supersession | COMPLETE | M4 | F-025 | Explicit cancellation |
| F-028 | Browser refresh without duplicate paid request | COMPLETE | M4 | F-026 | Logical-session-owned answers |
| F-029 | Bounded/serialized outbound event writer | COMPLETE | M4 | F-025 | Backpressure-aware |
| F-030 | Stateless provider calls / no provider-owned memory | COMPLETE | M4 | F-024 | Gemini `store=false` |
| F-031 | Base anti-hallucination policy for missing personal facts | COMPLETE | M4 | F-024 | Full Truth Lock comes later |
| F-032 | Progressive quick → deep answer | PLANNED | M5.5/M6+ | F-025,F-050 | Must be evidence-driven, not double every call |
| F-033 | Answer length modes: Quick / Normal / Deep | PLANNED | Later UX/Policy | F-024 | `AnswerPolicy` |
| F-034 | Adaptive Speakability Engine | PLANNED | After M5.5 / M7 | F-024,F-050 | Optimize answer for spoken time/context |
| F-035 | Regenerate/manual answer controls | PLANNED | Later answer UX | F-026 | Explicit generation attempt/version |

# D. Memory, context and prediction

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-036 | Logical-session conversation memory | COMPLETE | M5 | F-017,F-024 | Backend-owned `ConversationMemory`; in RAM only |
| F-037 | Bounded recent-turn context | COMPLETE | M5 | F-036 | Separate hard storage/context bounds |
| F-038 | Relevant older-turn retrieval | COMPLETE | M5 | F-036 | Deterministic local normalized-term overlap |
| F-039 | Follow-up/reference resolution | COMPLETE | M5 | F-037,F-038 | Recent short references + named topic return |
| F-040 | Memory provenance/trust model | COMPLETE | M5 | F-036 | Conversation/derived remain untrusted; verified source reserved |
| F-041 | Memory snapshot + revision | COMPLETE | M5 | F-036 | Frozen read-only hook for prediction |
| F-042 | Rolling/structured summary | DEFERRED | M5 or later | F-036 | Only if measured need justifies extra model lifecycle |
| F-043 | Predictive Next-Turn Engine | COMPLETE | M5.5 | F-041,F-017 | Provider-neutral side-car verified locally and on target Windows |
| F-044 | Speculative context prefetch | COMPLETE | M5.5 | F-043,F-038 | Bounded read-only active-turn + memory planner verified |
| F-045 | Speculative model/prompt warming | PLANNED | M5.5+ | F-043,F-024 | Cost-controlled; prediction never authoritative |
| F-046 | Prediction readiness + cancellation/invalidation | COMPLETE | M5.5 | F-043 | Operational readiness, bounded compatibility and stale cancellation verified |
| F-047 | Conversation Radar / Live Brain | PLANNED | M5.5/M7 | F-041,F-043 | Current topic, open threads, likely follow-ups, missing context |
| F-048 | Context Packs | PLANNED | M6+ | F-040,F-071 | User-selected bundles of profile/docs/task context |
| F-049 | Topic/entity tracking | FOUNDATION READY | M5/M6 | F-036 | Bounded local terms support retrieval; full tracking/radar remains planned |
| F-050 | End-of-speech → first-useful-token optimization | FOUNDATION READY | Continuous/M5.5 | F-023,F-043,F-025 | Prediction lead-time measured; actual answer latency not yet improved |

# E. Session timeline and navigation

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-051 | Session Timeline / Q&A Navigator | PLANNED | M5.6 | F-026,F-036 | Browse previous Q&A while live transcript continues |
| F-052 | Previous/next Q&A keyboard navigation | PLANNED | M5.6/M7 | F-051 | e.g. previous/next/back-to-live |
| F-053 | Return-to-live mode | PLANNED | M5.6 | F-051 | Browsing history must never pause STT |
| F-054 | Search/filter current-session Q&A | PLANNED | Later timeline UX | F-051 | Bounded current-session index |
| F-055 | Answer/history replay after browser refresh | FOUNDATION READY | M4/M5.6 | F-028,F-051 | UI navigation layer still needed |

# F. Profile, documents and Truth Lock

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-056 | User profile context | PLANNED | M6 | F-040 | Verified/authorized context source |
| F-057 | Resume upload + parsing | PLANNED | M6 | F-056 | Provenance-bearing facts |
| F-058 | Project notes / behavioral stories | PLANNED | M6 | F-056 | User-controlled |
| F-059 | Job description context | PLANNED | M6 | F-056 | Task-specific |
| F-060 | Company/interview notes | PLANNED | M6 | F-056 | Context source |
| F-061 | General document upload | PLANNED | M6 | F-056 | Authorized docs only |
| F-062 | Truth Lock | PLANNED | M6 | F-040,F-056 | Prevent unsupported personal claims |
| F-063 | Live Truth Ledger / provenance labels | PLANNED | M6 | F-062 | Verified doc/profile vs conversation vs general knowledge vs unknown |
| F-064 | Verified / Balanced / Creative response modes | PLANNED | M6+ | F-062 | Truth-policy modes |
| F-065 | Document-aware retrieval / RAG | PLANNED | M6+ | F-061 | Provider-neutral retrieval boundary |
| F-066 | Automatic important-term extraction for STT hints | PLANNED | M6+ | F-057,F-013 | Proper nouns / technologies |

# G. Desktop overlay and UX

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-067 | Tauri desktop app | PLANNED | M7 | F-024 | Windows first |
| F-068 | Always-on-top floating overlay | PLANNED | M7 | F-067 | Compact/expanded |
| F-069 | Drag / resize / collapse / expand | PLANNED | M7 | F-068 | UX |
| F-070 | Global show/hide hotkeys | PLANNED | M7 | F-067 | User-controlled |
| F-071 | Compact / discreet mode | PLANNED | M7 | F-068 | Privacy-oriented UX, not security evasion |
| F-072 | Opacity / click-through where appropriate | PLANNED | M7 | F-068 | Authorized normal desktop use |
| F-073 | Multi-monitor awareness | PLANNED | M7 | F-067 | Overlay placement/context |
| F-074 | Share-safe presentation/privacy mode | PLANNED | M7 | F-067 | Legitimate OS-supported capture exclusion only |
| F-075 | Capture-exclusion diagnostic/status | PLANNED | M7 | F-074 | Never promise universal invisibility |
| F-076 | Windows first, macOS later | PLANNED | M7+ | F-067 | Platform abstraction |
| F-077 | Browser-only lightweight edition | CANDIDATE | Later | F-024 | Reduced feature set |

# H. System audio and multimodal screen intelligence

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-078 | Authorized Windows system audio capture | PLANNED | M8 | F-067,F-015 | WASAPI loopback |
| F-079 | Authorized macOS system audio capture | PLANNED | M8+ | F-067,F-015 | Approved native APIs |
| F-080 | Separate local vs remote audio streams | PLANNED | M8 | F-078 | Stronger speaker semantics |
| F-081 | Explicit screenshot capture | PLANNED | M9 | F-067 | User-authorized |
| F-082 | Selected-region capture | PLANNED | M9 | F-081 | User-authorized |
| F-083 | Active-window context | PLANNED | M9 | F-081 | User-authorized |
| F-084 | Screen/image understanding | PLANNED | M9 | F-081 | Provider-neutral vision context |
| F-085 | Audio + screen fused reasoning | PLANNED | M9 | F-080,F-084 | “optimize this” + visible code |
| F-086 | OCR fallback where needed | PLANNED | M9 | F-084 | Prefer vision where possible |
| F-087 | Screen-context privacy controls | PLANNED | M9 | F-081 | Explicit capture/retention controls |

# I. Coding workspace and authorized actions

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-088 | Coding problem understanding | PLANNED | M10 | F-024,F-084 | Mode/router |
| F-089 | Approach + code + complexity + dry run | PLANNED | M10 | F-088 | Coding answer strategy |
| F-090 | Built-in Monaco coding workspace | PLANNED | M10 | F-067,F-088 | Safe primary action target |
| F-091 | Progressive/line-by-line code rendering | PLANNED | M10 | F-090 | Human-readable streaming |
| F-092 | Authorized IDE integration | PLANNED | M10+ | F-090 | Explicit extension/integration |
| F-093 | Practice-only auto-selection/action support | PLANNED | M11 | F-090 | Mentara/authorized UI only; no proctored bypass |
| F-094 | Code debugging/explanation mode | PLANNED | M10 | F-088 | Screen/code context |
| F-095 | System design workspace | PLANNED | M10/M12 | F-024,F-036 | Structured answer strategy |

# J. Learning, meeting, presentation and business modes

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-096 | Learning/Lecture mode | PLANNED | M11/M12 | F-036,F-024 | Live notes/explanations |
| F-097 | Flashcards/quizzes from session | PLANNED | M11 | F-096 | Practice UI |
| F-098 | Meeting mode | PLANNED | M12 | F-036,F-080 | Conversation intelligence |
| F-099 | Meeting decisions/action items | PLANNED | M12 | F-098 | Structured extraction |
| F-100 | Meeting summary / follow-up | PLANNED | M12 | F-098 | Post-session |
| F-101 | Presentation / Script mode | PLANNED | M12 | F-034 | Speakable scripts |
| F-102 | Sales / Call mode | PLANNED | M12 | F-036,F-065 | Objection/product context |
| F-103 | Customer-support knowledge mode | PLANNED | M12 | F-065 | Knowledge-grounded responses |
| F-104 | Interview practice mode | PLANNED | M12 | F-056,F-034 | Legitimate practice/coaching |
| F-105 | Resume / Project interview mode | PLANNED | M12 | F-057,F-058 | Personalized truthful responses |
| F-106 | System Design mode | PLANNED | M12 | F-095 | Structured design guidance |

# K. Local/free mode and provider routing

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-107 | Local Whisper/faster-whisper STT | PLANNED | M14 | F-003 | Provider adapter |
| F-108 | Local LLM / Ollama answer provider | PLANNED | M14 | F-024 | AnswerProvider adapter |
| F-109 | Local VAD | PLANNED | M14 | F-002 | Optional Silero/local boundary |
| F-110 | Cloud fast mode | FOUNDATION READY | M4 | F-024 | Current cloud provider |
| F-111 | Dynamic provider routing | PLANNED | M14/M15 | F-003,F-024 | Cost/latency/privacy policy |
| F-112 | Provider fallback | PLANNED | M14/M15 | F-111 | Bounded and explicit |
| F-113 | Cost-aware model selection | PLANNED | M14/M15 | F-111 | Per-task/provider policy |
| F-114 | Privacy-aware model selection | PLANNED | M14/M15 | F-111 | Local vs cloud based on policy |

# L. Multi-user product, access and admin

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-115 | User authentication | PLANNED | M13 | — | Product identity |
| F-116 | User settings/profile | PLANNED | M13 | F-115 | Account-level |
| F-117 | Session history | PLANNED | M13 | F-115 | Durable storage |
| F-118 | Persistent database | PLANNED | M13 | F-115 | PostgreSQL or justified equivalent |
| F-119 | Temporary invite URLs | PLANNED | M14+ | F-115 | Signed/expiring |
| F-120 | Single-use / expiry-limited access | PLANNED | M14+ | F-119 | Beta distribution |
| F-121 | Per-user feature flags | PLANNED | M14+ | F-115 | Entitlements |
| F-122 | Time/minute quotas | PLANNED | M14+ | F-115 | Usage control |
| F-123 | Device limits | PLANNED | M14+ | F-115 | Optional |
| F-124 | Admin dashboard | PLANNED | M14+ | F-115 | Users/invites/usage/errors |
| F-125 | Remote revoke access | PLANNED | M14+ | F-124 | Admin control |
| F-126 | Usage/cost/latency analytics | PLANNED | M14+ | F-124 | Privacy-safe telemetry |
| F-127 | Feature usage analytics | PLANNED | M14+ | F-124 | Product analytics |
| F-128 | Permission-based support screen sharing | PLANNED | M14+ | F-115 | Explicit opt-in/visible indicator |
| F-129 | Support diagnostics | PLANNED | M14+ | F-128 | User-controlled |
| F-130 | Plans/billing/subscriptions | PLANNED | M15 | F-115,F-126 | Only after product validation |
| F-131 | Team/workspace plans | CANDIDATE | M15+ | F-115 | Shared org context |
| F-132 | Enterprise controls / SSO/private deployment | CANDIDATE | M15+ | F-115 | Product maturity dependent |

# M. Production, privacy and reliability

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-133 | Explicit retention/deletion settings | PLANNED | M13/M15 | F-118 | User-controlled |
| F-134 | Encryption/persistence hardening | PLANNED | M15 | F-118 | Production |
| F-135 | Production monitoring/observability | PLANNED | M15 | — | No sensitive content in logs |
| F-136 | Rate limiting / abuse protection | PLANNED | M15 | F-115 | Production |
| F-137 | Automated update mechanism | PLANNED | M15 | F-067 | Desktop updater |
| F-138 | Secure secret management | PLANNED | M15 | — | Backend/desktop secrets |
| F-139 | Multi-worker/session coordination | PLANNED | M15 | F-118 | If scaling requires |
| F-140 | Disaster/recovery/rollback discipline | FOUNDATION READY | Continuous | — | Milestone checkpoints |
| F-141 | Reproducible dependency locking/constraints | FOUNDATION READY | M5/M15 | — | Verified provider SDK constrained; full cross-platform lock remains later work |
| F-142 | Cost dashboards / per-user cost attribution | PLANNED | M14/M15 | F-126 | Product economics |

# N. Candidate future enhancements discussed

| ID | Feature | Status | Intended milestone | Depends on | Architecture hook / notes |
|---|---|---|---|---|---|
| F-143 | Live translation | CANDIDATE | Future | F-012,F-024 | Add only if product demand justifies |
| F-144 | Emotion/tone/context signals | CANDIDATE | Future | F-036 | Never infer sensitive traits |
| F-145 | Automatic topic-transition detection | FOUNDATION READY | M5/M5.5 | F-049 | Material topic correction/change invalidation exists; full topic model absent |
| F-146 | Open-thread tracking | PLANNED | M5.5 | F-047 | Unresolved questions/topics |
| F-147 | Suggested likely next questions UI | COMPLETE | M5.5/M7 | F-043 | Minimal replay-safe advisory UI verified; full Radar remains F-047 |
| F-148 | “Go deeper” branches under live answer | PLANNED | M5.5/M7 | F-032,F-034 | Failure/consistency/etc. |
| F-149 | Selected-context pinning by user | CANDIDATE | M6/M7 | F-048 | Keep important context active |
| F-150 | Session export / notes export | CANDIDATE | M13+ | F-117 | Privacy-controlled |

---

# Milestone mapping summary

## M5 — Session Memory + Context
Primary IDs: F-036 to F-042, F-049, F-141 evaluation.

## M5.5 — Predictive Next-Turn
Primary IDs: F-043 to F-050, F-145 to F-148.

## M5.6 — Session Timeline / Q&A Navigator
Primary IDs: F-051 to F-055.

## M6 — Profile/Documents/Truth Lock
Primary IDs: F-056 to F-066, F-048.

## M7 — Desktop Overlay
Primary IDs: F-067 to F-077 plus Q&A Navigator/Conversation Radar overlay integration.

## M8 — System Audio
Primary IDs: F-078 to F-080.

## M9 — Screen Intelligence
Primary IDs: F-081 to F-087.

## M10 — Coding Workspace
Primary IDs: F-088 to F-095.

## M11/M12 — Learning + Specialized Modes
Primary IDs: F-096 to F-106.

## M13+ — Users, History, Productization
Primary IDs: F-115 onward.

## M14/M15 — Local/Free Mode + Production
Primary IDs: F-107 onward plus production hardening.

---

# Roadmap governance

Before starting any feature-focused milestone:

1. Check this file for the feature ID/status.
2. Compare against `PROJECT_STATE.md` and the latest milestone handoff.
3. Confirm dependencies are complete.
4. Confirm stable contracts that must not change.
5. Confirm migration/backward-compatibility/rollback implications.
6. Confirm effects on later feature IDs.
7. Update this roadmap only after an architectural decision is approved.
8. Do not silently delete or forget planned features.
9. If a new feature is proposed, assign a new stable ID rather than renumbering old entries.
10. If a feature moves milestones, update only its target/status/dependency fields; preserve its ID.

# Important product boundary

Mentara may support legitimate, user-controlled floating overlays, presentation privacy/capture exclusion where operating systems explicitly support it, and authorized support/screen-sharing workflows.

Mentara must not implement bypass/evasion of secure browsers, proctoring, monitoring or protected environments.

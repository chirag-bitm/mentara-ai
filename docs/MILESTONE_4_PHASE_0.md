# Milestone 4 Phase 0 — Provider and API research

## Status

Complete as of 2026-09-12 using current official Google documentation and the
installed `google-genai` Python SDK surface. The real-provider benchmark was
subsequently completed in Phase F.

## Confirmed current facts

- Google describes the Gemini Interactions API as generally available and the
  recommended API for new projects. `generateContent` remains supported but is
  now described as legacy.
- Interactions streaming is delivered as server-sent events. Text arrives in
  `step.delta` events and terminal usage is included in
  `interaction.completed`.
- Interactions default to `store=true`. Mentara explicitly sends `store=false`
  and does not use `previous_interaction_id`; provider state is not Mentara
  memory or identity.
- The current official Python SDK requirement for Interactions is
  `google-genai>=2.3.0`. M4 uses its true async client and async stream.
- `gemini-3.8-flash` and `gemini-3.5-flash-lite` are stable supported
  Interactions models.
- Gemini 3.8 Flash supports low, medium and high thinking; medium is the default
  and minimal is invalid. Gemini 3.5 Flash-Lite supports minimal, low, medium
  and high; minimal is the default.
- Current paid Standard list prices used only for the benchmark estimate are:
  Gemini 3.8 Flash at the introductory $0.75/M input and $3.75/M output through
  2026-12-31, and Gemini 3.5 Flash-Lite at $0.30/M input and $2.50/M output.
  Output pricing includes thinking tokens.
- Free-tier content may be used to improve Google products; paid-tier content is
  documented as not used for that purpose. Provider terms must be reviewed for
  the actual project tier.

## Sources

- <https://ai.google.dev/gemini-api/docs/interactions-overview>
- <https://ai.google.dev/gemini-api/docs/get-started>
- <https://ai.google.dev/gemini-api/docs/thinking>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite>
- <https://ai.google.dev/gemini-api/docs/pricing>

## M4 consequences

- Use Interactions through the async SDK.
- Explicitly send `store=false` on every request.
- Never pass provider interaction IDs into Mentara domain state.
- Do not declare tools, search, grounding or background execution.
- Keep the answer model and thinking level environment-driven.
- Compare 3.8 Flash/low against 3.5 Flash-Lite/minimal with the same small,
  non-sensitive prompt corpus before selecting the final default.

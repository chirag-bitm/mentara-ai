# Milestone 5.5 Phase F — Gemini prediction adapter

Date: 2026-09-13

Status: IMPLEMENTATION COMPLETE; controlled real-provider benchmark pending the
target environment/private backend configuration in Phase J.

## Provider decision

Current official Gemini documentation was rechecked before adapter work. The
implementation uses the Gemini Interactions API, stateless `store=false`,
structured JSON through `response_format`, no `previous_interaction_id`, no
tools, no Search and no grounding. The starting model is
`gemini-3.5-flash-lite` with `thinking_level=minimal` because this role needs
small, low-cost, high-throughput output rather than answer-grade reasoning.

The repository remains constrained to `google-genai==2.23.0`. Its installed
request and response types were inspected and support `interactions.create`,
`response_format`, `store`, `system_instruction`, generation configuration,
`output_text` and usage fields. No SDK upgrade or dependency change was needed.

## Adapter behavior

`GeminiPredictionProvider` is separate from `GeminiAnswerProvider`. It performs
one non-streaming Interaction per accepted runtime attempt, requests at most 512
output tokens and supplies the exact operational candidate cap in an
extra-forbidden structured schema. It maps auth,
configuration, rate-limit, timeout, transport, provider-server, malformed and
unknown failures to sanitized provider-neutral errors. Cancellation propagates.
After the first Windows benchmark failed, fixed status labels were added to
non-completion errors. They do not expose provider steps or response bodies.
The 512-token cap is a hard upper limit, not an expectation of usage; Google's
`max_output_tokens` includes thought tokens, so the initial 128-token cap
could truncate the structured response. The actual cause remains unconfirmed
until the corrected private-provider checkpoint is run.

The backend-only Gemini key is passed only to the SDK client. Prompts contain a
bounded active turn plus selected recent/relevant untrusted memory. They never
contain the entire session transcript, Answer History, credentials, resume
tokens, environment values or unrelated state.

## Production wiring and rollback

When `PREDICTION_ENABLED=true`, a new logical session may construct the
prediction provider/executor/runtime. Configuration failure disables only the
optional prediction side-car. When false, no provider is constructed, no
runtime/task exists and no prediction browser event is emitted; verified M5
behavior is unchanged.

## Verification

Adapter tests verify exact request shape, structured parsing, output
bounds, usage, cancellation, closing and safe error mapping. Enabled/disabled
WebSocket integration is covered by the full 381-test backend gate. A four-call
non-sensitive benchmark helper is ready as `benchmark-predictions.bat`; no key
is present in this workspace, so fabricated real latency/token results are not
recorded. The first real run returned zero completed predictions across four
calls; Phase J's correction will probe once and stop on failure.

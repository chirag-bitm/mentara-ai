# Milestone 4 Phase E — Gemini answer adapter

## Status

Complete. Adapter/fake-SDK protocol tests, a minimal stateless real-provider
request and the controlled eight-call benchmark passed.

## Adapter contract

- Uses `google-genai` 2.x and `client.aio.interactions.create`.
- Streams asynchronously; no synchronous network iterator runs in the STT
  WebSocket coroutine.
- Sends production policy as `system_instruction` and serialized transcript
  context as a separate untrusted `input`.
- Explicitly sends `stream=true` and `store=false`.
- Explicitly disables SDK HTTP retries. M4 makes one provider attempt per
  positive detection; it does not silently replay a request after a transient
  status or after any text may have become visible.
- Does not send `previous_interaction_id`, tools, search, grounding, environment
  data, resume tokens or unrelated transcript history.
- Converts only text deltas and terminal aggregate usage into provider-neutral
  events. Thought signatures and normal lifecycle markers remain inside the
  adapter.
- Closes both the SSE stream and async SDK client on completion, failure or
  cancellation.

## Error mapping

The adapter sanitizes configuration/authentication, quota/rate-limit, transient
network, provider/server, timeout, cancellation, safety/content and unknown
failures. Unsupported or discontinuous streams become `malformed_stream` in the
runtime. Raw provider payloads and credential-bearing exception text are not
sent to the browser or normal logs.

## Dependency

`google-genai>=2.3,<3.0` is a direct runtime dependency. `anyio>=4.10,<5.0` is
also direct because shielded WebSocket teardown must complete under the ASGI
connection cancellation scope.

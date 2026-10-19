# Milestone 5 Phase F — adversarial, privacy and recovery verification

## Status

Complete for automated verification. The target-Windows checkpoint remains
Phase G.

## Verified boundaries

- Stored prompt-injection text remains serialized untrusted conversation data
  and cannot enter or replace the application system instruction.
- Conversation claims cannot be assigned verified provenance.
- Generated answers are not inserted into memory.
- Duplicate/replay/stale/cross-session inputs cannot poison revision or order.
- Turn, character and context limits remain hard under synthetic pressure.
- Answer-provider failure, STT rotation and browser detach do not own or replace
  logical-session memory.
- Stop, reset, expiry and shutdown remove memory from the logical session.
- Normal logs were exercised with unique transcript and answer sentinels; neither
  body appeared in captured logs.
- A source-level regression guard confirms frontend persistent storage contains
  only the existing opaque resume token and active marker, never memory/context
  bodies.
- `MEMORY_CONTEXT_ENABLED=false` restores M4 assembly without disabling M3 or
  M4 independently.

All adversarial checks are deterministic and use fake/local providers. No secret,
personal transcript, paid API call or new persistence was used.

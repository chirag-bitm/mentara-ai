# Milestone 4 Phase D — Logical-session and reconnect semantics

## Status

Complete. Deterministic fake-provider lifecycle coverage and the target-Windows
disconnect/resume, supersession and Stop checks passed.

## Policy matrix

| Condition | Answer behavior |
| --- | --- |
| Browser disconnect before provider start | Generation remains owned by the logical session; no second request is created. |
| Browser disconnect while streaming | Browser sink detaches; generation continues for the resume lease. |
| Browser resume | Existing answer snapshots replay before the new sink is attached; live updates then continue. |
| Completed answer resume | Full immutable answer snapshot replays; provider is not called again. |
| 30-second resume expiry | Registry stops the logical session and cancels active answer work. |
| Stop | Active answer is cancelled, provider resources close, session is removed. |
| Session reset | Active answer is cancelled and old answer state is discarded with the old session ID. |
| Fatal STT failure | Pending turn state is flushed honestly and active answer work is cancelled during terminal cleanup. |
| STT rotation/reconnect | Answer task is unchanged because it belongs to the logical session, not the STT connection. |
| Answer provider failure | Answer becomes failed; STT and M2/M3 remain healthy. |
| Slow browser overflow | Browser writer is cancelled at the fixed bound; no unbounded queue remains. |

The in-memory registry remains the M3 mechanism and limitation. M4 adds no
database, Redis or durable task system.

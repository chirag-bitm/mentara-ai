# Milestone 3 Phase C — Meaningful assistance detection

## Status

Complete. The detector is local, deterministic, provider-neutral and isolated
from turn assembly. It adds no external model call or mandatory API cost.

## Semantics

The initial detector recognizes:

- direct interrogatives;
- auxiliary question forms;
- question punctuation as one signal;
- request verbs and interview-style imperatives;
- short follow-up forms;
- a focused set of common Latin-script and Devanagari Hinglish cues.

It suppresses:

- explicit short backchannels such as `okay`, `yes`, `thanks` and `got it`;
- common Hindi/Hinglish backchannels;
- ordinary declarative statements without actionable cues;
- short fragments without a meaningful cue.

`AssistanceDecision` reports only `question`, `request` or `none`, a stable
source-turn relationship, safe reason code and measured detection latency. It
does not invent probability/confidence and does not perform M4 topic routing.

## Replaceability and replay

`AssistanceDetector` is a protocol. A future local or cloud classifier can
replace the heuristic without changing the turn engine. The detection engine
processes each immutable turn once, retains positive decisions for replay and
suppresses duplicate processing using stable turn identity.

The curated tests verify specified examples and important negative controls.
They do not establish general natural-language detection accuracy.

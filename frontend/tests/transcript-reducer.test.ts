import assert from "node:assert/strict";
import test from "node:test";

import {
  INITIAL_TRANSCRIPT_STATE,
  selectFinalTranscripts,
  selectInterimTranscript,
  transcriptReducer,
  type TranscriptState,
} from "../src/lib/transcript-reducer";
import type {
  FinalTranscriptEvent,
  PartialTranscriptEvent,
  TranscriptEvent,
} from "../src/types/transcription";


function partial(
  sequence: number,
  revision: number,
  text: string,
  utteranceId = "utterance-1",
  sessionId = "session-1",
): PartialTranscriptEvent {
  return {
    type: "transcript.partial",
    session_id: sessionId,
    utterance_id: utteranceId,
    sequence,
    revision,
    audio_source: "microphone",
    speaker_role: "local_user",
    text,
    is_final: false,
    first_seen_ms: 0,
    last_updated_ms: sequence * 100,
  };
}


function final(
  sequence: number,
  revision: number,
  text: string,
  utteranceId = "utterance-1",
  sessionId = "session-1",
): FinalTranscriptEvent {
  return {
    type: "transcript.final",
    session_id: sessionId,
    utterance_id: utteranceId,
    sequence,
    revision,
    audio_source: "microphone",
    speaker_role: "local_user",
    text,
    is_final: true,
    first_seen_ms: 0,
    last_updated_ms: sequence * 100,
    finalized_ms: sequence * 100,
  };
}


function apply(state: TranscriptState, event: TranscriptEvent): TranscriptState {
  return transcriptReducer(state, { type: "transcript.event", event });
}


test("partial corrections update one canonical utterance before finalization", () => {
  let state = apply(INITIAL_TRANSCRIPT_STATE, partial(1, 1, "Can you"));
  state = apply(state, partial(2, 2, "Can you explain"));

  assert.equal(selectInterimTranscript(state), "Can you explain");
  assert.deepEqual(state.utteranceOrder, ["utterance-1"]);

  state = apply(state, final(3, 3, "Can you explain Redis?"));

  assert.equal(selectInterimTranscript(state), "");
  assert.deepEqual(
    selectFinalTranscripts(state).map((event) => event.text),
    ["Can you explain Redis?"],
  );
});


test("duplicate, stale and out-of-order events do not replace newer state", () => {
  let state = apply(INITIAL_TRANSCRIPT_STATE, partial(1, 1, "First"));
  state = apply(state, partial(3, 3, "Newest"));
  const current = state;

  state = apply(state, partial(3, 3, "Duplicate"));
  state = apply(state, partial(2, 2, "Stale"));

  assert.strictEqual(state, current);
  assert.equal(selectInterimTranscript(state), "Newest");
});


test("a finalized utterance is immutable and never duplicated", () => {
  let state = apply(INITIAL_TRANSCRIPT_STATE, final(1, 1, "Finished"));
  const finalized = state;

  state = apply(state, partial(2, 2, "Late partial"));
  state = apply(state, final(3, 3, "Repeated final"));

  assert.strictEqual(state, finalized);
  assert.equal(selectFinalTranscripts(state).length, 1);
  assert.equal(selectFinalTranscripts(state)[0]?.text, "Finished");
});


test("final utterances retain their original spoken order", () => {
  let state = apply(INITIAL_TRANSCRIPT_STATE, partial(1, 1, "First"));
  state = apply(state, final(2, 2, "First sentence."));
  state = apply(state, final(3, 1, "Second sentence.", "utterance-2"));

  assert.deepEqual(
    selectFinalTranscripts(state).map((event) => event.text),
    ["First sentence.", "Second sentence."],
  );
});


test("another session is ignored until an explicit reset", () => {
  let state = apply(INITIAL_TRANSCRIPT_STATE, final(1, 1, "Old session"));
  const oldSession = state;

  state = apply(state, final(1, 1, "Unexpected", "utterance-2", "session-2"));
  assert.strictEqual(state, oldSession);

  state = transcriptReducer(state, { type: "reset" });
  state = apply(state, final(1, 1, "New session", "utterance-2", "session-2"));

  assert.equal(state.sessionId, "session-2");
  assert.deepEqual(
    selectFinalTranscripts(state).map((event) => event.text),
    ["New session"],
  );
});


test("canonical reconnect replay rebuilds state and remains idempotent", () => {
  const first = final(3, 2, "First restored sentence.");
  const active = partial(7, 1, "Current restored words", "utterance-2");

  let state = apply(INITIAL_TRANSCRIPT_STATE, first);
  state = apply(state, active);

  assert.deepEqual(
    selectFinalTranscripts(state).map((event) => event.text),
    ["First restored sentence."],
  );
  assert.equal(selectInterimTranscript(state), "Current restored words");
  assert.equal(state.lastSequence, 7);

  const restored = state;
  state = apply(state, first);
  state = apply(state, active);
  assert.strictEqual(state, restored);
});

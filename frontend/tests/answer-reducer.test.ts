import assert from "node:assert/strict";
import test from "node:test";

import {
  answerReducer,
  INITIAL_ANSWER_STATE,
  selectLatestAnswer,
  type AnswerStateStore,
} from "../src/lib/answer-reducer";
import type {
  AnswerCompletedEvent,
  AnswerDeltaEvent,
  AnswerEvent,
  AnswerSnapshotEvent,
  AnswerStartedEvent,
  AnswerSupersededEvent,
} from "../src/types/transcription";


const common = {
  answer_id: "answer-1",
  session_id: "session-1",
  detection_id: "detection-1",
  source_turn_id: "turn-1",
  source_turn_sequence: 1,
  attempt: 1,
};


function started(overrides: Partial<AnswerStartedEvent> = {}): AnswerStartedEvent {
  return {
    ...common,
    type: "answer.started",
    state: "starting",
    revision: 2,
    stream_sequence: 0,
    requested_ms: 100,
    provider_started_ms: 102,
    question_detected_to_answer_request_ms: 1,
    answer_request_to_provider_start_ms: 2,
    ...overrides,
  };
}


function delta(
  from: number,
  to: number,
  text: string,
  revision: number,
): AnswerDeltaEvent {
  return {
    ...common,
    type: "answer.delta",
    state: "streaming",
    revision,
    from_stream_sequence: from,
    stream_sequence: to,
    text,
    first_text_ms: 120,
    answer_request_to_first_text_ms: 20,
    question_detected_to_first_text_ms: 21,
  };
}


function completed(revision = 5, sequence = 3): AnswerCompletedEvent {
  return {
    ...common,
    type: "answer.completed",
    state: "completed",
    revision,
    stream_sequence: sequence,
    terminal_ms: 150,
    answer_generation_total_ms: 50,
    input_tokens: 10,
    output_tokens: 4,
    total_tokens: 14,
  };
}


function apply(state: AnswerStateStore, event: AnswerEvent): AnswerStateStore {
  return answerReducer(state, { type: "answer.event", event });
}


test("coalesced and ordinary deltas stream in exact order", () => {
  let state = apply(INITIAL_ANSWER_STATE, started());
  state = apply(state, delta(1, 2, "Redis is ", 3));
  state = apply(state, delta(3, 3, "fast.", 4));
  state = apply(state, completed());

  const answer = selectLatestAnswer(state);
  assert.equal(answer?.state, "completed");
  assert.equal(answer?.text, "Redis is fast.");
  assert.equal(answer?.streamSequence, 3);
  assert.equal(answer?.questionDetectedToFirstTextMs, 21);
  assert.equal(answer?.answerGenerationTotalMs, 50);
  assert.equal(answer?.totalTokens, 14);
});


test("duplicate stale and out-of-order deltas are idempotently ignored", () => {
  let state = apply(INITIAL_ANSWER_STATE, started());
  state = apply(state, delta(1, 1, "one", 3));
  const current = state;

  state = apply(state, delta(1, 1, "duplicate", 3));
  state = apply(state, delta(3, 3, "gap", 4));
  state = apply(state, delta(1, 1, "stale", 2));
  assert.strictEqual(state, current);
  assert.equal(selectLatestAnswer(state)?.text, "one");
});


test("terminal answer is immutable and rejects late text", () => {
  let state = apply(INITIAL_ANSWER_STATE, started());
  state = apply(state, delta(1, 1, "final", 3));
  state = apply(state, completed(4, 1));
  const terminal = state;

  state = apply(state, delta(2, 2, "late", 5));
  state = apply(state, started({ revision: 6 }));
  assert.strictEqual(state, terminal);
  assert.equal(selectLatestAnswer(state)?.text, "final");
});


test("snapshot replay restores full state once and remains idempotent", () => {
  const snapshot: AnswerSnapshotEvent = {
    ...common,
    type: "answer.snapshot",
    state: "streaming",
    revision: 4,
    stream_sequence: 2,
    text: "restored partial",
    requested_ms: 100,
    provider_started_ms: 102,
    first_text_ms: 120,
    question_detected_to_answer_request_ms: 1,
    answer_request_to_provider_start_ms: 2,
    answer_request_to_first_text_ms: 20,
    question_detected_to_first_text_ms: 21,
  };
  let state = apply(INITIAL_ANSWER_STATE, snapshot);
  const restored = state;
  state = apply(state, snapshot);

  assert.strictEqual(state, restored);
  assert.equal(selectLatestAnswer(state)?.text, "restored partial");
  assert.equal(selectLatestAnswer(state)?.state, "streaming");
});


test("rapid supersession can terminate a requested answer before start", () => {
  const superseded: AnswerSupersededEvent = {
    ...common,
    type: "answer.superseded",
    state: "superseded",
    revision: 2,
    stream_sequence: 0,
    terminal_ms: 101,
  };
  const state = apply(INITIAL_ANSWER_STATE, superseded);
  assert.equal(selectLatestAnswer(state)?.state, "superseded");
});


test("cross-session events are ignored until explicit reset", () => {
  let state = apply(INITIAL_ANSWER_STATE, started());
  const original = state;
  state = apply(
    state,
    started({ answer_id: "answer-2", session_id: "session-2" }),
  );
  assert.strictEqual(state, original);

  state = answerReducer(state, { type: "reset" });
  state = apply(
    state,
    started({ answer_id: "answer-2", session_id: "session-2" }),
  );
  assert.equal(state.sessionId, "session-2");
});


test("provenance changes for an existing answer identity are rejected", () => {
  let state = apply(INITIAL_ANSWER_STATE, started());
  const original = state;
  state = apply(state, {
    ...delta(1, 1, "wrong", 3),
    detection_id: "different-detection",
  });
  assert.strictEqual(state, original);
});

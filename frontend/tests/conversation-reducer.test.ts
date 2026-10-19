import assert from "node:assert/strict";
import test from "node:test";

import {
  conversationReducer,
  INITIAL_CONVERSATION_STATE,
  selectLatestDetectedTurn,
  selectLatestDetection,
  selectLatestTurn,
  type ConversationState,
} from "../src/lib/conversation-reducer";
import type {
  ConversationEvent,
  QuestionDetectedEvent,
  TurnFinalizedEvent,
} from "../src/types/transcription";


function turn(sequence = 1, id = "turn-1", sessionId = "session-1"): TurnFinalizedEvent {
  return {
    type: "turn.finalized",
    session_id: sessionId,
    turn_id: id,
    turn_sequence: sequence,
    source_utterance_ids: [`utterance-${sequence}`],
    source_transcript_sequences: [sequence],
    audio_source: "microphone",
    speaker_role: "local_user",
    text: "Can you explain Redis?",
    started_ms: 0,
    last_updated_ms: 100,
    source_finalized_ms: 100,
    finalized_ms: 350,
    finalization_reason: "merge_window_elapsed",
    continuity_quality: "normal",
    transcript_final_to_turn_ms: 250,
  };
}


function detection(
  id = "detection-1",
  sourceTurnId = "turn-1",
  sequence = 1,
  sessionId = "session-1",
): QuestionDetectedEvent {
  return {
    type: "question.detected",
    detection_id: id,
    session_id: sessionId,
    source_turn_id: sourceTurnId,
    source_turn_sequence: sequence,
    kind: "request",
    detected_ms: 351,
    turn_to_detection_ms: 1,
  };
}


function apply(state: ConversationState, event: ConversationEvent): ConversationState {
  return conversationReducer(state, { type: "conversation.event", event });
}


test("finalized turns retain independent monotonic order", () => {
  let state = apply(INITIAL_CONVERSATION_STATE, turn());
  state = apply(state, turn(2, "turn-2"));
  assert.equal(selectLatestTurn(state)?.turn_id, "turn-2");
  assert.deepEqual(state.turnOrder, ["turn-1", "turn-2"]);
});


test("duplicate and stale turn replay is idempotent", () => {
  let state = apply(INITIAL_CONVERSATION_STATE, turn(2, "turn-2"));
  const current = state;
  state = apply(state, turn(2, "turn-2"));
  state = apply(state, turn(1, "turn-1"));
  assert.strictEqual(state, current);
});


test("a detection must reference an existing matching source turn", () => {
  const empty = apply(INITIAL_CONVERSATION_STATE, detection());
  assert.strictEqual(empty, INITIAL_CONVERSATION_STATE);

  let state = apply(INITIAL_CONVERSATION_STATE, turn());
  state = apply(state, detection());
  assert.equal(selectLatestDetection(state)?.detection_id, "detection-1");
  assert.equal(selectLatestDetectedTurn(state)?.turn_id, "turn-1");
});


test("duplicate detection replay is idempotent", () => {
  let state = apply(INITIAL_CONVERSATION_STATE, turn());
  state = apply(state, detection());
  const current = state;
  state = apply(state, detection());
  assert.strictEqual(state, current);
});


test("cross-session derived events are ignored until reset", () => {
  let state = apply(INITIAL_CONVERSATION_STATE, turn());
  const original = state;
  state = apply(state, turn(2, "turn-2", "session-2"));
  assert.strictEqual(state, original);
  state = conversationReducer(state, { type: "reset" });
  state = apply(state, turn(1, "turn-new", "session-2"));
  assert.equal(state.sessionId, "session-2");
});


test("continuity and measured latencies remain backend authoritative", () => {
  const degraded = {
    ...turn(),
    continuity_quality: "degraded" as const,
    transcript_final_to_turn_ms: 275,
  };
  const state = apply(INITIAL_CONVERSATION_STATE, degraded);
  assert.equal(selectLatestTurn(state)?.continuity_quality, "degraded");
  assert.equal(selectLatestTurn(state)?.transcript_final_to_turn_ms, 275);
});

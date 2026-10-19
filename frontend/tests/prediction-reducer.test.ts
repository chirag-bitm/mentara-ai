import assert from "node:assert/strict";
import test from "node:test";

import {
  INITIAL_PREDICTION_STATE,
  predictionReducer,
  selectLikelyNext,
} from "../src/lib/prediction-reducer";
import type { PredictionSnapshotEvent } from "../src/types/transcription";


function event(
  overrides: Partial<PredictionSnapshotEvent> = {},
): PredictionSnapshotEvent {
  return {
    type: "prediction.snapshot",
    prediction_id: "prediction-1",
    session_id: "session-1",
    active_turn_id: "turn-1",
    active_turn_sequence: 1,
    input_revision: 1,
    attempt: 1,
    state: "ready",
    revision: 3,
    audio_source: "microphone",
    speaker_role: "local_user",
    continuity_quality: "normal",
    active_turn_awaiting_finalization: false,
    candidate_consistent_revision_count: 1,
    candidates: [
      { kind: "question", text: "Why Redis?", anchor_terms: ["redis"] },
    ],
    input_observed_ms: 100,
    scheduled_ms: 100,
    provider_started_ms: 110,
    ready_ms: 140,
    readiness: "tentative",
    context_chars: 240,
    ...overrides,
  };
}


function apply(
  state = INITIAL_PREDICTION_STATE,
  next = event(),
) {
  return predictionReducer(state, { type: "prediction.event", event: next });
}


test("ready snapshot exposes bounded advisory candidates", () => {
  const state = apply();
  assert.equal(state.current?.state, "ready");
  assert.equal(selectLikelyNext(state)[0]?.text, "Why Redis?");
  assert.equal(state.current?.contextChars, 240);
});


test("duplicate stale revision and older input are idempotently rejected", () => {
  const state = apply();
  assert.strictEqual(apply(state, event()), state);
  assert.strictEqual(apply(state, event({ revision: 2 })), state);
  assert.strictEqual(
    apply(state, event({ revision: 4, input_revision: 0 })),
    state,
  );
});


test("newer invalidation immediately clears visible candidates", () => {
  let state = apply();
  state = apply(
    state,
    event({
      state: "invalidated",
      revision: 4,
      candidates: [],
      readiness: undefined,
      terminal_ms: 150,
      invalidation_reason: "active_input_changed",
    }),
  );
  assert.equal(state.current?.state, "invalidated");
  assert.deepEqual(selectLikelyNext(state), []);
});


test("newer input can change source or speaker and clears old output", () => {
  const state = apply();
  const corrected = apply(
    state,
    event({
      input_revision: 2,
      revision: 4,
      state: "scheduled",
      audio_source: "system",
      speaker_role: "remote_speaker",
      candidates: [],
      readiness: undefined,
    }),
  );

  assert.equal(corrected.current?.inputRevision, 2);
  assert.equal(corrected.current?.speakerRole, "remote_speaker");
  assert.deepEqual(selectLikelyNext(corrected), []);
});


test("new active turn replaces old state while old-turn replay is rejected", () => {
  let state = apply();
  state = apply(
    state,
    event({
      prediction_id: "prediction-2",
      active_turn_id: "turn-2",
      active_turn_sequence: 2,
      revision: 1,
      state: "scheduled",
      attempt: 0,
      candidates: [],
      readiness: undefined,
    }),
  );
  assert.equal(state.current?.predictionId, "prediction-2");
  const current = state;
  state = apply(state, event({ revision: 99 }));
  assert.strictEqual(state, current);
});


test("cross-session and changed provenance are rejected until reset", () => {
  let state = apply();
  const original = state;
  state = apply(state, event({ session_id: "session-2", revision: 4 }));
  state = apply(state, event({ speaker_role: "remote_speaker", revision: 4 }));
  assert.strictEqual(state, original);

  state = predictionReducer(state, { type: "reset" });
  state = apply(
    state,
    event({ session_id: "session-2", prediction_id: "prediction-2" }),
  );
  assert.equal(state.sessionId, "session-2");
});


test("malformed or oversized provider-shaped events fail closed", () => {
  const malformed = event({
    candidates: [
      { kind: "question", text: " untrimmed ", anchor_terms: [] },
    ],
  });
  assert.strictEqual(apply(INITIAL_PREDICTION_STATE, malformed), INITIAL_PREDICTION_STATE);

  const nonReadyWithCandidate = event({ state: "running" });
  assert.strictEqual(
    apply(INITIAL_PREDICTION_STATE, nonReadyWithCandidate),
    INITIAL_PREDICTION_STATE,
  );

  const missingCandidates = event() as unknown as Record<string, unknown>;
  missingCandidates.candidates = null;
  assert.doesNotThrow(() =>
    predictionReducer(INITIAL_PREDICTION_STATE, {
      type: "prediction.event",
      event: missingCandidates as unknown as PredictionSnapshotEvent,
    }),
  );
  assert.strictEqual(
    predictionReducer(INITIAL_PREDICTION_STATE, {
      type: "prediction.event",
      event: missingCandidates as unknown as PredictionSnapshotEvent,
    }),
    INITIAL_PREDICTION_STATE,
  );

  const invalidAnchors = event() as unknown as {
    candidates: Array<Record<string, unknown>>;
  };
  invalidAnchors.candidates[0].anchor_terms = null;
  assert.doesNotThrow(() =>
    predictionReducer(INITIAL_PREDICTION_STATE, {
      type: "prediction.event",
      event: invalidAnchors as unknown as PredictionSnapshotEvent,
    }),
  );

  const unknownState = event({ state: "future_state" as "ready" });
  assert.strictEqual(
    apply(INITIAL_PREDICTION_STATE, unknownState),
    INITIAL_PREDICTION_STATE,
  );
});

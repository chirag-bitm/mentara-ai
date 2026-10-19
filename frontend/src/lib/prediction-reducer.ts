import type {
  PredictionCandidatePayload,
  PredictionSnapshotEvent,
  PredictionState,
} from "../types/transcription";

export interface PredictionRecord {
  predictionId: string;
  sessionId: string;
  activeTurnId: string;
  activeTurnSequence: number;
  inputRevision: number;
  attempt: number;
  state: PredictionState;
  revision: number;
  audioSource: PredictionSnapshotEvent["audio_source"];
  speakerRole: PredictionSnapshotEvent["speaker_role"];
  continuityQuality: PredictionSnapshotEvent["continuity_quality"];
  readiness: PredictionSnapshotEvent["readiness"] | null;
  candidates: PredictionCandidatePayload[];
  contextChars: number | null;
}

export interface PredictionStateStore {
  sessionId: string | null;
  current: PredictionRecord | null;
}

export type PredictionAction =
  | { type: "reset" }
  | { type: "prediction.event"; event: PredictionSnapshotEvent };

export const INITIAL_PREDICTION_STATE: PredictionStateStore = {
  sessionId: null,
  current: null,
};

const PREDICTION_STATES = new Set([
  "scheduled",
  "running",
  "ready",
  "invalidated",
  "failed",
]);
const AUDIO_SOURCES = new Set(["microphone", "system"]);
const SPEAKER_ROLES = new Set(["local_user", "remote_speaker", "unknown"]);
const CONTINUITY_QUALITIES = new Set(["normal", "degraded"]);
const READINESS_VALUES = new Set(["tentative", "stable"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function validCandidate(candidate: unknown): candidate is PredictionCandidatePayload {
  if (!isRecord(candidate) || !Array.isArray(candidate.anchor_terms)) {
    return false;
  }
  return (
    (candidate.kind === "question" ||
      candidate.kind === "request" ||
      candidate.kind === "topic") &&
    typeof candidate.text === "string" &&
    candidate.text.trim() === candidate.text &&
    candidate.text.length > 0 &&
    candidate.text.length <= 240 &&
    candidate.anchor_terms.length <= 8 &&
    new Set(candidate.anchor_terms).size === candidate.anchor_terms.length &&
    candidate.anchor_terms.every(
      (term) =>
        typeof term === "string" &&
        term.length > 0 &&
        term.length <= 64 &&
        term.trim() === term,
    )
  );
}

function validEvent(event: PredictionSnapshotEvent): boolean {
  if (
    !isRecord(event) ||
    !Array.isArray(event.candidates) ||
    typeof event.prediction_id !== "string" ||
    event.prediction_id.length === 0 ||
    typeof event.session_id !== "string" ||
    event.session_id.length === 0 ||
    typeof event.active_turn_id !== "string" ||
    event.active_turn_id.length === 0 ||
    !PREDICTION_STATES.has(event.state) ||
    !AUDIO_SOURCES.has(event.audio_source) ||
    !SPEAKER_ROLES.has(event.speaker_role) ||
    !CONTINUITY_QUALITIES.has(event.continuity_quality) ||
    typeof event.active_turn_awaiting_finalization !== "boolean" ||
    (event.readiness !== undefined && !READINESS_VALUES.has(event.readiness)) ||
    !Number.isInteger(event.active_turn_sequence) ||
    !Number.isInteger(event.input_revision) ||
    !Number.isInteger(event.attempt) ||
    !Number.isInteger(event.revision) ||
    !Number.isInteger(event.candidate_consistent_revision_count)
  ) {
    return false;
  }
  const candidateKeys = event.candidates.map(
    (candidate) =>
      isRecord(candidate) && typeof candidate.text === "string"
        ? `${String(candidate.kind)}:${candidate.text.toLowerCase()}`
        : "",
  );
  return (
    event.active_turn_sequence >= 1 &&
    event.input_revision >= 1 &&
    event.attempt >= 0 &&
    event.revision >= 1 &&
    event.candidate_consistent_revision_count >= 0 &&
    Number.isInteger(event.input_observed_ms) &&
    event.input_observed_ms >= 0 &&
    (event.context_chars === undefined ||
      (Number.isInteger(event.context_chars) && event.context_chars >= 1)) &&
    event.candidates.length <= 5 &&
    event.candidates.every(validCandidate) &&
    new Set(candidateKeys).size === candidateKeys.length &&
    (event.state === "ready" || event.candidates.length === 0) &&
    (event.state === "ready" || event.readiness === undefined) &&
    (event.readiness === undefined || event.candidates.length > 0) &&
    (event.readiness !== "stable" ||
      (event.candidate_consistent_revision_count >= 2 &&
        event.active_turn_awaiting_finalization &&
        event.continuity_quality === "normal"))
  );
}

function sameStableTurn(
  record: PredictionRecord,
  event: PredictionSnapshotEvent,
): boolean {
  return (
    record.sessionId === event.session_id &&
    record.activeTurnId === event.active_turn_id &&
    record.activeTurnSequence === event.active_turn_sequence
  );
}

function recordFrom(event: PredictionSnapshotEvent): PredictionRecord {
  return {
    predictionId: event.prediction_id,
    sessionId: event.session_id,
    activeTurnId: event.active_turn_id,
    activeTurnSequence: event.active_turn_sequence,
    inputRevision: event.input_revision,
    attempt: event.attempt,
    state: event.state,
    revision: event.revision,
    audioSource: event.audio_source,
    speakerRole: event.speaker_role,
    continuityQuality: event.continuity_quality,
    readiness: event.readiness ?? null,
    candidates: event.state === "ready" ? event.candidates : [],
    contextChars: event.context_chars ?? null,
  };
}

export function predictionReducer(
  state: PredictionStateStore,
  action: PredictionAction,
): PredictionStateStore {
  if (action.type === "reset") return INITIAL_PREDICTION_STATE;

  const event = action.event;
  if (
    !validEvent(event) ||
    (state.sessionId !== null && event.session_id !== state.sessionId)
  ) {
    return state;
  }

  const current = state.current;
  if (current !== null) {
    if (event.prediction_id === current.predictionId) {
      if (
        !sameStableTurn(current, event) ||
        event.revision <= current.revision ||
        event.input_revision < current.inputRevision ||
        event.attempt < current.attempt ||
        (event.input_revision === current.inputRevision &&
          (event.audio_source !== current.audioSource ||
            event.speaker_role !== current.speakerRole))
      ) {
        return state;
      }
    } else if (event.active_turn_sequence <= current.activeTurnSequence) {
      return state;
    }
  }

  return {
    sessionId: state.sessionId ?? event.session_id,
    current: recordFrom(event),
  };
}

export function selectLikelyNext(
  state: PredictionStateStore,
): PredictionCandidatePayload[] {
  return state.current?.state === "ready" ? state.current.candidates : [];
}

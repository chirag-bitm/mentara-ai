export type StreamStatus =
  | "idle"
  | "connecting"
  | "requesting-microphone"
  | "listening"
  | "reconnecting"
  | "degraded"
  | "stopping"
  | "error";

export type ConnectionCheck = "idle" | "checking" | "passed" | "failed";

export type AudioSource = "microphone" | "system";
export type SpeakerRole = "local_user" | "remote_speaker";
export type ContinuityQuality = "normal" | "degraded";
export type TurnFinalizationReason =
  | "merge_window_elapsed"
  | "source_changed"
  | "stop_requested"
  | "browser_disconnected"
  | "provider_failed"
  | "session_reset";

export interface CanonicalTranscriptPayload {
  session_id: string;
  utterance_id: string;
  sequence: number;
  revision: number;
  audio_source: AudioSource;
  speaker_role: SpeakerRole;
  text: string;
  first_seen_ms: number;
  last_updated_ms: number;
  finalized_ms?: number;
  confidence?: number;
}

export type PartialTranscriptEvent = CanonicalTranscriptPayload & {
  type: "transcript.partial";
  is_final: false;
};

export type FinalTranscriptEvent = CanonicalTranscriptPayload & {
  type: "transcript.final";
  is_final: true;
};

export type TranscriptEvent = PartialTranscriptEvent | FinalTranscriptEvent;

export interface TurnFinalizedEvent {
  type: "turn.finalized";
  session_id: string;
  turn_id: string;
  turn_sequence: number;
  source_utterance_ids: string[];
  source_transcript_sequences: number[];
  audio_source: AudioSource;
  speaker_role: SpeakerRole;
  text: string;
  started_ms: number;
  last_updated_ms: number;
  source_finalized_ms: number;
  finalized_ms: number;
  finalization_reason: TurnFinalizationReason;
  continuity_quality: ContinuityQuality;
  transcript_final_to_turn_ms: number;
}

export interface QuestionDetectedEvent {
  type: "question.detected";
  detection_id: string;
  session_id: string;
  source_turn_id: string;
  source_turn_sequence: number;
  kind: "question" | "request";
  detected_ms: number;
  turn_to_detection_ms: number;
}

export type ConversationEvent = TurnFinalizedEvent | QuestionDetectedEvent;

export type AnswerState =
  | "requested"
  | "starting"
  | "streaming"
  | "completed"
  | "cancelled"
  | "superseded"
  | "failed";

export type AnswerFailureCategory =
  | "configuration"
  | "authentication"
  | "rate_limit"
  | "transient_network"
  | "provider_server"
  | "malformed_stream"
  | "timeout"
  | "cancellation"
  | "safety_refusal"
  | "unknown";

export interface AnswerEventPayload {
  answer_id: string;
  session_id: string;
  detection_id: string;
  source_turn_id: string;
  source_turn_sequence: number;
  attempt: number;
  revision: number;
  stream_sequence: number;
}

export interface AnswerStartedEvent extends AnswerEventPayload {
  type: "answer.started";
  state: "starting";
  requested_ms: number;
  provider_started_ms: number;
  question_detected_to_answer_request_ms: number;
  answer_request_to_provider_start_ms: number;
}

export interface AnswerDeltaEvent extends AnswerEventPayload {
  type: "answer.delta";
  state: "streaming";
  from_stream_sequence: number;
  text: string;
  first_text_ms: number;
  answer_request_to_first_text_ms: number;
  question_detected_to_first_text_ms: number;
}

export interface AnswerCompletedEvent extends AnswerEventPayload {
  type: "answer.completed";
  state: "completed";
  terminal_ms: number;
  answer_generation_total_ms: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}

export interface AnswerCancelledEvent extends AnswerEventPayload {
  type: "answer.cancelled";
  state: "cancelled";
  terminal_ms: number;
}

export interface AnswerSupersededEvent extends AnswerEventPayload {
  type: "answer.superseded";
  state: "superseded";
  terminal_ms: number;
}

export interface AnswerFailedEvent extends AnswerEventPayload {
  type: "answer.failed";
  state: "failed";
  terminal_ms: number;
  error_category: AnswerFailureCategory;
  message: string;
  retryable: boolean;
}

export interface AnswerSnapshotEvent extends AnswerEventPayload {
  type: "answer.snapshot";
  state: AnswerState;
  text: string;
  requested_ms: number;
  question_detected_to_answer_request_ms: number;
  provider_started_ms?: number;
  first_text_ms?: number;
  terminal_ms?: number;
  answer_request_to_provider_start_ms?: number;
  answer_request_to_first_text_ms?: number;
  question_detected_to_first_text_ms?: number;
  answer_generation_total_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  error_category?: AnswerFailureCategory;
  message?: string;
  retryable?: boolean;
}

export type AnswerEvent =
  | AnswerStartedEvent
  | AnswerDeltaEvent
  | AnswerCompletedEvent
  | AnswerCancelledEvent
  | AnswerSupersededEvent
  | AnswerFailedEvent
  | AnswerSnapshotEvent;

export type PredictionState =
  | "scheduled"
  | "running"
  | "ready"
  | "invalidated"
  | "failed";

export type PredictionReadiness = "tentative" | "stable";
export type PredictionCandidateKind = "question" | "request" | "topic";
export type PredictionFailureCategory =
  | "configuration"
  | "authentication"
  | "rate_limit"
  | "transient_network"
  | "provider_server"
  | "malformed_output"
  | "timeout"
  | "cancellation"
  | "safety_refusal"
  | "unknown";

export type PredictionInvalidationReason =
  | "active_input_changed"
  | "active_provenance_changed"
  | "new_active_turn"
  | "source_or_speaker_changed"
  | "context_changed"
  | "turn_finalized"
  | "continuity_degraded"
  | "browser_disconnected"
  | "stop_requested"
  | "session_reset"
  | "session_expired"
  | "backend_shutdown"
  | "turn_attempt_limit"
  | "session_call_limit"
  | "context_unavailable";

export interface PredictionCandidatePayload {
  kind: PredictionCandidateKind;
  text: string;
  anchor_terms: string[];
}

export interface PredictionSnapshotEvent {
  type: "prediction.snapshot";
  prediction_id: string;
  session_id: string;
  active_turn_id: string;
  active_turn_sequence: number;
  input_revision: number;
  attempt: number;
  state: PredictionState;
  revision: number;
  audio_source: AudioSource;
  speaker_role: SpeakerRole;
  continuity_quality: ContinuityQuality;
  active_turn_awaiting_finalization: boolean;
  candidate_consistent_revision_count: number;
  candidates: PredictionCandidatePayload[];
  input_observed_ms: number;
  scheduled_ms?: number;
  provider_started_ms?: number;
  ready_ms?: number;
  terminal_ms?: number;
  readiness?: PredictionReadiness;
  invalidation_reason?: PredictionInvalidationReason;
  error_category?: PredictionFailureCategory;
  message?: string;
  retryable?: boolean;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  context_chars?: number;
}

export type ServerEvent =
  | {
      type: "status";
      status:
        | "connecting"
        | "ready"
        | "reconnecting"
        | "degraded"
        | "stopping"
        | "stopped";
      message: string;
    }
  | TranscriptEvent
  | ConversationEvent
  | AnswerEvent
  | PredictionSnapshotEvent
  | {
      type: "session.ready";
      session_id: string;
      resume_token: string;
      resumed: boolean;
      resume_ttl_seconds: number;
    }
  | {
      type: "error";
      code: string;
      message: string;
    }
  | {
      type: "pong";
      message: string;
    };

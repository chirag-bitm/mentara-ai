import type {
  AnswerEvent,
  AnswerFailureCategory,
  AnswerState,
} from "../types/transcription";

export interface AnswerRecord {
  answerId: string;
  sessionId: string;
  detectionId: string;
  sourceTurnId: string;
  sourceTurnSequence: number;
  attempt: number;
  state: AnswerState;
  revision: number;
  streamSequence: number;
  text: string;
  requestedMs: number | null;
  providerStartedMs: number | null;
  firstTextMs: number | null;
  terminalMs: number | null;
  questionDetectedToAnswerRequestMs: number | null;
  answerRequestToProviderStartMs: number | null;
  answerRequestToFirstTextMs: number | null;
  questionDetectedToFirstTextMs: number | null;
  answerGenerationTotalMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  errorCategory: AnswerFailureCategory | null;
  message: string | null;
  retryable: boolean | null;
}

export interface AnswerStateStore {
  sessionId: string | null;
  answerOrder: string[];
  answersById: Record<string, AnswerRecord>;
}

export type AnswerAction =
  | { type: "reset" }
  | { type: "answer.event"; event: AnswerEvent };

export const INITIAL_ANSWER_STATE: AnswerStateStore = {
  sessionId: null,
  answerOrder: [],
  answersById: {},
};

const TERMINAL_STATES = new Set<AnswerState>([
  "completed",
  "cancelled",
  "superseded",
  "failed",
]);

function baseRecord(event: AnswerEvent): AnswerRecord {
  return {
    answerId: event.answer_id,
    sessionId: event.session_id,
    detectionId: event.detection_id,
    sourceTurnId: event.source_turn_id,
    sourceTurnSequence: event.source_turn_sequence,
    attempt: event.attempt,
    state: event.state,
    revision: event.revision,
    streamSequence: event.stream_sequence,
    text: event.type === "answer.snapshot" ? event.text : "",
    requestedMs:
      event.type === "answer.started" || event.type === "answer.snapshot"
        ? event.requested_ms
        : null,
    providerStartedMs:
      event.type === "answer.started"
        ? event.provider_started_ms
        : event.type === "answer.snapshot"
          ? (event.provider_started_ms ?? null)
          : null,
    firstTextMs:
      event.type === "answer.delta"
        ? event.first_text_ms
        : event.type === "answer.snapshot"
          ? (event.first_text_ms ?? null)
          : null,
    terminalMs:
      event.type === "answer.completed" ||
      event.type === "answer.cancelled" ||
      event.type === "answer.superseded" ||
      event.type === "answer.failed"
        ? event.terminal_ms
        : event.type === "answer.snapshot"
          ? (event.terminal_ms ?? null)
          : null,
    questionDetectedToAnswerRequestMs:
      event.type === "answer.started" || event.type === "answer.snapshot"
        ? event.question_detected_to_answer_request_ms
        : null,
    answerRequestToProviderStartMs:
      event.type === "answer.started"
        ? event.answer_request_to_provider_start_ms
        : event.type === "answer.snapshot"
          ? (event.answer_request_to_provider_start_ms ?? null)
          : null,
    answerRequestToFirstTextMs:
      event.type === "answer.delta"
        ? event.answer_request_to_first_text_ms
        : event.type === "answer.snapshot"
          ? (event.answer_request_to_first_text_ms ?? null)
          : null,
    questionDetectedToFirstTextMs:
      event.type === "answer.delta"
        ? event.question_detected_to_first_text_ms
        : event.type === "answer.snapshot"
          ? (event.question_detected_to_first_text_ms ?? null)
          : null,
    answerGenerationTotalMs:
      event.type === "answer.completed"
        ? event.answer_generation_total_ms
        : event.type === "answer.snapshot"
          ? (event.answer_generation_total_ms ?? null)
          : null,
    inputTokens:
      "input_tokens" in event ? (event.input_tokens ?? null) : null,
    outputTokens:
      "output_tokens" in event ? (event.output_tokens ?? null) : null,
    totalTokens:
      "total_tokens" in event ? (event.total_tokens ?? null) : null,
    errorCategory:
      event.type === "answer.failed"
        ? event.error_category
        : event.type === "answer.snapshot"
          ? (event.error_category ?? null)
          : null,
    message:
      event.type === "answer.failed"
        ? event.message
        : event.type === "answer.snapshot"
          ? (event.message ?? null)
          : null,
    retryable:
      event.type === "answer.failed"
        ? event.retryable
        : event.type === "answer.snapshot"
          ? (event.retryable ?? null)
          : null,
  };
}

function sameProvenance(record: AnswerRecord, event: AnswerEvent): boolean {
  return (
    record.sessionId === event.session_id &&
    record.detectionId === event.detection_id &&
    record.sourceTurnId === event.source_turn_id &&
    record.sourceTurnSequence === event.source_turn_sequence &&
    record.attempt === event.attempt
  );
}

function mergeEvent(record: AnswerRecord, event: AnswerEvent): AnswerRecord | null {
  if (!sameProvenance(record, event)) return null;
  if (TERMINAL_STATES.has(record.state) || event.revision <= record.revision) {
    return null;
  }

  if (event.type === "answer.delta") {
    if (
      event.from_stream_sequence !== record.streamSequence + 1 ||
      event.stream_sequence < event.from_stream_sequence ||
      !event.text
    ) {
      return null;
    }
    return {
      ...record,
      state: "streaming",
      revision: event.revision,
      streamSequence: event.stream_sequence,
      text: record.text + event.text,
      firstTextMs: event.first_text_ms,
      answerRequestToFirstTextMs: event.answer_request_to_first_text_ms,
      questionDetectedToFirstTextMs: event.question_detected_to_first_text_ms,
    };
  }

  if (event.type === "answer.snapshot") {
    return baseRecord(event);
  }

  const update = baseRecord(event);
  return {
    ...record,
    ...update,
    text: record.text,
    requestedMs: update.requestedMs ?? record.requestedMs,
    providerStartedMs: update.providerStartedMs ?? record.providerStartedMs,
    firstTextMs: update.firstTextMs ?? record.firstTextMs,
    questionDetectedToAnswerRequestMs:
      update.questionDetectedToAnswerRequestMs ??
      record.questionDetectedToAnswerRequestMs,
    answerRequestToProviderStartMs:
      update.answerRequestToProviderStartMs ?? record.answerRequestToProviderStartMs,
    answerRequestToFirstTextMs:
      update.answerRequestToFirstTextMs ?? record.answerRequestToFirstTextMs,
    questionDetectedToFirstTextMs:
      update.questionDetectedToFirstTextMs ?? record.questionDetectedToFirstTextMs,
  };
}

export function answerReducer(
  state: AnswerStateStore,
  action: AnswerAction,
): AnswerStateStore {
  if (action.type === "reset") return INITIAL_ANSWER_STATE;

  const event = action.event;
  if (
    event.source_turn_sequence < 1 ||
    event.attempt < 1 ||
    event.revision < 1 ||
    event.stream_sequence < 0 ||
    (state.sessionId !== null && event.session_id !== state.sessionId)
  ) {
    return state;
  }

  const current = state.answersById[event.answer_id];
  if (current) {
    const merged = mergeEvent(current, event);
    if (merged === null) return state;
    return {
      ...state,
      answersById: { ...state.answersById, [event.answer_id]: merged },
    };
  }

  if (event.type === "answer.delta") return state;
  const created = baseRecord(event);
  return {
    sessionId: state.sessionId ?? event.session_id,
    answerOrder: [...state.answerOrder, event.answer_id],
    answersById: { ...state.answersById, [event.answer_id]: created },
  };
}

export function selectLatestAnswer(state: AnswerStateStore): AnswerRecord | null {
  const answerId = state.answerOrder.at(-1);
  return answerId ? state.answersById[answerId] ?? null : null;
}

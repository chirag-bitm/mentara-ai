import type {
  ConversationEvent,
  QuestionDetectedEvent,
  TurnFinalizedEvent,
} from "../types/transcription";

export interface ConversationState {
  sessionId: string | null;
  lastTurnSequence: number;
  turnOrder: string[];
  turnsById: Record<string, TurnFinalizedEvent>;
  detectionOrder: string[];
  detectionsById: Record<string, QuestionDetectedEvent>;
}

export type ConversationAction =
  | { type: "reset" }
  | { type: "conversation.event"; event: ConversationEvent };

export const INITIAL_CONVERSATION_STATE: ConversationState = {
  sessionId: null,
  lastTurnSequence: 0,
  turnOrder: [],
  turnsById: {},
  detectionOrder: [],
  detectionsById: {},
};

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  if (action.type === "reset") return INITIAL_CONVERSATION_STATE;

  const event = action.event;
  if (state.sessionId !== null && event.session_id !== state.sessionId) {
    return state;
  }

  if (event.type === "turn.finalized") {
    if (
      event.turn_sequence < 1 ||
      event.turn_sequence <= state.lastTurnSequence ||
      state.turnsById[event.turn_id]
    ) {
      return state;
    }
    return {
      ...state,
      sessionId: state.sessionId ?? event.session_id,
      lastTurnSequence: event.turn_sequence,
      turnOrder: [...state.turnOrder, event.turn_id],
      turnsById: { ...state.turnsById, [event.turn_id]: event },
    };
  }

  if (
    event.source_turn_sequence < 1 ||
    state.detectionsById[event.detection_id]
  ) {
    return state;
  }
  const sourceTurn = state.turnsById[event.source_turn_id];
  if (
    !sourceTurn ||
    sourceTurn.turn_sequence !== event.source_turn_sequence ||
    sourceTurn.session_id !== event.session_id
  ) {
    return state;
  }
  return {
    ...state,
    sessionId: state.sessionId ?? event.session_id,
    detectionOrder: [...state.detectionOrder, event.detection_id],
    detectionsById: {
      ...state.detectionsById,
      [event.detection_id]: event,
    },
  };
}

export function selectLatestTurn(
  state: ConversationState,
): TurnFinalizedEvent | null {
  const turnId = state.turnOrder.at(-1);
  return turnId ? state.turnsById[turnId] ?? null : null;
}

export function selectLatestDetection(
  state: ConversationState,
): QuestionDetectedEvent | null {
  const detectionId = state.detectionOrder.at(-1);
  return detectionId ? state.detectionsById[detectionId] ?? null : null;
}

export function selectLatestDetectedTurn(
  state: ConversationState,
): TurnFinalizedEvent | null {
  const detection = selectLatestDetection(state);
  return detection ? state.turnsById[detection.source_turn_id] ?? null : null;
}

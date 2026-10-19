import type {
  FinalTranscriptEvent,
  TranscriptEvent,
} from "../types/transcription";

export interface TranscriptState {
  sessionId: string | null;
  lastSequence: number;
  utteranceOrder: string[];
  utterancesById: Record<string, TranscriptEvent>;
}

export type TranscriptAction =
  | { type: "reset" }
  | { type: "transcript.event"; event: TranscriptEvent };

export const INITIAL_TRANSCRIPT_STATE: TranscriptState = {
  sessionId: null,
  lastSequence: 0,
  utteranceOrder: [],
  utterancesById: {},
};

export function transcriptReducer(
  state: TranscriptState,
  action: TranscriptAction,
): TranscriptState {
  if (action.type === "reset") {
    return INITIAL_TRANSCRIPT_STATE;
  }

  const event = action.event;
  if (event.sequence < 1 || event.revision < 1) {
    return state;
  }

  if (state.sessionId !== null && event.session_id !== state.sessionId) {
    return state;
  }

  if (event.sequence <= state.lastSequence) {
    return state;
  }

  const existing = state.utterancesById[event.utterance_id];
  if (existing && (existing.is_final || event.revision <= existing.revision)) {
    return state;
  }

  return {
    sessionId: state.sessionId ?? event.session_id,
    lastSequence: event.sequence,
    utteranceOrder: existing
      ? state.utteranceOrder
      : [...state.utteranceOrder, event.utterance_id],
    utterancesById: {
      ...state.utterancesById,
      [event.utterance_id]: event,
    },
  };
}

export function selectFinalTranscripts(
  state: TranscriptState,
): FinalTranscriptEvent[] {
  return state.utteranceOrder
    .map((utteranceId) => state.utterancesById[utteranceId])
    .filter((event): event is FinalTranscriptEvent => event?.is_final === true);
}

export function selectInterimTranscript(state: TranscriptState): string {
  let latestPartial: TranscriptEvent | undefined;

  for (const utteranceId of state.utteranceOrder) {
    const event = state.utterancesById[utteranceId];
    if (
      event &&
      !event.is_final &&
      (!latestPartial || event.sequence > latestPartial.sequence)
    ) {
      latestPartial = event;
    }
  }

  return latestPartial?.text ?? "";
}

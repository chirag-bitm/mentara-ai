export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const WS_BASE_URL =
  process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8000";

export const AUDIO_SAMPLE_RATE = 16_000;
export const AUDIO_CHANNELS = 1;
export const AUDIO_ENCODING = "linear16";


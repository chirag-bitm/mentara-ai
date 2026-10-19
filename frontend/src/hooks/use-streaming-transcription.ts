"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import {
  AUDIO_CHANNELS,
  AUDIO_ENCODING,
  AUDIO_SAMPLE_RATE,
  WS_BASE_URL,
} from "@/lib/config";
import {
  BROWSER_RECONNECT_DELAYS_MS,
  shouldRetrySessionConnection,
} from "@/lib/reconnect-policy";
import {
  INITIAL_TRANSCRIPT_STATE,
  selectFinalTranscripts,
  selectInterimTranscript,
  transcriptReducer,
} from "@/lib/transcript-reducer";
import {
  conversationReducer,
  INITIAL_CONVERSATION_STATE,
  selectLatestDetectedTurn,
  selectLatestDetection,
  selectLatestTurn,
} from "@/lib/conversation-reducer";
import {
  answerReducer,
  INITIAL_ANSWER_STATE,
  selectLatestAnswer,
} from "@/lib/answer-reducer";
import {
  INITIAL_PREDICTION_STATE,
  predictionReducer,
  selectLikelyNext,
} from "@/lib/prediction-reducer";
import type {
  ConnectionCheck,
  ServerEvent,
  StreamStatus,
} from "@/types/transcription";

interface AudioResources {
  stream: MediaStream | null;
  context: AudioContext | null;
  source: MediaStreamAudioSourceNode | null;
  worklet: AudioWorkletNode | null;
  mutedOutput: GainNode | null;
}

const EMPTY_AUDIO: AudioResources = {
  stream: null,
  context: null,
  source: null,
  worklet: null,
  mutedOutput: null,
};

const RESUME_TOKEN_KEY = "mentara.transcription.resume-token";
const ACTIVE_SESSION_KEY = "mentara.transcription.active";

class SessionSocketError extends Error {
  constructor(
    message: string,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "SessionSocketError";
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return "Microphone permission was denied. Allow microphone access in Chrome and try again.";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "No microphone was found. Connect or enable a microphone and try again.";
  }
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function readStoredResumeToken(): string | null {
  try {
    if (window.sessionStorage.getItem(ACTIVE_SESSION_KEY) !== "true") return null;
    return window.sessionStorage.getItem(RESUME_TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeResumeToken(token: string): void {
  try {
    window.sessionStorage.setItem(RESUME_TOKEN_KEY, token);
    window.sessionStorage.setItem(ACTIVE_SESSION_KEY, "true");
  } catch {
    // Reconnection remains available in memory when sessionStorage is blocked.
  }
}

function clearStoredResumeToken(): void {
  try {
    window.sessionStorage.removeItem(RESUME_TOKEN_KEY);
    window.sessionStorage.removeItem(ACTIVE_SESSION_KEY);
  } catch {
    // There is nothing else to clear when browser storage is unavailable.
  }
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

export function useStreamingTranscription() {
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [statusMessage, setStatusMessage] = useState("Ready to test the pipeline.");
  const [error, setError] = useState<string | null>(null);
  const [transcriptState, dispatchTranscript] = useReducer(
    transcriptReducer,
    INITIAL_TRANSCRIPT_STATE,
  );
  const [conversationState, dispatchConversation] = useReducer(
    conversationReducer,
    INITIAL_CONVERSATION_STATE,
  );
  const [answerState, dispatchAnswer] = useReducer(
    answerReducer,
    INITIAL_ANSWER_STATE,
  );
  const [predictionState, dispatchPrediction] = useReducer(
    predictionReducer,
    INITIAL_PREDICTION_STATE,
  );
  const [audioLevel, setAudioLevel] = useState(0);
  const [connectionCheck, setConnectionCheck] = useState<ConnectionCheck>("idle");

  const interimTranscript = useMemo(
    () => selectInterimTranscript(transcriptState),
    [transcriptState],
  );
  const finalTranscripts = useMemo(
    () => selectFinalTranscripts(transcriptState),
    [transcriptState],
  );
  const latestTurn = useMemo(
    () => selectLatestTurn(conversationState),
    [conversationState],
  );
  const latestDetection = useMemo(
    () => selectLatestDetection(conversationState),
    [conversationState],
  );
  const latestDetectedTurn = useMemo(
    () => selectLatestDetectedTurn(conversationState),
    [conversationState],
  );
  const latestAnswer = useMemo(
    () => selectLatestAnswer(answerState),
    [answerState],
  );
  const likelyNext = useMemo(
    () => selectLikelyNext(predictionState),
    [predictionState],
  );

  const socketRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<AudioResources>({ ...EMPTY_AUDIO });
  const resumeTokenRef = useRef<string | null>(null);
  const lastConnectionResumedRef = useRef(false);
  const shouldReconnectRef = useRef(false);
  const reconnectingRef = useRef(false);
  const startingRef = useRef(false);
  const unmountedRef = useRef(false);
  const reconnectRef = useRef<() => void>(() => undefined);

  const releaseAudio = useCallback(async () => {
    const audio = audioRef.current;
    if (audio.worklet) audio.worklet.port.onmessage = null;
    audio.source?.disconnect();
    audio.worklet?.disconnect();
    audio.mutedOutput?.disconnect();
    audio.stream?.getTracks().forEach((track) => track.stop());
    if (audio.context && audio.context.state !== "closed") {
      await audio.context.close();
    }
    audioRef.current = { ...EMPTY_AUDIO };
    setAudioLevel(0);
  }, []);

  const processServerEvent = useCallback((event: ServerEvent) => {
    if (event.type === "session.ready") {
      resumeTokenRef.current = event.resume_token;
      lastConnectionResumedRef.current = event.resumed;
      storeResumeToken(event.resume_token);
      return;
    }

    if (event.type === "status") {
      setStatusMessage(event.message);
      if (event.status === "stopping") setStatus("stopping");
      if (event.status === "stopped") {
        shouldReconnectRef.current = false;
        resumeTokenRef.current = null;
        clearStoredResumeToken();
        dispatchPrediction({ type: "reset" });
        setStatus("idle");
      }
      if (event.status === "reconnecting") setStatus("reconnecting");
      if (event.status === "degraded") setStatus("degraded");
      if (event.status === "ready") {
        setStatus((current) =>
          current === "reconnecting" || current === "degraded"
            ? "listening"
            : current,
        );
      }
      return;
    }

    if (event.type === "error") {
      shouldReconnectRef.current = false;
      resumeTokenRef.current = null;
      clearStoredResumeToken();
      setError(`${event.code}: ${event.message}`);
      setStatusMessage("Streaming transcription failed.");
      setStatus("error");
      dispatchPrediction({ type: "reset" });
      void releaseAudio();
      return;
    }

    if (
      event.type === "transcript.partial" ||
      event.type === "transcript.final"
    ) {
      dispatchTranscript({ type: "transcript.event", event });
      return;
    }

    if (event.type === "turn.finalized" || event.type === "question.detected") {
      dispatchConversation({ type: "conversation.event", event });
      return;
    }

    if (
      event.type === "answer.started" ||
      event.type === "answer.delta" ||
      event.type === "answer.completed" ||
      event.type === "answer.cancelled" ||
      event.type === "answer.superseded" ||
      event.type === "answer.failed" ||
      event.type === "answer.snapshot"
    ) {
      dispatchAnswer({ type: "answer.event", event });
      return;
    }

    if (event.type === "prediction.snapshot") {
      dispatchPrediction({ type: "prediction.event", event });
    }
  }, [releaseAudio]);

  const openTranscriptionSocket = useCallback(
    (resumeToken: string | null) =>
      new Promise<WebSocket>((resolve, reject) => {
        const socket = new WebSocket(`${WS_BASE_URL}/ws/transcribe`);
        socket.binaryType = "arraybuffer";
        socketRef.current = socket;
        let ready = false;
        let rejected = false;

        const rejectOnce = (connectionError: SessionSocketError) => {
          if (rejected || ready) return;
          rejected = true;
          reject(connectionError);
        };

        const timeout = window.setTimeout(() => {
          if (!ready) {
            rejectOnce(new SessionSocketError("Timed out while connecting to the STT backend."));
            socket.close();
          }
        }, 10_000);

        socket.onopen = () => {
          socket.send(JSON.stringify(
            resumeToken
              ? { type: "session.resume", resume_token: resumeToken }
              : { type: "session.start" },
          ));
        };

        socket.onmessage = (message) => {
          let event: ServerEvent;
          try {
            event = JSON.parse(message.data as string) as ServerEvent;
          } catch {
            if (!ready) {
              rejectOnce(new SessionSocketError("The backend returned an invalid event."));
              socket.close();
            }
            return;
          }

          if (event.type === "error" && !ready) {
            window.clearTimeout(timeout);
            rejectOnce(new SessionSocketError(`${event.code}: ${event.message}`, event.code));
            return;
          }

          processServerEvent(event);
          if (event.type === "status" && event.status === "ready" && !ready) {
            ready = true;
            window.clearTimeout(timeout);
            resolve(socket);
          }
        };

        socket.onerror = () => {
          if (!ready) {
            window.clearTimeout(timeout);
            rejectOnce(new SessionSocketError("Could not connect to ws://localhost:8000."));
          }
        };

        socket.onclose = () => {
          window.clearTimeout(timeout);
          if (socketRef.current === socket) socketRef.current = null;
          if (!ready) {
            rejectOnce(
              new SessionSocketError("The backend closed the connection before STT was ready."),
            );
            return;
          }
          dispatchPrediction({ type: "reset" });
          if (shouldReconnectRef.current && !unmountedRef.current) {
            reconnectRef.current();
          }
        };
      }),
    [processServerEvent],
  );

  const reconnect = useCallback(async () => {
    if (reconnectingRef.current || !shouldReconnectRef.current) return;
    const resumeToken = resumeTokenRef.current ?? readStoredResumeToken();
    if (!resumeToken) {
      shouldReconnectRef.current = false;
      setError("The browser connection was lost and no resume token is available.");
      setStatus("error");
      await releaseAudio();
      return;
    }

    reconnectingRef.current = true;
    setStatus("reconnecting");
    setStatusMessage(
      "Browser connection interrupted. Reconnecting; speech during this gap may be incomplete…",
    );
    let lastError: unknown = new Error("Browser reconnection failed.");

    for (let attempt = 0; attempt < BROWSER_RECONNECT_DELAYS_MS.length; attempt += 1) {
      await wait(BROWSER_RECONNECT_DELAYS_MS[attempt]);
      if (!shouldReconnectRef.current || unmountedRef.current) break;

      try {
        await openTranscriptionSocket(resumeToken);
        reconnectingRef.current = false;
        setStatus("listening");
        setStatusMessage("Previous transcription session restored.");
        return;
      } catch (caughtError) {
        lastError = caughtError;
        const code = caughtError instanceof SessionSocketError ? caughtError.code : null;
        if (!shouldRetrySessionConnection(code, attempt)) break;
      }
    }

    reconnectingRef.current = false;
    shouldReconnectRef.current = false;
    if (
      lastError instanceof SessionSocketError &&
      lastError.code === "SESSION_RESUME_UNAVAILABLE"
    ) {
      resumeTokenRef.current = null;
      clearStoredResumeToken();
    }
    setError(getErrorMessage(lastError));
    setStatus("error");
    setStatusMessage("Could not restore the transcription session.");
    await releaseAudio();
  }, [openTranscriptionSocket, releaseAudio]);

  useEffect(() => {
    reconnectRef.current = () => {
      void reconnect();
    };
  }, [reconnect]);

  const connectForStart = useCallback(async (resumeToken: string | null) => {
    if (!resumeToken) return openTranscriptionSocket(null);

    let lastError: unknown;
    for (let attempt = 0; attempt < BROWSER_RECONNECT_DELAYS_MS.length; attempt += 1) {
      if (attempt > 0) {
        await wait(BROWSER_RECONNECT_DELAYS_MS[attempt - 1]);
      }
      try {
        return await openTranscriptionSocket(resumeToken);
      } catch (caughtError) {
        lastError = caughtError;
        if (
          caughtError instanceof SessionSocketError &&
          caughtError.code === "SESSION_RESUME_UNAVAILABLE"
        ) {
          resumeTokenRef.current = null;
          clearStoredResumeToken();
          setStatusMessage("The previous session expired. Starting a new session…");
          return openTranscriptionSocket(null);
        }
        const code = caughtError instanceof SessionSocketError ? caughtError.code : null;
        if (!shouldRetrySessionConnection(code, attempt)) throw caughtError;
      }
    }
    throw lastError;
  }, [openTranscriptionSocket]);

  const start = useCallback(async () => {
    if (startingRef.current) return;
    startingRef.current = true;
    setError(null);
    dispatchTranscript({ type: "reset" });
    dispatchConversation({ type: "reset" });
    dispatchAnswer({ type: "reset" });
    dispatchPrediction({ type: "reset" });
    setStatus("connecting");
    setStatusMessage("Connecting to the Mentara AI backend…");
    shouldReconnectRef.current = true;
    lastConnectionResumedRef.current = false;
    const storedResumeToken = readStoredResumeToken();
    resumeTokenRef.current = storedResumeToken;

    try {
      const socket = await connectForStart(storedResumeToken);
      setStatus("requesting-microphone");
      setStatusMessage("Waiting for Chrome microphone permission…");

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: AUDIO_CHANNELS,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      audioRef.current.stream = stream;

      const context = new AudioContext({
        latencyHint: "interactive",
        sampleRate: AUDIO_SAMPLE_RATE,
      });
      audioRef.current.context = context;
      await context.resume();

      if (context.sampleRate !== AUDIO_SAMPLE_RATE) {
        throw new Error(
          `Chrome created ${context.sampleRate} Hz audio instead of ${AUDIO_SAMPLE_RATE} Hz.`,
        );
      }

      await context.audioWorklet.addModule("/audio/pcm16-worklet.js");
      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, "pcm16-worklet", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: AUDIO_CHANNELS,
        processorOptions: { chunkDurationMs: 100 },
      });
      const mutedOutput = context.createGain();
      mutedOutput.gain.value = 0;
      audioRef.current = { stream, context, source, worklet, mutedOutput };

      worklet.port.onmessage = (message: MessageEvent) => {
        const data = message.data as {
          type: "audio";
          buffer: ArrayBuffer;
          level: number;
        };
        if (data.type === "audio") {
          setAudioLevel(data.level);
          const activeSocket = socketRef.current;
          if (activeSocket?.readyState === WebSocket.OPEN) {
            activeSocket.send(data.buffer);
          }
        }
      };

      source.connect(worklet);
      worklet.connect(mutedOutput);
      mutedOutput.connect(context.destination);

      const activeSocket = socketRef.current ?? socket;
      if (activeSocket.readyState !== WebSocket.OPEN) {
        throw new Error("The transcription connection closed during microphone setup.");
      }
      activeSocket.send(
        JSON.stringify({
          type: "start",
          format: AUDIO_ENCODING,
          sample_rate: AUDIO_SAMPLE_RATE,
          channels: AUDIO_CHANNELS,
        }),
      );

      setStatus("listening");
      setStatusMessage(
        lastConnectionResumedRef.current
          ? "Previous transcription session restored."
          : "Listening — speak naturally into your microphone.",
      );
    } catch (caughtError) {
      shouldReconnectRef.current = false;
      await releaseAudio();
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        if (lastConnectionResumedRef.current) {
          socket.close();
        } else {
          socket.send(JSON.stringify({ type: "stop" }));
          resumeTokenRef.current = null;
          clearStoredResumeToken();
        }
      }
      socket?.close();
      socketRef.current = null;
      setError(getErrorMessage(caughtError));
      setStatus("error");
      setStatusMessage("Could not start transcription.");
    } finally {
      startingRef.current = false;
    }
  }, [connectForStart, releaseAudio]);

  const stop = useCallback(async () => {
    shouldReconnectRef.current = false;
    reconnectingRef.current = false;
    resumeTokenRef.current = null;
    clearStoredResumeToken();
    setStatus("stopping");
    setStatusMessage("Stopping the microphone and finalizing text…");
    await releaseAudio();

    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stop" }));
    } else {
      socket?.close();
      setStatus("idle");
    }
  }, [releaseAudio]);

  const checkWebSocket = useCallback(async () => {
    setConnectionCheck("checking");
    setError(null);

    try {
      await new Promise<void>((resolve, reject) => {
        const socket = new WebSocket(`${WS_BASE_URL}/ws/health`);
        const timeout = window.setTimeout(() => {
          socket.close();
          reject(new Error("WebSocket check timed out."));
        }, 5_000);

        socket.onopen = () => socket.send("ping");
        socket.onmessage = (message) => {
          const event = JSON.parse(message.data as string) as ServerEvent;
          if (event.type === "pong") {
            window.clearTimeout(timeout);
            setStatusMessage(event.message);
            socket.close();
            resolve();
          }
        };
        socket.onerror = () => {
          window.clearTimeout(timeout);
          reject(new Error("Backend WebSocket is unavailable."));
        };
      });
      setConnectionCheck("passed");
    } catch (caughtError) {
      setConnectionCheck("failed");
      setError(getErrorMessage(caughtError));
    }
  }, []);

  useEffect(() => {
    unmountedRef.current = false;
    const restoreTimer = window.setTimeout(() => {
      if (readStoredResumeToken() && !startingRef.current) {
        void start();
      }
    }, 150);

    return () => {
      unmountedRef.current = true;
      shouldReconnectRef.current = false;
      window.clearTimeout(restoreTimer);
      void releaseAudio();
      socketRef.current?.close();
    };
  }, [releaseAudio, start]);

  return {
    status,
    statusMessage,
    error,
    interimTranscript,
    finalTranscripts,
    latestTurn,
    latestDetection,
    latestDetectedTurn,
    latestAnswer,
    prediction: predictionState.current,
    likelyNext,
    audioLevel,
    connectionCheck,
    start,
    stop,
    checkWebSocket,
  };
}

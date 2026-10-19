"use client";

import { useStreamingTranscription } from "@/hooks/use-streaming-transcription";

const PIPELINE = [
  "Mic",
  "AudioWorklet",
  "PCM16",
  "WebSocket",
  "STT",
  "Transcript",
  "Turn",
  "Assist",
  "Answer",
];

const STATUS_LABELS = {
  idle: "Ready",
  connecting: "Connecting",
  "requesting-microphone": "Microphone permission",
  listening: "Live",
  reconnecting: "Reconnecting",
  degraded: "Limited connection",
  stopping: "Finalizing",
  error: "Needs attention",
} as const;

export function TranscriptionConsole() {
  const {
    status,
    statusMessage,
    error,
    interimTranscript,
    finalTranscripts,
    latestTurn,
    latestDetection,
    latestDetectedTurn,
    latestAnswer,
    prediction,
    likelyNext,
    audioLevel,
    connectionCheck,
    start,
    stop,
    checkWebSocket,
  } = useStreamingTranscription();

  const isActive =
    status === "listening" ||
    status === "reconnecting" ||
    status === "degraded";
  const isBusy =
    status === "connecting" ||
    status === "requesting-microphone" ||
    status === "stopping";
  const transcriptIsEmpty = finalTranscripts.length === 0 && !interimTranscript;

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Mentara AI home">
          <span className="brand-mark" aria-hidden="true">M</span>
          <span>Mentara <strong>AI</strong></span>
        </a>
        <div className="milestone-pill">Milestone 5.5 · Likely next</div>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow">REAL-TIME CONVERSATION COPILOT</div>
        <h1>Turn live speech into<br /><span>clear, immediate text.</span></h1>
        <p>
          Mentara captures microphone audio locally, converts it to 16 kHz PCM,
          and streams it securely through the backend for transcription.
        </p>
      </section>

      <section className="workspace-grid">
        <article className="control-card panel">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">SESSION CONTROL</p>
              <h2>Live microphone</h2>
            </div>
            <span className={`status-badge status-${status}`}>
              <span className="status-dot" />
              {STATUS_LABELS[status]}
            </span>
          </div>

          <div className={`mic-visual ${isActive ? "mic-live" : ""}`}>
            <div className="mic-ring mic-ring-outer" />
            <div className="mic-ring mic-ring-inner" />
            <div className="mic-core" aria-hidden="true">
              <span className="mic-capsule" />
              <span className="mic-stem" />
            </div>
          </div>

          <div className="level-track" aria-label="Microphone input level">
            <div
              className="level-fill"
              style={{ width: `${Math.max(2, audioLevel * 100)}%` }}
            />
          </div>

          <button
            className={`primary-button ${isActive ? "stop-button" : ""}`}
            type="button"
            onClick={isActive ? stop : start}
            disabled={isBusy}
          >
            {isBusy
              ? status === "stopping" ? "Finalizing…" : "Starting…"
              : isActive ? "Stop transcription" : "Start transcription"}
          </button>

          <p className="status-message" aria-live="polite">{statusMessage}</p>
          {error && <div className="error-box" role="alert">{error}</div>}

          <div className="connection-check">
            <div>
              <strong>Backend WebSocket</strong>
              <span>Test without using the microphone or STT credits.</span>
            </div>
            <button type="button" onClick={checkWebSocket} disabled={connectionCheck === "checking"}>
              {connectionCheck === "checking" && "Checking…"}
              {connectionCheck === "passed" && "✓ Connected"}
              {connectionCheck === "failed" && "Retry"}
              {connectionCheck === "idle" && "Run check"}
            </button>
          </div>
        </article>

        <article className="transcript-card panel">
          <div className="panel-heading transcript-heading">
            <div>
              <p className="section-kicker">STREAMING OUTPUT</p>
              <h2>Live transcript</h2>
            </div>
            <span className="format-tag">16 kHz · mono · PCM16</span>
          </div>

          <div className={`transcript-body ${transcriptIsEmpty ? "empty-transcript" : ""}`} aria-live="polite">
            {transcriptIsEmpty ? (
              <div className="empty-state">
                <span className="empty-wave" aria-hidden="true">▂▄▆▄▂</span>
                <strong>Your words will appear here</strong>
                <p>Start transcription, allow microphone access, and begin speaking.</p>
              </div>
            ) : (
              <div className="transcript-copy">
                {finalTranscripts.map((segment) => (
                  <span className="final-segment" key={segment.utterance_id}>{segment.text} </span>
                ))}
                {interimTranscript && <span className="interim-segment">{interimTranscript}</span>}
              </div>
            )}
          </div>

          <footer className="transcript-footer">
            <span><i className="legend-dot final-dot" /> Final text</span>
            <span><i className="legend-dot interim-dot" /> Partial text</span>
            <span className="segment-count">{finalTranscripts.length} final segments</span>
          </footer>
        </article>
      </section>

      <section className="analysis-section">
        <div className="analysis-heading">
          <div>
            <p className="section-kicker">CONVERSATION ANALYSIS</p>
            <h2>Meaningful assistance detection</h2>
          </div>
          <span className="format-tag">
            {latestTurn ? `Turn ${latestTurn.turn_sequence} finalized` : "Waiting for a turn"}
          </span>
        </div>
        <div className="analysis-grid">
          <div className="analysis-result">
            <span>Last meaningful {latestDetection?.kind ?? "request"}</span>
            <strong>
              {latestDetectedTurn?.text ?? "No meaningful question or request detected yet."}
            </strong>
          </div>
          <div className="analysis-metrics">
            <span>Transcript → turn</span>
            <strong>{latestTurn ? `${latestTurn.transcript_final_to_turn_ms} ms` : "—"}</strong>
            <span>Turn → detection</span>
            <strong>{latestDetection ? `${latestDetection.turn_to_detection_ms} ms` : "—"}</strong>
            <span>Continuity</span>
            <strong className={latestTurn?.continuity_quality === "degraded" ? "quality-degraded" : ""}>
              {latestTurn?.continuity_quality ?? "—"}
            </strong>
          </div>
        </div>
      </section>

      <section className="prediction-section" aria-live="polite">
        <div className="analysis-heading">
          <div>
            <p className="section-kicker">ADVISORY PREPARATION</p>
            <h2>Likely next</h2>
          </div>
          <span className={`prediction-state prediction-state-${prediction?.state ?? "idle"}`}>
            {prediction?.state === "ready"
              ? prediction.readiness ?? "Ready"
              : prediction?.state === "invalidated"
                ? "Waiting for new input"
                : prediction?.state === "failed"
                  ? "Unavailable"
                  : prediction?.state ?? "Waiting"}
          </span>
        </div>
        <p className="prediction-disclaimer">
          Bounded guesses while the current turn evolves—not detected questions,
          verified facts, or answers.
        </p>
        {likelyNext.length > 0 ? (
          <ol className="prediction-list">
            {likelyNext.map((candidate) => (
              <li key={`${candidate.kind}:${candidate.text}`}>
                <span>{candidate.kind}</span>
                <strong>{candidate.text}</strong>
              </li>
            ))}
          </ol>
        ) : (
          <p className="prediction-placeholder">
            Likely follow-ups will appear only when a bounded prediction is ready.
          </p>
        )}
      </section>

      <section className="answer-section" aria-live="polite">
        <div className="analysis-heading">
          <div>
            <p className="section-kicker">REAL-TIME ASSISTANCE</p>
            <h2>Latest answer</h2>
          </div>
          <span className={`answer-state answer-state-${latestAnswer?.state ?? "idle"}`}>
            {latestAnswer?.state ?? "Waiting"}
          </span>
        </div>
        <div className="answer-body">
          {latestAnswer?.text ? (
            <p>{latestAnswer.text}</p>
          ) : latestAnswer?.state === "failed" ? (
            <p className="answer-error">{latestAnswer.message ?? "Answer generation failed."}</p>
          ) : (
            <p className="answer-placeholder">
              {latestAnswer?.state === "starting" || latestAnswer?.state === "requested"
                ? "Preparing a concise answer…"
                : "A useful answer will stream here after a meaningful request."}
            </p>
          )}
          {latestAnswer && (
            <div className="answer-diagnostics">
              <span>
                First text: {latestAnswer.questionDetectedToFirstTextMs !== null
                  ? `${latestAnswer.questionDetectedToFirstTextMs} ms`
                  : "—"}
              </span>
              <span>
                Total: {latestAnswer.answerGenerationTotalMs !== null
                  ? `${latestAnswer.answerGenerationTotalMs} ms`
                  : "—"}
              </span>
            </div>
          )}
        </div>
      </section>

      <section className="pipeline-section">
        <div>
          <p className="section-kicker">ACTIVE PIPELINE</p>
          <h2>Every stage is independently testable.</h2>
        </div>
        <ol className="pipeline-list">
          {PIPELINE.map((stage, index) => (
            <li key={stage}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{stage}</strong>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

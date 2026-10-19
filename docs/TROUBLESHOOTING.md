# Mentara AI troubleshooting

Diagnose the earliest failing stage. Do not change the architecture until that
stage is understood.

## Browser reconnection does not restore the transcript

- Reconnect or refresh within 30 seconds of the browser WebSocket interruption.
- Keep the same browser tab; the opaque resume token is stored in tab-scoped
  session storage and is not shared with a new tab.
- Do not restart the backend during the checkpoint because its registry is
  intentionally in memory.
- If Chrome blocks automatic microphone restart after refresh, select Start once
  inside the 30-second grace period.
- `SESSION_RESUME_UNAVAILABLE` means the token expired or the backend restarted.
  Start again to create a clean new logical session.
- `SESSION_ALREADY_ATTACHED` is normally temporary; the frontend retries it with
  bounded backoff while the prior socket releases its lease.

## `setup.bat` fails

- `No suitable Python runtime found`: run `py -0p`. Python 3.11 must appear.
- `npm was not found`: close VS Code, reopen it, and run `node --version`.
- Package-download errors: confirm normal internet access, then rerun `setup.bat`.
  The script safely reuses completed work.

## Backend does not start

- Run `start-backend.bat` from the project root.
- `Address already in use`: another program is using port 8000. In Command Prompt,
  run `netstat -ano | findstr :8000`, then identify that PID in Task Manager.
- Import error: rerun `setup.bat`; do not install random packages globally.

## Health endpoint fails

Open `http://localhost:8000/api/health`.

- Browser cannot connect: backend terminal is not running or port 8000 is blocked.
- `stt_configured` is `false`: run `configure-gemini.bat`, enter the key, and
  restart the backend.
- `stt_provider` is not `gemini`: run `configure-gemini.bat` again.

## WebSocket check fails

- Confirm the backend terminal shows `Uvicorn running on http://127.0.0.1:8000`.
- Confirm `frontend/.env.local` contains `NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000`.
- Restart the frontend after changing `.env.local`.
- Browser extensions, VPNs, or corporate security software may block localhost
  WebSockets; test once in a normal Chrome window with extensions disabled.

## Chrome never asks for microphone permission

1. Open `chrome://settings/content/microphone`.
2. Confirm a working input device is selected.
3. Remove any existing block for `http://localhost:3000`.
4. Reload Mentara AI and select **Start transcription** again.

The microphone is requested only after the STT WebSocket becomes ready. Therefore,
an STT/API-key error must be fixed before Chrome displays its microphone prompt.

## The level moves but no text appears

- The microphone and AudioWorklet are working; focus on the provider connection.
- Inspect the backend terminal for `400`, `401`, `403`, `429`, model, or quota errors.
- Verify the Gemini API key is active in Google AI Studio and has Gemini Developer
  API free-tier quota. Google AI Pro subscription limits and API quota are separate.
- Speak continuously for two or three seconds and then pause briefly.

## Text appears but is slow to become final

Partial text is expected to change while speaking. A final segment is produced
after Gemini server-side VAD detects a pause.

## Gemini-specific errors

- `STT_NOT_CONFIGURED`: run `configure-gemini.bat`, then restart the backend.
- `401` or `403`: the key is invalid, restricted incorrectly, or the API is not
  available to that Google AI Studio project. Create or repair the key there.
- `429` or `RESOURCE_EXHAUSTED`: the project reached its API quota. Wait for quota
  reset or inspect the project's Gemini API usage; do not repeatedly retry rapidly.
- WebSocket close code `1008`: inspect the accompanying provider message for model,
  account, region, or request-validation details.
- Session ends near 10 minutes: Phase B2 should rotate the provider connection
  before this limit while retaining the Mentara transcript. Confirm the current
  package is installed and `GEMINI_ROTATION_ENABLED` is not `false`.
- `Limited connection` appears: Mentara continued but could not guarantee recent
  audio continuity, usually because a final boundary was unavailable or the
  two-second reconnect buffer filled. Pause briefly, confirm text resumes, and
  treat the words around the warning as potentially incomplete.
- Repeated reconnect failure: `401`, `403` and `429` are intentionally not
  retried. Temporary network and server failures use only bounded retries; fix
  the reported cause rather than repeatedly restarting the session.

Use only non-sensitive/demo speech while testing the free tier because free-tier
content may be used by Google to improve its products.

## Transcript works but no answer appears

- Confirm the conversation panel shows a meaningful request. A normal statement
  intentionally creates no model call.
- If the panel says no meaningful request was detected, inspect the finalized
  transcript wording. The local detector supports bounded explicit question and
  request forms; broad implicit intent is not yet a model classifier.
- Confirm `ANSWER_GENERATION_ENABLED=true` and `ANSWER_PROVIDER=gemini` in
  `backend/.env`, then restart the backend.
- `ANSWER_NOT_CONFIGURED` means answer generation is enabled but the backend key
  or provider configuration is unavailable. M1–M3 should remain usable.
- A `failed` answer reports only a sanitized category. Use the backend terminal
  and the one-request diagnostic script for status/category evidence; do not
  repeatedly run the eight-request benchmark while configuration is failing.

## Hidden API-key prompt rejects the key

Use right-click or Shift+Insert at the hidden `configure-gemini.bat` prompt.
Some Windows raw-console hosts interpret Ctrl+V as the control character U+0016
instead of pasting. The script now rejects control characters and implausible
lengths so that malformed input is not silently written. Never send the key or a
full diagnostic exception to chat.

## Answer is cancelled or superseded

- `superseded` is expected when another meaningful request arrives while the
  previous answer is active; latest meaningful request wins.
- `cancelled` is expected after Stop, reset or terminal session cleanup. Already
  visible partial text remains, no later delta is accepted and completion-total
  latency is intentionally absent.
- Refresh within 30 seconds replays the same answer identity and must not create
  another model request. After expiry or backend restart, start a new session.

## Answer latency varies

The UI's first-text/total values include provider and network time. Local M3
timings are shown separately. The M4 benchmark selected Flash-Lite for lower
median latency/cost, but individual real requests can still vary materially.
Do not add retries, speculative generation or two-pass answers solely from one
slow sample; measure a controlled corpus first.

## Feedback or echo

Mentara connects the worklet through a zero-gain node so captured microphone audio
is not played through speakers. If echo still appears, verify no other recording
application is monitoring the microphone.

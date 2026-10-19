# Milestone 5 Phase G — target-Windows checkpoint

This is the only manual checkpoint required for M5. It should take only a few
minutes and uses the existing configured Gemini account plus a physical
microphone.

## Start

1. Extract the Phase-F checkpoint to a new folder.
2. Double-click `m5-checkpoint.bat`.
3. If dependencies are absent, the helper runs setup automatically.
4. If `backend/.env` is absent, enter the Gemini key in the hidden configuration
   prompt. Do not paste the key into chat, screenshots or logs.
5. Wait for `All automated checks passed.` The helper then opens backend and
   frontend server windows; leave both running.
6. Open Chrome at `http://localhost:3000` and allow microphone permission.

## Short product check

1. Begin transcription.
2. Establish a topic over a few turns, for example: “We use Redis as our caching
   layer for low-latency session reads.”
3. Ask “Why?” Confirm the answer uses that recent topic.
4. Speak four or five unrelated ordinary statements so Redis leaves the default
   recent window.
5. Ask “Coming back to Redis, why not use DynamoDB?” Confirm the answer reflects
   the earlier Redis context.
6. Say an ordinary statement. Confirm it does not create an unnecessary answer.
7. Refresh Chrome. Confirm the logical session, transcript and answers restore
   without a duplicate provider request.
8. Ask another short follow-up and confirm it uses the resumed context.
9. Click Stop. Confirm the microphone indicator releases and neither server
   window shows an unhandled exception.

## Result to return

Reply with one compact line:

`M5 Windows checkpoint: PASS — verify passed; recent follow-up passed; older-topic return passed; ordinary statement produced no answer; refresh/resume had no duplicate; post-resume follow-up passed; Stop released microphone; no unhandled exception.`

If anything fails, replace `PASS` with `FAIL` and state only which numbered step
failed plus the visible safe error. Never send an API key or `.env` file.

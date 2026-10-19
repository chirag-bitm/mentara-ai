import assert from "node:assert/strict";
import test from "node:test";

import {
  BROWSER_RECONNECT_DELAYS_MS,
  shouldRetrySessionConnection,
} from "../src/lib/reconnect-policy";


test("browser reconnect uses a bounded five-attempt backoff", () => {
  assert.deepEqual(BROWSER_RECONNECT_DELAYS_MS, [250, 500, 1_000, 2_000, 4_000]);
  assert.equal(shouldRetrySessionConnection(null, 0), true);
  assert.equal(shouldRetrySessionConnection(null, 4), false);
});


test("only a still-attached session error is retried", () => {
  assert.equal(shouldRetrySessionConnection("SESSION_ALREADY_ATTACHED", 0), true);
  assert.equal(shouldRetrySessionConnection("SESSION_RESUME_UNAVAILABLE", 0), false);
  assert.equal(shouldRetrySessionConnection("STT_CONNECTION_ERROR", 0), false);
});

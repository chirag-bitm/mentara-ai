export const BROWSER_RECONNECT_DELAYS_MS = [250, 500, 1_000, 2_000, 4_000] as const;

export const RETRYABLE_SESSION_ERROR_CODES = new Set([
  "SESSION_ALREADY_ATTACHED",
]);

export function shouldRetrySessionConnection(
  errorCode: string | null,
  attemptIndex: number,
): boolean {
  if (attemptIndex >= BROWSER_RECONNECT_DELAYS_MS.length - 1) return false;
  if (errorCode === null) return true;
  return RETRYABLE_SESSION_ERROR_CODES.has(errorCode);
}

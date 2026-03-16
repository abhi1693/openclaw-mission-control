export type ExponentialBackoffOptions = {
  baseMs?: number;
  factor?: number;
  maxMs?: number;
  jitter?: number;
};

export type ExponentialBackoff = {
  nextDelayMs: () => number;
  reset: () => void;
  attempt: () => number;
};

const clampMs = (
  value: number,
  { min, max }: { min: number; max: number },
): number => {
  if (Number.isNaN(value) || !Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.trunc(value)));
};

export const createExponentialBackoff = (
  options: ExponentialBackoffOptions = {},
): ExponentialBackoff => {
  const baseMs = clampMs(options.baseMs ?? 1_000, { min: 50, max: 60_000 });
  const factor = options.factor ?? 2;
  const maxMs = clampMs(options.maxMs ?? 5 * 60_000, {
    min: baseMs,
    max: 60 * 60_000,
  });
  const jitter = options.jitter ?? 0.2;

  let attempt = 0;

  return {
    nextDelayMs: () => {
      const raw = baseMs * Math.pow(factor, attempt);
      const capped = Math.min(maxMs, raw);
      const normalized = clampMs(capped, { min: baseMs, max: maxMs });

      // K8s-style jitter: only add extra random delay (no negative jitter),
      // which avoids thundering-herd reconnects.
      const jitterFactor = Math.max(0, jitter);
      const delay =
        normalized + Math.floor(Math.random() * jitterFactor * normalized);

      attempt = Math.min(attempt + 1, 64);
      return clampMs(delay, { min: baseMs, max: maxMs });
    },
    reset: () => {
      attempt = 0;
    },
    attempt: () => attempt,
  };
};

import { createExponentialBackoff } from "./backoff";

describe("createExponentialBackoff", () => {
  it("uses default options", () => {
    const backoff = createExponentialBackoff();
    expect(backoff.attempt()).toBe(0);
    const delay = backoff.nextDelayMs();
    expect(delay).toBeGreaterThanOrEqual(50);
    expect(backoff.attempt()).toBe(1);
  });

  it("clamps invalid base/max and increments attempt", () => {
    const backoff = createExponentialBackoff({
      baseMs: Number.NaN,
      maxMs: Number.POSITIVE_INFINITY,
      factor: 2,
      jitter: 0,
    });

    expect(backoff.attempt()).toBe(0);
    const d1 = backoff.nextDelayMs();
    // baseMs clamps to min 50
    expect(d1).toBe(50);
    expect(backoff.attempt()).toBe(1);

    const d2 = backoff.nextDelayMs();
    // maxMs=+Inf is treated as invalid and clamped to baseMs, so it will cap immediately.
    expect(d2).toBe(50);
    expect(backoff.attempt()).toBe(2);

    backoff.reset();
    expect(backoff.attempt()).toBe(0);
  });

  it("applies positive jitter (extra delay only)", () => {
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0.5);

    const backoff = createExponentialBackoff({
      baseMs: 1000,
      factor: 2,
      maxMs: 2000,
      jitter: 0.2,
    });

    // attempt=0 => normalized=1000 => delay = 1000 + floor(0.5*0.2*1000)=1100
    expect(backoff.nextDelayMs()).toBe(1100);

    // attempt=1 => raw=2000 capped=2000 => delay=2000 + floor(0.5*0.2*2000)=2200 but clamped to maxMs (2000)
    expect(backoff.nextDelayMs()).toBe(2000);

    randomSpy.mockRestore();
  });

  it("treats negative jitter as zero", () => {
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0.999);

    const backoff = createExponentialBackoff({
      baseMs: 100,
      factor: 2,
      maxMs: 1000,
      jitter: -1,
    });

    expect(backoff.nextDelayMs()).toBe(100);
    randomSpy.mockRestore();
  });
});

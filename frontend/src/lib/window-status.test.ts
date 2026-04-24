import { getWindowStatus, windowExpiresInMs, formatTimeRemaining } from "./window-status";

describe("getWindowStatus", () => {
  const now = new Date();

  test("returns n/a for evolution provider", () => {
    expect(getWindowStatus(now.toISOString(), "evolution")).toBe("n/a");
  });

  test("returns n/a for null provider", () => {
    expect(getWindowStatus(now.toISOString(), null)).toBe("n/a");
  });

  test("returns closed when last_customer_message_at is null", () => {
    expect(getWindowStatus(null, "meta_cloud")).toBe("closed");
  });

  test("returns open when message is 1 hour ago", () => {
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    expect(getWindowStatus(oneHourAgo, "meta_cloud")).toBe("open");
  });

  test("returns expiring when message is 23 hours ago", () => {
    const twentyThreeHoursAgo = new Date(Date.now() - 23 * 60 * 60 * 1000).toISOString();
    expect(getWindowStatus(twentyThreeHoursAgo, "meta_cloud")).toBe("expiring");
  });

  test("returns closed when message is 25 hours ago", () => {
    const twentyFiveHoursAgo = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    expect(getWindowStatus(twentyFiveHoursAgo, "meta_cloud")).toBe("closed");
  });

  test("returns expiring at exactly 22h boundary", () => {
    const twentyTwoHoursAgo = new Date(Date.now() - 22 * 60 * 60 * 1000).toISOString();
    expect(getWindowStatus(twentyTwoHoursAgo, "meta_cloud")).toBe("expiring");
  });
});

describe("windowExpiresInMs", () => {
  test("returns 0 when window already expired", () => {
    const expired = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
    expect(windowExpiresInMs(expired)).toBe(0);
  });

  test("returns positive ms when window is still open", () => {
    const oneHourAgo = new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString();
    const remaining = windowExpiresInMs(oneHourAgo);
    expect(remaining).toBeGreaterThan(0);
    // Should be ~23 hours in ms
    expect(remaining).toBeLessThanOrEqual(23 * 60 * 60 * 1000 + 5000);
  });
});

describe("formatTimeRemaining", () => {
  test("formats hours and minutes", () => {
    const twoHoursThirty = 2.5 * 60 * 60 * 1000;
    expect(formatTimeRemaining(twoHoursThirty)).toBe("2h 30min");
  });

  test("formats minutes only when less than 1 hour", () => {
    const fortyFiveMin = 45 * 60 * 1000;
    expect(formatTimeRemaining(fortyFiveMin)).toBe("45min");
  });

  test("returns 0min for expired window (0ms)", () => {
    expect(formatTimeRemaining(0)).toBe("0min");
  });
});

import { getWindowStatus } from "./window-status";

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

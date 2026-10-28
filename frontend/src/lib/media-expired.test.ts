import { describe, it, expect } from "vitest";
import { isMediaExpired } from "./media-expired";

const NOW = new Date("2026-10-27T12:00:00Z");
const dias = (n: number) => new Date(NOW.getTime() - n * 86400000).toISOString();

describe("isMediaExpired", () => {
  it("metadata.media_expired = true → expirado", () => {
    expect(isMediaExpired({ media_url: "https://x/a.jpg", metadata: { media_expired: true }, created_at: dias(1) }, NOW)).toBe(true);
  });
  it("media_id legado da Meta com mais de 7 dias → expirado", () => {
    expect(isMediaExpired({ media_url: "2302234720561889", created_at: dias(8) }, NOW)).toBe(true);
  });
  it("media_id recente → não expirado", () => {
    expect(isMediaExpired({ media_url: "2302234720561889", created_at: dias(2) }, NOW)).toBe(false);
  });
  it("URL do Storage antiga sem marca → não expirado", () => {
    expect(isMediaExpired({ media_url: "https://x/a.jpg", created_at: dias(300) }, NOW)).toBe(false);
  });
  it("blob: e sem media_url → não expirado", () => {
    expect(isMediaExpired({ media_url: "blob:abc", created_at: dias(30) }, NOW)).toBe(false);
    expect(isMediaExpired({ media_url: null, created_at: dias(30) }, NOW)).toBe(false);
  });
});

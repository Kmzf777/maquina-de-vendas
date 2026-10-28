import { describe, it, expect } from "vitest";
import { isMediaExpired } from "./media-expired";

const NOW = new Date("2026-10-27T12:00:00Z");
const dias = (n: number) => new Date(NOW.getTime() - n * 86400000).toISOString();

describe("isMediaExpired", () => {
  it("metadata.media_expired = true → expirado", () => {
    expect(isMediaExpired({ media_url: "https://x/a.jpg", metadata: { media_expired: true }, created_at: dias(1) }, NOW)).toBe(true);
  });
  it("media_id que o CLIENTE mandou com mais de 7 dias → expirado", () => {
    expect(isMediaExpired({ media_url: "2302234720561889", sent_by: "user", created_at: dias(8) }, NOW)).toBe(true);
    expect(isMediaExpired({ media_url: "2302234720561889", role: "user", created_at: dias(8) }, NOW)).toBe(true);
  });
  it("media_id do cliente recente → não expirado", () => {
    expect(isMediaExpired({ media_url: "2302234720561889", sent_by: "user", created_at: dias(2) }, NOW)).toBe(false);
  });
  it("media_id enviado por nós (vendedor/robô) dura ~30 dias na Meta", () => {
    for (const quem of [
      { role: "assistant", sent_by: "seller" },
      { role: "assistant", sent_by: "agent" },
      { role: "assistant", sent_by: null },
    ]) {
      expect(isMediaExpired({ media_url: "2302234720561889", ...quem, created_at: dias(8) }, NOW)).toBe(false);
      expect(isMediaExpired({ media_url: "2302234720561889", ...quem, created_at: dias(29) }, NOW)).toBe(false);
      expect(isMediaExpired({ media_url: "2302234720561889", ...quem, created_at: dias(31) }, NOW)).toBe(true);
    }
  });
  it("URL do Storage antiga sem marca → não expirado", () => {
    expect(isMediaExpired({ media_url: "https://x/a.jpg", created_at: dias(300) }, NOW)).toBe(false);
  });
  it("blob: e sem media_url → não expirado", () => {
    expect(isMediaExpired({ media_url: "blob:abc", created_at: dias(30) }, NOW)).toBe(false);
    expect(isMediaExpired({ media_url: null, created_at: dias(30) }, NOW)).toBe(false);
  });
});

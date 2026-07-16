import { describe, it, expect } from "vitest";
import { describeOutboundMediaContent } from "@/lib/media-message-content";

describe("describeOutboundMediaContent", () => {
  it("audio → [áudio]", () => {
    expect(describeOutboundMediaContent("audio", "gravacao.ogg")).toBe("[áudio]");
  });
  it("image → [imagem]", () => {
    expect(describeOutboundMediaContent("image", "foto.jpg")).toBe("[imagem]");
  });
  it("video → [vídeo]", () => {
    expect(describeOutboundMediaContent("video", "clipe.mp4")).toBe("[vídeo]");
  });
  it("document → mantém o nome original do arquivo", () => {
    expect(describeOutboundMediaContent("document", "contrato.pdf")).toBe("contrato.pdf");
  });
});

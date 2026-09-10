import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { isTextualPreview, mediaPreviewLabel, previewText } from "@/lib/message-preview";

describe("isTextualPreview", () => {
  it("clique em botão é texto para efeito de preview", () => {
    expect(isTextualPreview("button")).toBe(true);
  });

  it("texto e legado sem message_type continuam texto", () => {
    expect(isTextualPreview("text")).toBe(true);
    expect(isTextualPreview(null)).toBe(true);
    expect(isTextualPreview(undefined)).toBe(true);
  });

  it("mídia de verdade não é texto", () => {
    for (const tipo of ["image", "audio", "video", "document", "sticker", "location", "contact"]) {
      expect(isTextualPreview(tipo), tipo).toBe(false);
    }
  });
});

describe("mediaPreviewLabel", () => {
  it("cobre os mesmos tipos de message-bubble.tsx:66-77, inclusive location/contact", () => {
    expect(mediaPreviewLabel("image")).toBe("📷 Imagem");
    expect(mediaPreviewLabel("audio")).toBe("🎵 Áudio");
    expect(mediaPreviewLabel("video")).toBe("🎬 Vídeo");
    expect(mediaPreviewLabel("document")).toBe("📄 Documento");
    expect(mediaPreviewLabel("sticker")).toBe("😀 Figurinha");
    // O mapa inline de chat-view.tsx:733-739 não tinha estes dois: caíam em "📎 Mídia".
    expect(mediaPreviewLabel("location")).toBe("📍 Localização");
    expect(mediaPreviewLabel("contact")).toBe("👤 Contato");
  });

  it("tipo desconhecido cai no genérico", () => {
    expect(mediaPreviewLabel("holograma")).toBe("📎 Mídia");
  });
});

describe("previewText", () => {
  it("REPRO: responder a um clique em botão mostra o rótulo, não '📎 Mídia'", () => {
    // Cenário do dossiê: o lead toca "Quero repor meu estoque" no primeiro toque da
    // recuperação e o vendedor clica em responder. Antes da correção a barra de resposta
    // do chat-view.tsx caía no mapa inline (tudo != 'text' era mídia) e exibia "📎 Mídia".
    expect(
      previewText({ message_type: "button", content: "Quero repor meu estoque" })
    ).toBe("Quero repor meu estoque");
  });

  it("mídia continua mostrando o rótulo de mídia", () => {
    expect(previewText({ message_type: "audio", content: "" })).toBe("🎵 Áudio");
    expect(previewText({ message_type: "image", content: null })).toBe("📷 Imagem");
  });

  it("texto normal e legado sem tipo mostram o content", () => {
    expect(previewText({ message_type: "text", content: "bom dia" })).toBe("bom dia");
    expect(previewText({ content: "clique gravado antes do parser novo" })).toBe(
      "clique gravado antes do parser novo"
    );
  });

  it("content nulo não vira 'null' na tela", () => {
    expect(previewText({ message_type: "text", content: null })).toBe("");
  });
});

// vitest roda com cwd = frontend/ (mesma premissa de src/lib/auth/proxy-coverage.test.ts).
const CHAT_VIEW = path.resolve(
  process.cwd(),
  "src/components/conversas/chat-view.tsx"
);

describe("terceiro call-site: barra de resposta do chat-view", () => {
  const fonte = fs.readFileSync(CHAT_VIEW, "utf8");

  it("usa previewText em vez do mapa de mídia inline", () => {
    // Guarda de regressão: o defeito foi exatamente um call-site esquecido. Se alguém
    // reintroduzir o mapa inline, este teste cai antes de o operador ver "📎 Mídia".
    expect(fonte).toContain("previewText(replyingTo)");
    expect(fonte).not.toContain('"📎 Mídia"');
    expect(fonte).not.toMatch(/replyingTo\.message_type\s*!==\s*"text"/);
  });
});

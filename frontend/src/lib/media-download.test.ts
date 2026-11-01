import { describe, it, expect } from "vitest";
import { mediaDownloadHref, mediaFileName, documentPreviewKind } from "./media-download";

describe("mediaFileName", () => {
  it("usa o nome do arquivo quando existe", () => {
    expect(mediaFileName("document", "Pedido Café.pdf")).toBe("Pedido Café.pdf");
  });
  it("cai no nome padrão por tipo quando não há nome", () => {
    expect(mediaFileName("document", null)).toBe("documento");
    expect(mediaFileName("image", undefined)).toBe("imagem.jpg");
    expect(mediaFileName("video", "")).toBe("video.mp4");
    expect(mediaFileName("audio", "   ")).toBe("audio.ogg");
  });
});

describe("mediaDownloadHref", () => {
  it("URL do Storage ganha ?download=<nome> (o Storage responde como anexo)", () => {
    const href = mediaDownloadHref(
      "https://supabase.canastrainteligencia.com/storage/v1/object/public/media/a/b.pdf",
      "Pedido Café.pdf",
    );
    const u = new URL(href);
    expect(u.origin + u.pathname).toBe(
      "https://supabase.canastrainteligencia.com/storage/v1/object/public/media/a/b.pdf",
    );
    expect(u.searchParams.get("download")).toBe("Pedido Café.pdf");
  });
  it("proxy /api/media ganha download=1 e filename, mantendo os parâmetros", () => {
    const href = mediaDownloadHref("/api/media?media_id=123&conversation_id=conv-1", "nota.pdf");
    const u = new URL(href, "http://x");
    expect(u.pathname).toBe("/api/media");
    expect(u.searchParams.get("media_id")).toBe("123");
    expect(u.searchParams.get("conversation_id")).toBe("conv-1");
    expect(u.searchParams.get("download")).toBe("1");
    expect(u.searchParams.get("filename")).toBe("nota.pdf");
    expect(href.startsWith("/api/media?")).toBe(true);
  });
  it("blob: volta igual (o download vem do atributo download do link)", () => {
    expect(mediaDownloadHref("blob:http://localhost/abc", "x.pdf")).toBe("blob:http://localhost/abc");
  });
});

describe("documentPreviewKind", () => {
  it("nome terminado em .pdf → pdf (qualquer caixa)", () => {
    expect(documentPreviewKind("Nota Fiscal.PDF")).toBe("pdf");
  });
  it("sem nome → pdf (a base mostra que quase todos são PDF)", () => {
    expect(documentPreviewKind(null)).toBe("pdf");
    expect(documentPreviewKind("")).toBe("pdf");
  });
  it("outros formatos → file (sem prévia, só Baixar)", () => {
    expect(documentPreviewKind("arte.psd")).toBe("file");
    expect(documentPreviewKind("apresentacao.pptx")).toBe("file");
    expect(documentPreviewKind("video.mp4")).toBe("file");
  });
});

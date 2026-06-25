import { describe, it, expect } from "vitest";
import { resolveSearchChannelScope, highlightSegments } from "./message-search";

describe("resolveSearchChannelScope", () => {
  it("admin sem channel_id => null (sem restrição)", () => {
    expect(resolveSearchChannelScope(null, null)).toEqual({ kind: "all" });
  });
  it("admin com channel_id => restringe a esse canal", () => {
    expect(resolveSearchChannelScope(null, "ch1")).toEqual({ kind: "ids", ids: ["ch1"] });
  });
  it("vendedor sem channel_id => seus canais", () => {
    expect(resolveSearchChannelScope(["a", "b"], null)).toEqual({ kind: "ids", ids: ["a", "b"] });
  });
  it("vendedor com channel_id permitido => só esse", () => {
    expect(resolveSearchChannelScope(["a", "b"], "a")).toEqual({ kind: "ids", ids: ["a"] });
  });
  it("vendedor com channel_id NÃO permitido => vazio (bloqueia)", () => {
    expect(resolveSearchChannelScope(["a", "b"], "c")).toEqual({ kind: "empty" });
  });
  it("vendedor sem canais => vazio", () => {
    expect(resolveSearchChannelScope([], null)).toEqual({ kind: "empty" });
  });
});

describe("highlightSegments", () => {
  it("sem query => um segmento não-match", () => {
    expect(highlightSegments("Olá mundo", "")).toEqual([{ text: "Olá mundo", match: false }]);
  });
  it("match simples preserva texto original", () => {
    expect(highlightSegments("Quero um café agora", "cafe")).toEqual([
      { text: "Quero um ", match: false },
      { text: "café", match: true },
      { text: " agora", match: false },
    ]);
  });
  it("case-insensitive", () => {
    expect(highlightSegments("PRECO bom", "preco")).toEqual([
      { text: "PRECO", match: true },
      { text: " bom", match: false },
    ]);
  });
  it("múltiplas ocorrências", () => {
    expect(highlightSegments("oi oi", "oi")).toEqual([
      { text: "oi", match: true },
      { text: " ", match: false },
      { text: "oi", match: true },
    ]);
  });
  it("sem ocorrência => um segmento", () => {
    expect(highlightSegments("nada", "xyz")).toEqual([{ text: "nada", match: false }]);
  });
});

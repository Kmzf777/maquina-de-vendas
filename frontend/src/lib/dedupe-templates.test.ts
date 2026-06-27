import { describe, it, expect } from "vitest";
import { dedupeTemplatesByNameLang } from "@/lib/dedupe-templates";

describe("dedupeTemplatesByNameLang", () => {
  it("colapsa cópias por canal do mesmo (name, language) — WABA compartilhada", () => {
    // 3 canais (mesma WABA) → 3 linhas-espelho do mesmo template.
    const rows = [
      { id: "1", name: "continuar_conversa", language: "pt_BR", status: "approved", channel_id: "c1" },
      { id: "2", name: "continuar_conversa", language: "pt_BR", status: "approved", channel_id: "c2" },
      { id: "3", name: "continuar_conversa", language: "pt_BR", status: "approved", channel_id: "c3" },
    ];
    const result = dedupeTemplatesByNameLang(rows);
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("continuar_conversa");
  });

  it("mantém variações de idioma como entradas distintas", () => {
    const rows = [
      { id: "1", name: "promo", language: "pt_BR", status: "approved", channel_id: "c1" },
      { id: "2", name: "promo", language: "en_US", status: "approved", channel_id: "c1" },
    ];
    expect(dedupeTemplatesByNameLang(rows)).toHaveLength(2);
  });

  it("prefere uma linha não-cancelada sobre uma cancelada do mesmo nome/idioma", () => {
    const rows = [
      { id: "1", name: "t", language: "pt_BR", status: "cancelled", channel_id: "c1" },
      { id: "2", name: "t", language: "pt_BR", status: "approved", channel_id: "c2" },
    ];
    const result = dedupeTemplatesByNameLang(rows);
    expect(result).toHaveLength(1);
    expect(result[0].status).toBe("approved");
  });

  it("preserva a primeira não-cancelada quando há mais de uma (ordem estável)", () => {
    const rows = [
      { id: "1", name: "t", language: "pt_BR", status: "approved", channel_id: "c1" },
      { id: "2", name: "t", language: "pt_BR", status: "approved", channel_id: "c2" },
    ];
    const result = dedupeTemplatesByNameLang(rows);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("1");
  });

  it("não altera uma lista já sem duplicatas", () => {
    const rows = [
      { id: "1", name: "a", language: "pt_BR", status: "approved", channel_id: "c1" },
      { id: "2", name: "b", language: "pt_BR", status: "approved", channel_id: "c1" },
    ];
    expect(dedupeTemplatesByNameLang(rows)).toHaveLength(2);
  });

  it("retorna vazio para lista vazia", () => {
    expect(dedupeTemplatesByNameLang([])).toEqual([]);
  });
});

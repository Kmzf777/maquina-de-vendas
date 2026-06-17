// frontend/src/lib/quick-replies.test.ts
import { describe, it, expect } from "vitest";
import { getSlashQuery, applyQuickReply, filterQuickReplies } from "@/lib/quick-replies";
import type { QuickReply } from "@/lib/types";

const make = (p: Partial<QuickReply>): QuickReply => ({
  id: "1", shortcut: null, title: "", content: "",
  created_at: "", updated_at: "", ...p,
});

describe("getSlashQuery", () => {
  it("abre no '/' isolado", () => {
    expect(getSlashQuery("/", 1)).toEqual({ query: "", start: 0 });
  });
  it("captura o texto após a '/'", () => {
    expect(getSlashQuery("/saud", 5)).toEqual({ query: "saud", start: 0 });
  });
  it("abre após espaço", () => {
    expect(getSlashQuery("oi /sa", 6)).toEqual({ query: "sa", start: 3 });
  });
  it("não abre no meio de palavra (e/ou)", () => {
    expect(getSlashQuery("e/ou", 4)).toBeNull();
  });
  it("não abre em URL (http://)", () => {
    expect(getSlashQuery("http://x", 8)).toBeNull();
  });
  it("fecha ao digitar espaço depois do token", () => {
    expect(getSlashQuery("/sa ", 4)).toBeNull();
  });
});

describe("applyQuickReply", () => {
  it("substitui '/token' isolado pelo conteúdo", () => {
    expect(applyQuickReply("/saud", 5, 0, "Olá!")).toEqual({ text: "Olá!", caret: 4 });
  });
  it("preserva texto antes e depois do trecho", () => {
    expect(applyQuickReply("oi /sa fim", 6, 3, "X")).toEqual({ text: "oi X fim", caret: 4 });
  });
});

describe("filterQuickReplies", () => {
  const items = [
    make({ id: "a", shortcut: "saud", title: "Saudação", content: "Olá tudo bem" }),
    make({ id: "b", shortcut: "cond", title: "Condições", content: "Pagamento" }),
  ];
  it("query vazia retorna tudo", () => {
    expect(filterQuickReplies(items, "")).toHaveLength(2);
  });
  it("filtra por shortcut/título/conteúdo (case-insensitive)", () => {
    expect(filterQuickReplies(items, "SAUD").map((i) => i.id)).toEqual(["a"]);
    expect(filterQuickReplies(items, "pagamento").map((i) => i.id)).toEqual(["b"]);
  });
});

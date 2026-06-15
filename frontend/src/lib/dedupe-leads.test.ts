import { describe, it, expect } from "vitest";
import { dedupeByPhone } from "@/lib/dedupe-leads";

describe("dedupeByPhone", () => {
  it("mantém apenas a primeira ocorrência de cada telefone", () => {
    const items = [
      { phone: "5531999990001", name: "Primeiro" },
      { phone: "5531999990002", name: "Outro" },
      { phone: "5531999990001", name: "Repetido" },
    ];
    const result = dedupeByPhone(items);
    expect(result).toEqual([
      { phone: "5531999990001", name: "Primeiro" },
      { phone: "5531999990002", name: "Outro" },
    ]);
  });

  it("não altera uma lista já sem duplicatas", () => {
    const items = [{ phone: "5531999990001" }, { phone: "5531999990002" }];
    expect(dedupeByPhone(items)).toEqual(items);
  });

  it("retorna vazio para lista vazia", () => {
    expect(dedupeByPhone([])).toEqual([]);
  });
});

import { describe, expect, it } from "vitest";
import { conversationSelect } from "./conversation-enrichment";

/** Campos do join `leads(...)` do select das conversas. */
function camposDoLead(select: string): string[] {
  const m = select.match(/leads(?:!inner)?\(([^)]*)\)/);
  return (m?.[1] ?? "").split(",").map((c) => c.trim());
}

describe("conversationSelect — lead", () => {
  it("traz o endereço estruturado para a aba Perfil da conversa", () => {
    const campos = camposDoLead(conversationSelect());
    for (const c of ["cep", "logradouro", "numero", "complemento", "bairro", "municipio", "uf", "endereco"]) {
      expect(campos).toContain(c);
    }
  });

  it("o INNER JOIN da busca usa os mesmos campos do lead", () => {
    expect(camposDoLead(conversationSelect({ innerLead: true }))).toEqual(camposDoLead(conversationSelect()));
  });
});

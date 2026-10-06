import { describe, it, expect } from "vitest";
import {
  foldText,
  leadMatchesSearch,
  dealMatchesSearch,
  buildAccentInsensitivePattern,
  buildLeadSearchOrFilter,
  searchTokens,
  buildDigitsPattern,
} from "./search";

describe("foldText", () => {
  it("strips diacritics and lowercases", () => {
    expect(foldText("José Açaí")).toBe("jose acai");
    expect(foldText("CAÇAPAVA")).toBe("cacapava");
  });
});

describe("leadMatchesSearch", () => {
  const lead = {
    name: "José da Silva",
    phone: "5534999998888",
    company: "Café Canastra",
    razao_social: "Canastra Comércio LTDA",
    nome_fantasia: "Canastra Grãos",
  };

  it("returns true for empty query", () => {
    expect(leadMatchesSearch("", lead)).toBe(true);
    expect(leadMatchesSearch("   ", lead)).toBe(true);
  });

  it("matches name without accents", () => {
    expect(leadMatchesSearch("jose", lead)).toBe(true);
    expect(leadMatchesSearch("SILVA", lead)).toBe(true);
  });

  it("matches company and razao_social and nome_fantasia accent-insensitively", () => {
    expect(leadMatchesSearch("cafe", lead)).toBe(true);
    expect(leadMatchesSearch("comercio", lead)).toBe(true);
    expect(leadMatchesSearch("graos", lead)).toBe(true);
  });

  it("matches phone typed with formatting", () => {
    expect(leadMatchesSearch("(34) 99999-8888", lead)).toBe(true);
    expect(leadMatchesSearch("3499999", lead)).toBe(true);
  });

  it("returns false when nothing matches", () => {
    expect(leadMatchesSearch("zzz", lead)).toBe(false);
  });

  it("tolerates null fields", () => {
    expect(leadMatchesSearch("x", { name: null, phone: null })).toBe(false);
  });
});

describe("dealMatchesSearch", () => {
  const deal = {
    title: "Kit Canastra Atacado",
    leads: {
      name: "José da Silva",
      company: "Café Canastra",
      phone: "5534999998888",
      nome_fantasia: "Canastra Grãos",
    },
  };

  it("returns true for empty query", () => {
    expect(dealMatchesSearch("", deal)).toBe(true);
  });

  it("matches deal title accent-insensitively", () => {
    expect(dealMatchesSearch("atacado", deal)).toBe(true);
    expect(dealMatchesSearch("CANASTRA", deal)).toBe(true);
  });

  it("matches lead name, company and nome_fantasia accent-insensitively", () => {
    expect(dealMatchesSearch("jose", deal)).toBe(true);
    expect(dealMatchesSearch("cafe", deal)).toBe(true);
    expect(dealMatchesSearch("graos", deal)).toBe(true);
  });

  it("matches phone typed with formatting", () => {
    expect(dealMatchesSearch("(34) 99999-8888", deal)).toBe(true);
  });

  it("returns false when nothing matches", () => {
    expect(dealMatchesSearch("zzz", deal)).toBe(false);
  });

  it("tolerates missing leads join", () => {
    expect(dealMatchesSearch("x", { title: "Sem lead" })).toBe(false);
  });
});

describe("buildAccentInsensitivePattern", () => {
  it("expands each letter into its accented variants", () => {
    expect(buildAccentInsensitivePattern("aisl")).toBe("[aàáâãäå][iìíîï]sl");
  });

  it("folds the query first, so accented input matches unaccented data", () => {
    // "José" e "jose" precisam gerar o MESMO padrão — a busca é simétrica.
    expect(buildAccentInsensitivePattern("José")).toBe(
      buildAccentInsensitivePattern("jose"),
    );
  });

  it("never emits characters that break the PostgREST or=() parser", () => {
    const pattern = buildAccentInsensitivePattern("a.b,c(d)e*f") ?? "";
    expect(pattern).not.toMatch(/[.,()*\\]/);
  });

  it("keeps spaces so multi-word queries match", () => {
    expect(buildAccentInsensitivePattern("aislan piuco")).toContain(" ");
  });

  it("returns null when there is nothing searchable left", () => {
    expect(buildAccentInsensitivePattern("")).toBeNull();
    expect(buildAccentInsensitivePattern("   ")).toBeNull();
    expect(buildAccentInsensitivePattern("...")).toBeNull();
  });

  it("matches the same rows the client-side matcher would", () => {
    // Paridade: o padrão do servidor tem de casar exatamente o que
    // leadMatchesSearch casa no cliente — senão a lista mente de novo.
    const names = ["Aislan Piuco", "José da Silva", "Jose Lima", "DALECAFÉ", "Zé"];
    for (const query of ["aisl", "jose", "JOSÉ", "cafe", "ze"]) {
      const re = new RegExp(buildAccentInsensitivePattern(query) ?? "$^", "i");
      for (const name of names) {
        expect(re.test(name)).toBe(leadMatchesSearch(query, { name }));
      }
    }
  });
});

describe("buildLeadSearchOrFilter", () => {
  it("covers every text field the client matcher looks at", () => {
    const filter = buildLeadSearchOrFilter("cafe") ?? "";
    for (const col of ["name", "company", "razao_social", "nome_fantasia"]) {
      expect(filter).toContain(`${col}.imatch.`);
    }
  });

  it("adds a phone term only when the query carries digits", () => {
    expect(buildLeadSearchOrFilter("(34) 99999-8888")).toContain(
      `phone.imatch.${buildDigitsPattern("34999998888")}`,
    );
    expect(buildLeadSearchOrFilter("aisl")).not.toContain("phone.");
  });

  it("returns null for an unsearchable query", () => {
    expect(buildLeadSearchOrFilter("  ")).toBeNull();
  });
});

describe("leadMatchesSearch — tokens, e-mail e CNPJ (P5)", () => {
  const hiago = {
    name: "Hiago Angelucci",
    phone: "5534999998888",
    email: "compras@vidanatural.com.br",
    cnpj: "25139264000151",
    company: "Vida Natural",
  };

  it("matches all terms in any order", () => {
    expect(leadMatchesSearch("angelucci hiago", hiago)).toBe(true);
    expect(leadMatchesSearch("Hiago   ANGELUCCI", hiago)).toBe(true);
  });

  it("requires every term", () => {
    expect(leadMatchesSearch("hiago souza", hiago)).toBe(false);
  });

  it("lets terms hit different fields", () => {
    expect(leadMatchesSearch("hiago natural", hiago)).toBe(true);
    expect(leadMatchesSearch("hiago 99999", hiago)).toBe(true);
  });

  it("matches by e-mail", () => {
    expect(leadMatchesSearch("compras@vidanatural", hiago)).toBe(true);
    expect(leadMatchesSearch("vidanatural.com", hiago)).toBe(true);
  });

  it("finds a CNPJ typed with mask by its digits", () => {
    expect(leadMatchesSearch("25.139.264/0001-51", hiago)).toBe(true);
    expect(leadMatchesSearch("25139264", hiago)).toBe(true);
  });

  it("finds a CNPJ stored with mask by the digits typed", () => {
    const masked = { name: "Loja", cnpj: "25.139.264/0001-51" };
    expect(leadMatchesSearch("25139264000151", masked)).toBe(true);
    expect(leadMatchesSearch("25.139.264/0001-51", masked)).toBe(true);
  });

  it("keeps matching a contiguous phrase (superset of the old behavior)", () => {
    expect(leadMatchesSearch("hiago ang", hiago)).toBe(true);
  });

  it("matches nothing for a query made only of punctuation", () => {
    expect(leadMatchesSearch("...", hiago)).toBe(false);
  });
});

describe("searchTokens", () => {
  it("folds, splits on anything that is not a letter or digit, drops empties", () => {
    expect(searchTokens("  Angelucci,  HIÁGO ")).toEqual(["angelucci", "hiago"]);
    expect(searchTokens("compras@vida.com")).toEqual(["compras", "vida", "com"]);
    expect(searchTokens("...")).toEqual([]);
  });
});

describe("buildDigitsPattern", () => {
  it("tolerates up to two separators between digits", () => {
    const re = new RegExp(buildDigitsPattern("25139264000151"));
    expect(re.test("25.139.264/0001-51")).toBe(true);
    expect(re.test("25139264000151")).toBe(true);
    expect(new RegExp(buildDigitsPattern("34988887777")).test("(34) 98888-7777")).toBe(true);
  });

  it("never emits characters that break the PostgREST or=() parser", () => {
    expect(buildDigitsPattern("123")).not.toMatch(/[.,()*\\"]/);
  });
});

describe("buildLeadSearchOrFilter — tokens (P5)", () => {
  it("ANDs one OR-group per term when there are several terms", () => {
    const filter = buildLeadSearchOrFilter("angelucci hiago") ?? "";
    expect(filter.startsWith("and(or(")).toBe(true);
    expect(filter).toContain("name.imatch.[aàáâãäå][nñ]g");
    expect(filter).toContain("name.imatch.h[iìíîï][aàáâãäå]g[oòóôõö]");
  });

  it("looks at e-mail", () => {
    expect(buildLeadSearchOrFilter("compras")).toContain("email.imatch.");
  });

  it("matches the whole digit string on phone and cnpj, with or without mask", () => {
    const filter = buildLeadSearchOrFilter("25.139.264/0001-51") ?? "";
    const d = buildDigitsPattern("25139264000151");
    expect(filter).toContain(`phone.imatch.${d}`);
    expect(filter).toContain(`cnpj.imatch.${d}`);
  });

  it("keeps a single-term query flat (no and())", () => {
    const filter = buildLeadSearchOrFilter("cafe") ?? "";
    expect(filter).not.toContain("and(");
    expect(filter).not.toContain("phone.");
  });
});

describe("casamento por dígitos exige 4+ dígitos (revisão P5)", () => {
  const lead = {
    name: "Mercearia Boa Vista",
    phone: "5565993650001",
    cnpj: "12345678000190",
  };

  it("does not match by phone a text query that carries a lone digit", () => {
    expect(leadMatchesSearch("Café 3 Corações", lead)).toBe(false);
    expect(leadMatchesSearch("3", lead)).toBe(false);
    expect(leadMatchesSearch("boa 65", lead)).toBe(false);
  });

  it("still matches by phone with 4+ digits", () => {
    expect(leadMatchesSearch("65993", lead)).toBe(true);
    expect(leadMatchesSearch("boa 6599", lead)).toBe(true);
    expect(leadMatchesSearch("65650", { name: "X", phone: "5565650123" })).toBe(true);
  });

  it("keeps a text match on a short number (\"Café 3 Corações\" finds itself)", () => {
    expect(leadMatchesSearch("Café 3 Corações", { name: "Café 3 Corações", phone: "5511" })).toBe(true);
  });

  it("server filter: no phone/cnpj term for fewer than 4 digits", () => {
    expect(buildLeadSearchOrFilter("Café 3 Corações")).not.toContain("phone.");
    expect(buildLeadSearchOrFilter("3")).not.toContain("phone.");
    expect(buildLeadSearchOrFilter("65650")).toContain(`phone.imatch.${buildDigitsPattern("65650")}`);
    expect(buildLeadSearchOrFilter("boa 6599")).toContain(`phone.imatch.${buildDigitsPattern("6599")}`);
  });
});

import { describe, it, expect } from "vitest";
import { findInadimplentes, valorVencidoDe, type LeadComTags } from "@/lib/inadimplentes";
import { TAG_DEBITO_VENCIDO_ID } from "@/lib/constants";

const OUTRA_TAG = "2249642b-e4f2-420e-8482-d07b325a28c8";

function lead(over: Partial<LeadComTags> & { id: string }): LeadComTags {
  return {
    name: "Fulano",
    phone: "5534999999999",
    lead_tags: [],
    metadata: null,
    ...over,
  } as LeadComTags;
}

describe("findInadimplentes", () => {
  it("devolve vazio quando nada está selecionado", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }] })];
    const r = findInadimplentes(leads, new Set());
    expect(r.leads).toEqual([]);
    expect(r.totalVencido).toBe(0);
  });

  it("devolve vazio quando nenhum selecionado tem a tag", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: OUTRA_TAG, tags: null }] })];
    expect(findInadimplentes(leads, new Set(["a"])).leads).toEqual([]);
  });

  it("soma valor_vencido dos selecionados com a tag", () => {
    const leads = [
      lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 1000 } }),
      lead({ id: "b", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 234.56 } }),
    ];
    const r = findInadimplentes(leads, new Set(["a", "b"]));
    expect(r.leads.map((l) => l.id)).toEqual(["a", "b"]);
    expect(r.totalVencido).toBeCloseTo(1234.56);
  });

  it("ignora lead com a tag que não está selecionado", () => {
    const leads = [
      lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 100 } }),
      lead({ id: "b", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: 900 } }),
    ];
    const r = findInadimplentes(leads, new Set(["a"]));
    expect(r.leads).toHaveLength(1);
    expect(r.totalVencido).toBe(100);
  });

  it("conta lead com a tag mas sem metadata, somando zero", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: null })];
    const r = findInadimplentes(leads, new Set(["a"]));
    expect(r.leads).toHaveLength(1);
    expect(r.totalVencido).toBe(0);
  });

  it("aceita valor_vencido como string com vírgula decimal", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: "1.234,56" } })];
    expect(findInadimplentes(leads, new Set(["a"])).totalVencido).toBeCloseTo(1234.56);
  });

  it("trata valor_vencido inválido como zero sem quebrar", () => {
    const leads = [lead({ id: "a", lead_tags: [{ tag_id: TAG_DEBITO_VENCIDO_ID, tags: null }], metadata: { valor_vencido: "abc" } })];
    const r = findInadimplentes(leads, new Set(["a"]));
    expect(r.leads).toHaveLength(1);
    expect(r.totalVencido).toBe(0);
  });

  it("tolera lead_tags ausente", () => {
    const leads = [{ id: "a", name: "X", phone: "55", metadata: null } as LeadComTags];
    expect(findInadimplentes(leads, new Set(["a"])).leads).toEqual([]);
  });
});

describe("valorVencidoDe", () => {
  it("parseia string no formato brasileiro igual à soma", () => {
    expect(valorVencidoDe(lead({ id: "a", metadata: { valor_vencido: "1.234,56" } }))).toBeCloseTo(1234.56);
  });
  it("devolve 0 para metadata ausente ou lixo", () => {
    expect(valorVencidoDe(lead({ id: "a", metadata: null }))).toBe(0);
    expect(valorVencidoDe(lead({ id: "a", metadata: { valor_vencido: "abc" } }))).toBe(0);
  });
});

import { describe, it, expect } from "vitest";
import {
  DEFAULT_USD_TO_BRL_WITH_TAX,
  resolveBrlMultiplier,
  formatBRL,
  mapCostsSummary,
  fillDailyCosts,
  mapCostsBreakdown,
  mapTopLeads,
  mapWhatsappSummary,
  fillWhatsappDaily,
} from "@/lib/stats-mappers";

describe("mapCostsSummary", () => {
  it("mapeia linha da RPC com totais e avg_cost_per_lead", () => {
    const r = mapCostsSummary({
      total_cost: 1.23456789,
      total_calls: 10,
      total_prompt_tokens: 1000,
      total_completion_tokens: 500,
      unique_leads: 4,
    });
    expect(r).toEqual({
      total_cost: 1.234568, // round6
      total_calls: 10,
      total_prompt_tokens: 1000,
      total_completion_tokens: 500,
      total_tokens: 1500,
      unique_leads: 4,
      avg_cost_per_lead: 0.308642, // 1.23456789/4 round6
      total_cost_brl: 7.0741, // 1.23456789 * 5.73 round4
      brl_multiplier: DEFAULT_USD_TO_BRL_WITH_TAX,
    });
  });

  it("janela sem dados -> zeros (não 500), sem divisão por zero", () => {
    const r = mapCostsSummary(undefined);
    expect(r).toEqual({
      total_cost: 0,
      total_calls: 0,
      total_prompt_tokens: 0,
      total_completion_tokens: 0,
      total_tokens: 0,
      unique_leads: 0,
      avg_cost_per_lead: 0,
      total_cost_brl: 0,
      brl_multiplier: DEFAULT_USD_TO_BRL_WITH_TAX,
    });
  });

  it("aceita numeric/bigint vindos como string do PostgREST", () => {
    const r = mapCostsSummary({
      total_cost: "2.5",
      total_calls: "3",
      total_prompt_tokens: "100",
      total_completion_tokens: "50",
      unique_leads: "1",
    });
    expect(r.total_cost).toBe(2.5);
    expect(r.total_calls).toBe(3);
    expect(r.avg_cost_per_lead).toBe(2.5);
  });

  it("total_cost_brl usa o multiplicador injetado sem tocar nos campos USD", () => {
    const base = {
      total_cost: 2.39,
      total_calls: 60,
      total_prompt_tokens: 100,
      total_completion_tokens: 50,
      unique_leads: 5,
    };
    const r = mapCostsSummary(base, 5.73);
    // conciliacao real de 11/07: $2,39 -> R$ 13,70
    expect(r.total_cost_brl).toBe(13.6947);
    expect(r.brl_multiplier).toBe(5.73);
    expect(r.total_cost).toBe(2.39); // USD intocado (Regra de Ouro)
  });
});

describe("resolveBrlMultiplier (env CUSTO_IA_MULTIPLICADOR_BRL)", () => {
  it("sem env -> default da conciliacao", () => {
    expect(resolveBrlMultiplier(undefined)).toBe(DEFAULT_USD_TO_BRL_WITH_TAX);
    expect(resolveBrlMultiplier(null)).toBe(DEFAULT_USD_TO_BRL_WITH_TAX);
  });

  it("valor valido do env e respeitado", () => {
    expect(resolveBrlMultiplier("5.85")).toBe(5.85);
  });

  it("lixo/zero/negativo -> fallback ao default (nunca NaN no dashboard)", () => {
    expect(resolveBrlMultiplier("abc")).toBe(DEFAULT_USD_TO_BRL_WITH_TAX);
    expect(resolveBrlMultiplier("0")).toBe(DEFAULT_USD_TO_BRL_WITH_TAX);
    expect(resolveBrlMultiplier("-2")).toBe(DEFAULT_USD_TO_BRL_WITH_TAX);
  });
});

describe("formatBRL", () => {
  it("formata em pt-BR com virgula decimal", () => {
    // Intl usa NBSP entre simbolo e valor — normaliza p/ comparar
    expect(formatBRL(13.7).replace(/ /g, " ")).toBe("R$ 13,70");
    expect(formatBRL(0.4).replace(/ /g, " ")).toBe("R$ 0,40");
    expect(formatBRL(1234.5).replace(/ /g, " ")).toBe("R$ 1.234,50");
  });
});

describe("fillDailyCosts", () => {
  it("preenche dias sem dados com cost 0 (gap-fill)", () => {
    const rows = [{ day: "2026-07-02", cost: 5 }];
    const data = fillDailyCosts(rows, "2026-07-01", "2026-07-04");
    expect(data).toEqual([
      { date: "2026-07-01", cost: 0 },
      { date: "2026-07-02", cost: 5 },
      { date: "2026-07-03", cost: 0 },
    ]);
  });

  it("arredonda cost em 6 casas", () => {
    const rows = [{ day: "2026-07-01", cost: 1.123456789 }];
    const data = fillDailyCosts(rows, "2026-07-01", "2026-07-02");
    expect(data).toEqual([{ date: "2026-07-01", cost: 1.123457 }]);
  });
});

describe("mapCostsBreakdown", () => {
  it("mapeia e arredonda cost, preserva ordem já vinda da RPC (ORDER BY cost DESC)", () => {
    const rows = [
      { key: "qualificacao", cost: 3.0000009, calls: 2, tokens: 300 },
      { key: "null", cost: 1, calls: 1, tokens: 100 },
    ];
    expect(mapCostsBreakdown(rows)).toEqual([
      { key: "qualificacao", cost: 3.000001, calls: 2, tokens: 300 },
      { key: "null", cost: 1, calls: 1, tokens: 100 },
    ]);
  });

  it("lista vazia -> []", () => {
    expect(mapCostsBreakdown([])).toEqual([]);
  });
});

describe("mapTopLeads", () => {
  it("injeta name/phone do join e arredonda cost", () => {
    const rows = [
      { lead_id: "l1", cost: 9.9999995, calls: 5, tokens: 900, stage: "negociacao" },
    ];
    const leadInfos = [{ id: "l1", name: "Ana", phone: "5511999998888" }];
    expect(mapTopLeads(rows, leadInfos)).toEqual([
      {
        lead_id: "l1",
        cost: 10.0,
        calls: 5,
        tokens: 900,
        stage: "negociacao",
        name: "Ana",
        phone: "5511999998888",
      },
    ]);
  });

  it("sem nome cadastrado -> usa phone; sem phone -> 'Desconhecido'", () => {
    const rows = [{ lead_id: "l2", cost: 1, calls: 1, tokens: 10, stage: "novo" }];
    expect(mapTopLeads(rows, [{ id: "l2", name: null, phone: "123" }])[0].name).toBe("123");
    expect(mapTopLeads(rows, [{ id: "l2", name: null, phone: null }])[0].name).toBe("Desconhecido");
  });

  it("lead sem correspondência no join -> name 'Desconhecido', phone ''", () => {
    const rows = [{ lead_id: "l3", cost: 1, calls: 1, tokens: 10, stage: "novo" }];
    expect(mapTopLeads(rows, [])[0]).toMatchObject({ name: "Desconhecido", phone: "" });
  });
});

describe("mapWhatsappSummary", () => {
  it("aplica preços de marketing/utility e trunca em false", () => {
    const r = mapWhatsappSummary({ marketing_count: 10, utility_count: 5 });
    expect(r).toEqual({
      marketing_count: 10,
      marketing_cost: 0.617, // 10*0.0617
      utility_count: 5,
      utility_cost: 0.0335, // 5*0.0067
      total_whatsapp_cost: 0.6505,
      truncated: false,
    });
  });

  it("janela sem dados -> zeros, truncated false", () => {
    expect(mapWhatsappSummary(null)).toEqual({
      marketing_count: 0,
      marketing_cost: 0,
      utility_count: 0,
      utility_cost: 0,
      total_whatsapp_cost: 0,
      truncated: false,
    });
  });
});

describe("fillWhatsappDaily", () => {
  it("gap-fill de dias + custo por dia, truncated tratado pela rota (não aqui)", () => {
    const rows = [{ day: "2026-07-01", marketing_count: 2, utility_count: 1 }];
    const data = fillWhatsappDaily(rows, "2026-07-01", "2026-07-03");
    expect(data).toEqual([
      { date: "2026-07-01", marketing_cost: 0.1234, utility_cost: 0.0067, total: 0.1301 },
      { date: "2026-07-02", marketing_cost: 0, utility_cost: 0, total: 0 },
    ]);
  });
});

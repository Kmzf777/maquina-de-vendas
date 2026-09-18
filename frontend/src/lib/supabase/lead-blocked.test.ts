/**
 * O helper `isLeadBlocked` é a ÚNICA barreira das rotas Next de envio: elas montam o
 * POST para `graph.facebook.com` com o token lido do Supabase, sem passar pelo FastAPI
 * nem pelo `MetaCloudClient`, então nenhum guard de backend as cobre. Estes testes
 * fixam o critério (o mesmo de `is_lead_blacklisted`, `backend/app/leads/service.py:381`)
 * e, principalmente, o fail-open — que é fácil de inverter sem querer numa refatoração.
 *
 * Mock do cliente Supabase no estilo de `pipeline-access.test.ts` / do teste de rota em
 * `src/app/api/campaigns/__tests__/activate-proxy.test.ts`: objeto montado à mão, sem
 * banco nem rede.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { getServiceSupabase } from "@/lib/supabase/api";
import {
  BLACKLIST_PIPELINE_ID,
  blockedLeadIds,
  isLeadBlocked,
} from "@/lib/supabase/lead-blocked";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;
type Resultado = { data: unknown; error: unknown };

/**
 * Cliente falso: cada tabela tem um resultado fixo. O builder é encadeável e "thenable"
 * (o supabase-js resolve a query no await, sem método terminal), e ainda expõe
 * `maybeSingle()` para o caminho que lê um lead só.
 */
function clienteFalso(resultados: Record<string, Resultado | (() => Resultado)>) {
  const tabelasConsultadas: string[] = [];
  const filtros: [string, unknown][] = [];

  const from = (tabela: string) => {
    tabelasConsultadas.push(tabela);
    const configurado = resultados[tabela];
    // Fábrica em vez de valor: é assim que o teste simula um cliente que ESTOURA
    // (a função lança) em vez de devolver `{ data, error }`.
    const resultado: Resultado =
      typeof configurado === "function"
        ? configurado()
        : (configurado ?? { data: null, error: null });

    const builder: Record<string, unknown> = {
      select: () => builder,
      eq: (campo: string, valor: unknown) => {
        filtros.push([campo, valor]);
        return builder;
      },
      in: (campo: string, valor: unknown) => {
        filtros.push([campo, valor]);
        return builder;
      },
      limit: () => builder,
      maybeSingle: async () => resultado,
      then: (resolve: (v: Resultado) => void) => resolve(resultado),
    };
    return builder;
  };

  return {
    supabase: { from } as unknown as ServiceSupabase,
    tabelasConsultadas,
    filtros,
  };
}

const semDeals: Resultado = { data: [], error: null };

let warn: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  warn = vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("isLeadBlocked", () => {
  it("bloqueado por leads.opt_out (critério canônico)", async () => {
    const { supabase } = clienteFalso({
      leads: { data: { opt_out: true }, error: null },
      deals: semDeals,
    });

    expect(await isLeadBlocked(supabase, "lead-1")).toBe(true);
  });

  it("bloqueado por deal no funil Blacklist mesmo sem opt_out (defesa em profundidade)", async () => {
    // Este é o caso do card arrastado para a Blacklist no Kanban: `opt_out` continua
    // false, e só o braço do deal segura o disparo.
    const { supabase, filtros } = clienteFalso({
      leads: { data: { opt_out: false }, error: null },
      deals: { data: [{ id: "deal-1" }], error: null },
    });

    expect(await isLeadBlocked(supabase, "lead-1")).toBe(true);
    expect(filtros).toContainEqual(["pipeline_id", BLACKLIST_PIPELINE_ID]);
  });

  it("lead normal (sem opt_out e sem deal na Blacklist) NÃO é bloqueado", async () => {
    const { supabase } = clienteFalso({
      leads: { data: { opt_out: false }, error: null },
      deals: semDeals,
    });

    expect(await isLeadBlocked(supabase, "lead-1")).toBe(false);
  });

  // Fail-open deliberado, igual ao backend: a proteção vem das camadas somadas
  // (filtro na origem + guard no envio + gate inbound). Travar todo envio manual do
  // CRM porque o Supabase soluçou seria pior do que a lacuna.
  it("erro na consulta de leads é fail-open, com console.warn", async () => {
    const { supabase } = clienteFalso({
      leads: { data: null, error: { message: "timeout" } },
      deals: semDeals,
    });

    expect(await isLeadBlocked(supabase, "lead-1")).toBe(false);
    expect(warn).toHaveBeenCalled();
  });

  it("erro na consulta de deals é fail-open, com console.warn", async () => {
    const { supabase } = clienteFalso({
      leads: { data: { opt_out: false }, error: null },
      deals: { data: null, error: { message: "timeout" } },
    });

    expect(await isLeadBlocked(supabase, "lead-1")).toBe(false);
    expect(warn).toHaveBeenCalled();
  });

  it("exceção do cliente também é fail-open (não propaga e não derruba a rota)", async () => {
    const { supabase } = clienteFalso({
      leads: () => {
        throw new Error("cliente quebrado");
      },
    });

    expect(await isLeadBlocked(supabase, "lead-1")).toBe(false);
    expect(warn).toHaveBeenCalled();
  });

  it("sem lead_id devolve false sem consultar nada", async () => {
    const { supabase, tabelasConsultadas } = clienteFalso({});

    expect(await isLeadBlocked(supabase, "")).toBe(false);
    expect(await isLeadBlocked(supabase, null)).toBe(false);
    expect(tabelasConsultadas).toEqual([]);
  });

  it("opt_out já conhecido como true encerra sem ida ao Supabase", async () => {
    const { supabase, tabelasConsultadas } = clienteFalso({});

    expect(await isLeadBlocked(supabase, "lead-1", true)).toBe(true);
    expect(tabelasConsultadas).toEqual([]);
  });

  it("opt_out conhecido como false pula a consulta de leads, mas ainda checa a Blacklist", async () => {
    // Economiza a ida extra no caminho de envio (o `select` da rota já traz opt_out),
    // sem abrir mão do segundo braço do critério.
    const { supabase, tabelasConsultadas } = clienteFalso({
      deals: { data: [{ id: "deal-1" }], error: null },
    });

    expect(await isLeadBlocked(supabase, "lead-1", false)).toBe(true);
    expect(tabelasConsultadas).toEqual(["deals"]);
  });
});

describe("blockedLeadIds (versão em lote, usada na atribuição de disparo)", () => {
  it("junta os bloqueados por opt_out e os bloqueados por deal na Blacklist", async () => {
    const { supabase } = clienteFalso({
      leads: { data: [{ id: "a" }], error: null },
      deals: { data: [{ lead_id: "b" }], error: null },
    });

    const bloqueados = await blockedLeadIds(supabase, ["a", "b", "c"]);

    expect([...bloqueados].sort()).toEqual(["a", "b"]);
    expect(bloqueados.has("c")).toBe(false);
  });

  it("erro de consulta é fail-open: ninguém filtrado, disparo segue", async () => {
    const { supabase } = clienteFalso({
      leads: { data: null, error: { message: "timeout" } },
      deals: { data: [], error: null },
    });

    expect((await blockedLeadIds(supabase, ["a", "b"])).size).toBe(0);
    expect(warn).toHaveBeenCalled();
  });

  it("lista vazia não consulta o Supabase", async () => {
    const { supabase, tabelasConsultadas } = clienteFalso({});

    expect((await blockedLeadIds(supabase, [])).size).toBe(0);
    expect(tabelasConsultadas).toEqual([]);
  });
});

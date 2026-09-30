import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";

type Resultado = { data: unknown; error: { message: string } | null };
/** Tabela do fake: um resultado fixo, ou uma função que rejeita (para o caminho de exceção). */
type Tabela = Resultado | (() => Promise<never>);

type Chamada = { tabela: string; metodo: string; args: unknown[] };

/**
 * Query builder falso do supabase-js: todo método encadeia, o `await` devolve o
 * resultado da tabela, e `tabelas` registra CADA `from(...)` — é por essa lista que os
 * testes provam quantas consultas a rota faz e em quais tabelas.
 */
function fakeSupabase(tabelas: Record<string, Tabela>) {
  const consultadas: string[] = [];
  const chamadas: Chamada[] = [];
  const from = (tabela: string) => {
    consultadas.push(tabela);
    const alvo = tabelas[tabela];
    const builder: Record<string, unknown> = {};
    for (const metodo of ["select", "eq", "order", "limit", "in"]) {
      builder[metodo] = (...args: unknown[]) => {
        chamadas.push({ tabela, metodo, args });
        return builder;
      };
    }
    builder.then = (ok: (r: Resultado) => unknown, falha?: (e: unknown) => unknown) => {
      if (typeof alvo === "function") return alvo().then(ok as never, falha);
      return Promise.resolve(alvo ?? { data: null, error: null }).then(ok, falha);
    };
    return builder;
  };
  const instalar = () => {
    vi.mocked(getServiceSupabase).mockResolvedValue({ from } as never);
    return { consultadas, chamadas };
  };
  return instalar();
}

const chamar = (qs = "?status=pending") =>
  GET(new NextRequest(`http://localhost/api/followups${qs}`));

/** Job do João: metadata completo do motor (`_montar_jobs_da_matricula`). */
const jobJoao = (p: Record<string, unknown> = {}, md: Record<string, unknown> = {}) => ({
  id: "job-1",
  sequence: 2,
  job_type: "joao_novo",
  status: "pending",
  fire_at: "2026-09-29T12:00:00Z",
  sent_at: null,
  cancel_reason: null,
  lead_id: "lead-1",
  conversation_id: "conv-1",
  leads: { name: "Marcella", phone: "5534988861441" },
  metadata: {
    cadencia: "novo",
    funil: "atacado",
    toque: 2,
    deal_id: "deal-1",
    // A etapa da MATRÍCULA — o passado. Nunca deve aparecer no payload.
    stage_id: "stage-novo",
    pipeline_id: "pipe-1",
    ...md,
  },
  ...p,
});

/** Job da ValerIA: sem deal_id, sem cadência/funil/toque — só `objetivo`. */
const jobValeria = (p: Record<string, unknown> = {}) => ({
  id: "job-v",
  sequence: 3,
  job_type: "standard",
  status: "pending",
  fire_at: "2026-09-29T13:00:00Z",
  sent_at: null,
  cancel_reason: null,
  lead_id: "lead-9",
  conversation_id: "conv-9",
  leads: { name: "Ana", phone: "5511999999999" },
  metadata: { objetivo: "reengajar" },
  ...p,
});

/** O card AGORA está em "Em atenção" — etapa DIFERENTE da gravada no metadata. */
const dealsAgora: Resultado = {
  data: [{ id: "deal-1", pipeline_stages: { label: "Em atenção" } }],
  error: null,
};

/** Se alguém resolvesse a etapa por `metadata.stage_id`, sairia daqui — e é o que não pode. */
const stagesDaMatricula: Resultado = {
  data: [{ id: "stage-novo", label: "Novo" }],
  error: null,
};

afterEach(() => {
  vi.resetAllMocks();
});

describe("GET /api/followups — contexto das esteiras", () => {
  it("repassa cadencia, funil, toque e acao do metadata, e os CINCO campos saem no payload", async () => {
    fakeSupabase({
      follow_up_jobs: { data: [jobJoao()], error: null },
      deals: dealsAgora,
    });
    const res = await chamar();
    expect(res.status).toBe(200);
    const [row] = await res.json();

    // O compilador não cobra: a rota monta objeto literal sem anotar BoardJob. A
    // garantia de que nenhum dos cinco campos some é esta asserção de CHAVES.
    for (const campo of ["cadencia", "funil", "toque", "acao", "etapa_atual"]) {
      expect(Object.keys(row)).toContain(campo);
    }
    expect(row).toMatchObject({
      cadencia: "novo",
      funil: "atacado",
      toque: 2,
      acao: null,
      etapa_atual: "Em atenção",
    });
    // E o que já existia continua de pé.
    expect(row).toMatchObject({ id: "job-1", job_type: "joao_novo", sequence: 2, lead_name: "Marcella" });
  });

  it("job de mover o card expõe acao = mover_etapa", async () => {
    fakeSupabase({
      follow_up_jobs: { data: [jobJoao({ sequence: 5 }, { acao: "mover_etapa", toque: undefined })], error: null },
      deals: dealsAgora,
    });
    const [row] = await (await chamar()).json();
    expect(row.acao).toBe("mover_etapa");
    expect(row.toque).toBeNull();
  });

  it("A ETAPA VEM DO deals, NÃO de metadata.stage_id — os dois apontam para etapas diferentes", async () => {
    const { consultadas, chamadas } = fakeSupabase({
      follow_up_jobs: { data: [jobJoao()], error: null },
      // metadata.stage_id = "stage-novo" → "Novo";   deals.pipeline_stages → "Em atenção".
      deals: dealsAgora,
      pipeline_stages: stagesDaMatricula,
    });
    const [row] = await (await chamar()).json();

    expect(row.etapa_atual).toBe("Em atenção"); // o AGORA
    expect(row.etapa_atual).not.toBe("Novo"); // o passado da matrícula NÃO vence
    // Prova estrutural: a rota nunca abre `pipeline_stages` por conta própria — o
    // rótulo chega pelo embed do `deals`, e o metadata.stage_id não é usado em lugar nenhum.
    expect(consultadas).not.toContain("pipeline_stages");
    const filtro = chamadas.find((c) => c.tabela === "deals" && c.metodo === "in");
    expect(filtro?.args).toEqual(["id", ["deal-1"]]);
    // `metadata.stage_id` não aparece em nenhum argumento de consulta.
    expect(JSON.stringify(chamadas)).not.toContain("stage-novo");
  });

  it("UMA consulta em lote para a página inteira: 6 jobs, 3 deals distintos → 2 consultas", async () => {
    const jobs = [
      jobJoao({ id: "a" }, { deal_id: "deal-1" }),
      jobJoao({ id: "b" }, { deal_id: "deal-1" }),
      jobJoao({ id: "c" }, { deal_id: "deal-2" }),
      jobJoao({ id: "d" }, { deal_id: "deal-2" }),
      jobJoao({ id: "e" }, { deal_id: "deal-3" }),
      jobValeria({ id: "f" }),
    ];
    const { consultadas, chamadas } = fakeSupabase({
      follow_up_jobs: { data: jobs, error: null },
      deals: {
        data: [
          { id: "deal-1", pipeline_stages: { label: "Em atenção" } },
          { id: "deal-2", pipeline_stages: [{ label: "Já chamado" }] }, // embed como array
          { id: "deal-3", pipeline_stages: { label: "Cliente Ativo" } },
        ],
        error: null,
      },
    });
    const rows = await (await chamar()).json();

    expect(consultadas).toEqual(["follow_up_jobs", "deals"]); // constante, não 1 por job
    expect(chamadas.filter((c) => c.metodo === "in")).toHaveLength(1);
    expect(chamadas.find((c) => c.metodo === "in")?.args).toEqual(["id", ["deal-1", "deal-2", "deal-3"]]);
    expect(rows.map((r: { etapa_atual: string | null }) => r.etapa_atual)).toEqual([
      "Em atenção",
      "Em atenção",
      "Já chamado",
      "Já chamado",
      "Cliente Ativo",
      null,
    ]);
  });

  it("página só com jobs sem deal_id (ValerIA) não consulta deals", async () => {
    const { consultadas } = fakeSupabase({
      follow_up_jobs: { data: [jobValeria(), jobValeria({ id: "job-v2" })], error: null },
    });
    const rows = await (await chamar()).json();
    expect(consultadas).toEqual(["follow_up_jobs"]);
    expect(rows[0]).toMatchObject({
      cadencia: null,
      funil: null,
      toque: null,
      acao: null,
      etapa_atual: null,
      objetivo: "reengajar", // o campo da ValerIA segue intocado
    });
  });

  it("fail-soft: erro na consulta da etapa → etapa_atual null e a resposta sai inteira", async () => {
    fakeSupabase({
      follow_up_jobs: { data: [jobJoao()], error: null },
      deals: { data: null, error: { message: "column deals.stage_id does not exist" } },
    });
    const res = await chamar();
    expect(res.status).toBe(200);
    const [row] = await res.json();
    expect(row.etapa_atual).toBeNull();
    expect(row).toMatchObject({ id: "job-1", cadencia: "novo", funil: "atacado", toque: 2 });
  });

  it("fail-soft: exceção na consulta da etapa não derruba a resposta", async () => {
    fakeSupabase({
      follow_up_jobs: { data: [jobJoao()], error: null },
      deals: () => Promise.reject(new Error("fetch failed")),
    });
    const res = await chamar();
    expect(res.status).toBe(200);
    expect((await res.json())[0].etapa_atual).toBeNull();
  });

  it("card cujo deal não voltou (ou sem etapa) → etapa_atual null, sem quebrar", async () => {
    fakeSupabase({
      follow_up_jobs: { data: [jobJoao({ id: "x" }, { deal_id: "deal-sumido" }), jobJoao()], error: null },
      deals: { data: [{ id: "deal-1", pipeline_stages: null }], error: null },
    });
    const rows = await (await chamar()).json();
    expect(rows.map((r: { etapa_atual: string | null }) => r.etapa_atual)).toEqual([null, null]);
  });

  it("erro na consulta dos jobs continua 500 e não consulta deals", async () => {
    const { consultadas } = fakeSupabase({
      follow_up_jobs: { data: null, error: { message: "boom" } },
    });
    const res = await chamar();
    expect(res.status).toBe(500);
    expect(consultadas).toEqual(["follow_up_jobs"]);
  });

  it("status inválido segue 400 sem tocar no banco", async () => {
    const res = await chamar("?status=inventado");
    expect(res.status).toBe(400);
    expect(getServiceSupabase).not.toHaveBeenCalled();
  });
});

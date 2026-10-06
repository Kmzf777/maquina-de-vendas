import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({ getCurrentUser: vi.fn() }));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { getServiceSupabase } from "@/lib/supabase/api";
import type { TimelineConversou, TimelineEvent, TimelineResponse } from "@/components/leads/lead-timeline";

type Result = { data: unknown; error: { message: string } | null };
type Call = { table: string; ops: [string, unknown[]][] };

/**
 * Fake do query builder. Cada tabela devolve um Result fixo, ou uma FILA de Results (um por
 * consulta — a paginação de `messages`). `calls` registra a tabela e os métodos chamados.
 */
function fakeSupabase(tables: Record<string, Result | Result[]>) {
  const calls: Call[] = [];
  return {
    calls,
    from(table: string) {
      const call: Call = { table, ops: [] };
      calls.push(call);
      const entry = tables[table];
      const result: Result = Array.isArray(entry)
        ? (entry.shift() ?? { data: [], error: null })
        : (entry ?? { data: null, error: null });
      const builder: Record<string, unknown> = {};
      for (const m of ["select", "eq", "in", "order", "limit", "range"]) {
        builder[m] = (...args: unknown[]) => {
          call.ops.push([m, args]);
          return builder;
        };
      }
      builder.maybeSingle = async () => result;
      builder.then = (resolve: (r: Result) => unknown, reject?: (e: unknown) => unknown) =>
        Promise.resolve(result).then(resolve, reject);
      return builder;
    },
  };
}

const LEAD_ID = "6f1c2e7a-0000-4000-8000-000000000001";

const call = (id = LEAD_ID) =>
  GET(new Request(`http://localhost/api/leads/${id}/timeline`) as never, { params: Promise.resolve({ id }) });

const LEAD: Result = { data: { id: LEAD_ID }, error: null };

const ev = (p: Record<string, unknown>) => ({
  id: "e",
  event_type: "entrada",
  old_value: null,
  new_value: null,
  metadata: {},
  occurred_at: "2026-09-10T12:00:00Z",
  created_at: "2026-09-10T12:00:00Z",
  source: null,
  ...p,
});

const msgs = (...isos: string[]): Result => ({ data: isos.map((created_at) => ({ created_at })), error: null });

async function body(res: Response) {
  return (await res.json()) as TimelineResponse;
}

describe("GET /api/leads/[id]/timeline", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u1", role: "admin", email: "admin@x.com" } as never);
  });

  it("401 sem sessão", async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new Error("no session"));
    expect((await call()).status).toBe(401);
  });

  it("404 para id que não é UUID, sem consultar o banco", async () => {
    const sb = fakeSupabase({ leads: { data: null, error: { message: 'invalid input syntax for type uuid: "x"' } } });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);
    const res = await call("nao-e-uuid");
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ error: "lead_not_found" });
    expect(sb.calls).toHaveLength(0);
  });

  it("404 lead inexistente", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({ leads: { data: null, error: null } }) as never,
    );
    expect((await call()).status).toBe(404);
  });

  it("junta eventos e marcadores 'conversou' do mais novo ao mais antigo, no fuso de São Paulo", async () => {
    const sb = fakeSupabase({
      leads: LEAD,
      lead_events: {
        data: [
          ev({ id: "e2", event_type: "etapa", occurred_at: "2026-09-20T12:00:00Z" }),
          ev({ id: "e1", event_type: "entrada", occurred_at: "2026-09-10T12:00:00Z" }),
        ],
        error: null,
      },
      // 16/09 02:00Z = 15/09 23:00 em São Paulo: cai no dia 15.
      messages: [msgs("2026-09-16T02:00:00Z", "2026-09-15T18:00:00Z", "2026-09-15T13:00:00Z")],
    });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);

    const res = await call();
    expect(res.status).toBe(200);
    const { items, partial } = await body(res);
    expect(partial).toEqual([]);
    expect(items.map((i) => i.id)).toEqual(["e2", "conversou:2026-09-15", "e1"]);
    const dia = items[1] as TimelineConversou;
    expect(dia).toEqual({
      kind: "conversou",
      id: "conversou:2026-09-15",
      dia: "2026-09-15",
      at: "2026-09-16T02:00:00.000Z",
      mensagens: 3,
    });
    const evento = items[0] as TimelineEvent;
    expect(evento.kind).toBe("evento");
    expect(evento.at).toBe("2026-09-20T12:00:00Z");

    const evCall = sb.calls.find((c) => c.table === "lead_events")!;
    expect(evCall.ops).toContainEqual(["order", ["occurred_at", { ascending: false }]]);
    const msgCall = sb.calls.find((c) => c.table === "messages")!;
    expect(msgCall.ops).toContainEqual(["eq", ["role", "user"]]);
  });

  it("pagina as mensagens além do teto de 1000 linhas do PostgREST", async () => {
    const cheia = Array.from({ length: 1000 }, () => "2026-09-01T12:00:00Z");
    const sb = fakeSupabase({
      leads: LEAD,
      lead_events: { data: [], error: null },
      messages: [msgs(...cheia), msgs("2026-08-31T12:00:00Z")],
    });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);

    const { items } = await body(await call());
    expect(items.map((i) => [i.id, (i as TimelineConversou).mensagens])).toEqual([
      ["conversou:2026-09-01", 1000],
      ["conversou:2026-08-31", 1],
    ]);
    expect(sb.calls.filter((c) => c.table === "messages")).toHaveLength(2);
  });

  it("vendedor não vê venda de outro vendedor; vê a dele e a importada do Bling", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u2", role: "vendedor", email: "ana@x.com" } as never);
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: {
          data: [
            ev({ id: "v-joao", event_type: "venda", metadata: { sale_id: "s-j", sold_by: "joao@x.com", origin: "crm" } }),
            ev({ id: "v-ana", event_type: "venda", metadata: { sale_id: "s-a", sold_by: "Ana@x.com", origin: "crm" } }),
            ev({ id: "v-bling", event_type: "venda_cancelada", metadata: { sale_id: "s-b", sold_by: null, origin: "bling" } }),
            ev({ id: "ent", event_type: "entrada" }),
          ],
          error: null,
        },
        sales: {
          data: [
            { id: "s-j", sold_by: "joao@x.com", origin: "crm" },
            { id: "s-a", sold_by: "Ana@x.com", origin: "crm" },
            { id: "s-b", sold_by: null, origin: "bling" },
          ],
          error: null,
        },
        messages: [msgs()],
      }) as never,
    );
    const { items } = await body(await call());
    expect(items.map((i) => i.id).sort()).toEqual(["ent", "v-ana", "v-bling"]);
  });

  it("escopo do vendedor usa o sold_by ATUAL de sales, não a foto do evento", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u2", role: "vendedor", email: "ana@x.com" } as never);
    const sb = fakeSupabase({
      leads: LEAD,
      lead_events: {
        data: [
          // a foto diz Ana, mas a venda foi reatribuída ao João
          ev({ id: "era-ana", event_type: "venda", metadata: { sale_id: "s1", sold_by: "ana@x.com", origin: "crm" } }),
          // a foto diz João, mas a venda agora é da Ana
          ev({ id: "virou-ana", event_type: "venda", metadata: { sale_id: "s2", sold_by: "joao@x.com", origin: "crm" } }),
          // venda que não existe mais em sales: some
          ev({ id: "apagada", event_type: "venda_cancelada", metadata: { sale_id: "s3", sold_by: "ana@x.com", origin: "crm" } }),
        ],
        error: null,
      },
      sales: {
        data: [
          { id: "s1", sold_by: "joao@x.com", origin: "crm" },
          { id: "s2", sold_by: "Ana@x.com", origin: "crm" },
        ],
        error: null,
      },
      messages: [msgs()],
    });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);
    const { items, partial } = await body(await call());
    expect(items.map((i) => i.id)).toEqual(["virou-ana"]);
    expect(partial).toEqual([]);
    const salesCall = sb.calls.find((c) => c.table === "sales")!;
    expect(salesCall.ops).toContainEqual(["in", ["id", ["s1", "s2", "s3"]]]);
  });

  it("falha ao ler sales esconde as vendas do vendedor (na dúvida, esconde)", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u2", role: "vendedor", email: "ana@x.com" } as never);
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: {
          data: [
            ev({ id: "v", event_type: "venda", metadata: { sale_id: "s1", sold_by: "ana@x.com", origin: "crm" } }),
            ev({ id: "ent", event_type: "entrada" }),
          ],
          error: null,
        },
        sales: { data: null, error: { message: "boom" } },
        messages: [msgs()],
      }) as never,
    );
    const { items, partial } = await body(await call());
    expect(items.map((i) => i.id)).toEqual(["ent"]);
    expect(partial).toEqual(["vendas"]);
  });

  it("admin vê todas as vendas", async () => {
    const sb = fakeSupabase({
      leads: LEAD,
      lead_events: {
        data: [ev({ id: "v-joao", event_type: "venda", metadata: { sold_by: "joao@x.com", origin: "crm" } })],
        error: null,
      },
      messages: [msgs()],
    });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);
    const { items } = await body(await call());
    expect(items.map((i) => i.id)).toEqual(["v-joao"]);
    expect(sb.calls.some((c) => c.table === "sales")).toBe(false); // sem escopo, não busca
  });

  it("falha em lead_events vira partial 'eventos' sem derrubar os marcadores", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: { data: null, error: { message: "column occurred_at does not exist" } },
        messages: [msgs("2026-09-15T13:00:00Z")],
      }) as never,
    );
    const res = await call();
    expect(res.status).toBe(200);
    const { items, partial } = await body(res);
    expect(partial).toEqual(["eventos"]);
    expect(items.map((i) => i.id)).toEqual(["conversou:2026-09-15"]);
  });

  it("falha em messages vira partial 'conversas'", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: { data: [ev({ id: "e1" })], error: null },
        messages: [{ data: null, error: { message: "boom" } }],
      }) as never,
    );
    const { items, partial } = await body(await call());
    expect(partial).toEqual(["conversas"]);
    expect(items.map((i) => i.id)).toEqual(["e1"]);
  });

  it("completa o nome da campanha pelo meta_ad_id quando a entrada não trouxe", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: {
          data: [ev({ id: "e1", metadata: { canal: "Meta Ads", meta_ad_id: "ad-9", campanha_nome: null } })],
          error: null,
        },
        meta_ad_campaigns: { data: [{ ad_id: "ad-9", campaign_id: "c-9", campaign_name: "CTWA Atacado" }], error: null },
        messages: [msgs()],
      }) as never,
    );
    const { items } = await body(await call());
    const e = items[0] as TimelineEvent;
    expect(e.metadata.campanha_nome).toBe("CTWA Atacado");
    expect(e.metadata.campanha_id).toBe("c-9");
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));
vi.mock("@/lib/supabase/lead-blocked", () => ({
  isLeadBlocked: vi.fn(async () => false),
  MENSAGEM_LEAD_BLOQUEADO: "bloqueado",
}));
vi.mock("@/lib/supabase/channel-access", () => {
  class ChannelAccessError extends Error {}
  return { getAllowedChannelIds: vi.fn(async () => null), ChannelAccessError };
});
vi.mock("@/lib/meta-template", () => ({
  MetaRecusou: class MetaRecusou extends Error {},
  sendTemplateViaMeta: vi.fn(async () => ({ messages: [{ id: "wamid.X" }] })),
  registrarTemplateEnviado: vi.fn(async () => {}),
  wamidDaResposta: (j: { messages?: { id?: string }[] } | null) => j?.messages?.[0]?.id ?? null,
}));

import { GET, POST } from "./route";
import { getServiceSupabase } from "@/lib/supabase/api";
import { isLeadBlocked } from "@/lib/supabase/lead-blocked";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { sendTemplateViaMeta, registrarTemplateEnviado, MetaRecusou } from "@/lib/meta-template";

type Row = Record<string, unknown>;
type Tabelas = Record<"leads" | "channels" | "conversations" | "messages", Row[]>;

const CFG = { phone_number_id: "pn", access_token: "tok", waba_id: "waba" };

function base(): Tabelas {
  return {
    leads: [
      { id: "lead-1", name: "Ana", phone: "+55 (34) 98886-1441", company: "Loja", opt_out: false },
      { id: "lead-bling", name: "Bia", phone: "bling-123", company: null, opt_out: false },
    ],
    channels: [
      { id: "ch-b", name: "Vendas", provider: "meta_cloud", provider_config: CFG },
      { id: "ch-a", name: "Atendimento", provider: "meta_cloud", provider_config: CFG },
      { id: "ch-evo", name: "Antigo", provider: "evolution", provider_config: {} },
    ],
    conversations: [],
    messages: [],
  };
}

/**
 * Supabase falso por tabela: filtra por eq/is, ordena, e registra inserts e deletes.
 * O delete apaga de verdade só as linhas que casam com TODOS os filtros do comando.
 * `falhaSelect`: tabelas cujo select (maybeSingle) devolve erro.
 */
function instalar(tabelas: Tabelas, falhaSelect: (keyof Tabelas)[] = []) {
  const inseridos: { tabela: string; row: Row }[] = [];
  const apagados: { tabela: string; filtros: [string, unknown][] }[] = [];
  const from = (tabela: keyof Tabelas) => {
    const filtros: [string, unknown][] = [];
    let modo: "select" | "insert" | "delete" = "select";
    let contar = false;
    let ordem: string | null = null;
    let novo: Row | null = null;
    const linhas = () => {
      const rs = tabelas[tabela].filter((r) => filtros.every(([c, v]) => (r[c] ?? null) === v));
      if (ordem) rs.sort((a, b) => String(a[ordem!]).localeCompare(String(b[ordem!])));
      return rs;
    };
    const b: Record<string, unknown> = {};
    b.select = (_cols?: string, opts?: { count?: string; head?: boolean }) => {
      if (opts?.head) contar = true;
      return b;
    };
    b.eq = (c: string, v: unknown) => (filtros.push([c, v]), b);
    b.is = (c: string, v: unknown) => (filtros.push([c, v]), b);
    b.order = (c: string) => ((ordem = c), b);
    b.limit = () => b;
    b.insert = (row: Row) => {
      modo = "insert";
      novo = { id: `${tabela}-nova`, ...row };
      tabelas[tabela].push(novo);
      inseridos.push({ tabela, row });
      return b;
    };
    b.delete = () => ((modo = "delete"), b);
    b.single = async () => ({ data: modo === "insert" ? novo : linhas()[0] ?? null, error: null });
    b.maybeSingle = async () =>
      falhaSelect.includes(tabela)
        ? { data: null, error: { message: `falha em ${tabela}` } }
        : { data: linhas()[0] ?? null, error: null };
    b.then = (ok: (r: unknown) => unknown, ko?: (e: unknown) => unknown) => {
      let r: unknown;
      if (modo === "delete") {
        apagados.push({ tabela, filtros: [...filtros] });
        const alvo = new Set(linhas());
        tabelas[tabela] = tabelas[tabela].filter((row) => !alvo.has(row));
        r = { data: null, error: null };
      } else if (contar) {
        r = { data: null, count: linhas().length, error: null };
      } else {
        r = { data: linhas(), error: null };
      }
      return Promise.resolve(r).then(ok, ko);
    };
    return b;
  };
  vi.mocked(getServiceSupabase).mockResolvedValue({ from } as never);
  return { inseridos, apagados };
}

const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

const get = (id = "lead-1") =>
  GET(new NextRequest(`http://localhost/api/leads/${id}/iniciar-conversa`), ctx(id));

const post = (corpo: Row, id = "lead-1") =>
  POST(
    new NextRequest(`http://localhost/api/leads/${id}/iniciar-conversa`, {
      method: "POST",
      body: JSON.stringify(corpo),
    }),
    ctx(id),
  );

const CORPO = {
  channel_id: "ch-a",
  template_name: "boas_vindas",
  template_language_code: "pt_BR",
  template_variables: { nome: "Ana" },
  template_body: "Oi Ana",
};

beforeEach(() => {
  vi.mocked(getAllowedChannelIds).mockResolvedValue(null);
  vi.mocked(isLeadBlocked).mockResolvedValue(false);
  vi.mocked(sendTemplateViaMeta).mockResolvedValue({ messages: [{ id: "wamid.X" }] });
});
afterEach(() => vi.clearAllMocks());

describe("GET iniciar-conversa", () => {
  it("devolve lead, telefone limpo e só canais meta_cloud permitidos, por nome", async () => {
    instalar(base());
    const res = await get();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      lead: { id: "lead-1", name: "Ana", phone: "+55 (34) 98886-1441", company: "Loja" },
      telefone: "5534988861441",
      canais: [
        { id: "ch-a", name: "Atendimento" },
        { id: "ch-b", name: "Vendas" },
      ],
    });

    vi.mocked(getAllowedChannelIds).mockResolvedValue(["ch-b", "ch-evo"]);
    const restrito = await (await get("lead-bling")).json();
    expect(restrito.telefone).toBeNull();
    expect(restrito.canais).toEqual([{ id: "ch-b", name: "Vendas" }]);
  });

  it("lead inexistente → 404; falha de acesso → 401", async () => {
    instalar(base());
    expect((await get("nao-existe")).status).toBe(404);
    vi.mocked(getAllowedChannelIds).mockRejectedValue(new ChannelAccessError("sem sessão"));
    expect((await get()).status).toBe(401);
  });
});

describe("POST iniciar-conversa — guards antes do envio", () => {
  it("sem channel_id ou template_name → 400", async () => {
    instalar(base());
    expect((await post({ ...CORPO, channel_id: undefined })).status).toBe(400);
    expect((await post({ ...CORPO, template_name: "" })).status).toBe(400);
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
  });

  it("canal fora dos permitidos → 403, sem enviar", async () => {
    instalar(base());
    vi.mocked(getAllowedChannelIds).mockResolvedValue(["ch-b"]);
    expect((await post(CORPO)).status).toBe(403);
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
  });

  it("canal que não é meta_cloud → 400, sem enviar", async () => {
    instalar(base());
    expect((await post({ ...CORPO, channel_id: "ch-evo" })).status).toBe(400);
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
  });

  it("lead sem telefone (bling-) → 400 'Lead sem telefone', sem enviar", async () => {
    const { inseridos } = instalar(base());
    const res = await post(CORPO, "lead-bling");
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("Lead sem telefone");
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
    expect(inseridos).toHaveLength(0);
  });

  it("lead bloqueado / opt-out → 403 com a mensagem de bloqueio, sem enviar", async () => {
    const { inseridos } = instalar(base());
    vi.mocked(isLeadBlocked).mockResolvedValue(true);
    const res = await post(CORPO);
    expect(res.status).toBe(403);
    expect((await res.json()).error).toBe("bloqueado");
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
    expect(inseridos).toHaveLength(0);
  });

  it("conversa do par já existe com status blocked → 403, sem enviar", async () => {
    const t = base();
    t.conversations.push({ id: "conv-x", lead_id: "lead-1", channel_id: "ch-a", status: "blocked", stage: "secretaria" });
    instalar(t);
    const res = await post(CORPO);
    expect(res.status).toBe(403);
    expect((await res.json()).error).toBe("bloqueado");
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
  });
});

describe("POST iniciar-conversa — envio", () => {
  it("sem conversa do par: cria, envia ao telefone limpo e grava; 200 com o id", async () => {
    const { inseridos } = instalar(base());
    const res = await post(CORPO);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ conversation_id: "conversations-nova" });
    expect(inseridos).toEqual([
      {
        tabela: "conversations",
        row: { lead_id: "lead-1", channel_id: "ch-a", stage: "secretaria", status: "active" },
      },
    ]);
    expect(sendTemplateViaMeta).toHaveBeenCalledWith(CFG, "5534988861441", "boas_vindas", "pt_BR", { nome: "Ana" });
    expect(registrarTemplateEnviado).toHaveBeenCalledWith(expect.anything(), {
      conversationId: "conversations-nova",
      leadId: "lead-1",
      channel: expect.objectContaining({ id: "ch-a", provider_config: CFG }),
      templateName: "boas_vindas",
      templateLanguageCode: "pt_BR",
      templateBody: "Oi Ana",
      sentWamid: "wamid.X",
    });
  });

  it("conversa do par já existe: não cria, envia nela; 200 com o id dela", async () => {
    const t = base();
    t.conversations.push({ id: "conv-old", lead_id: "lead-1", channel_id: "ch-a", status: "active", stage: "atacado" });
    const { inseridos } = instalar(t);
    const res = await post(CORPO);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ conversation_id: "conv-old" });
    expect(inseridos).toHaveLength(0);
    expect(registrarTemplateEnviado).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ conversationId: "conv-old" }),
    );
  });

  it("Meta recusa com conversa criada agora: apaga só ela (sem mensagens) e devolve 502", async () => {
    const t = base();
    const { apagados } = instalar(t);
    vi.mocked(sendTemplateViaMeta).mockRejectedValue(new MetaRecusou("Meta API 400: template inválido"));
    const res = await post(CORPO);
    expect(res.status).toBe(502);
    expect((await res.json()).error).toBe("Meta API 400: template inválido");
    expect(apagados).toEqual([
      {
        tabela: "conversations",
        filtros: [["id", "conversations-nova"], ["status", "active"], ["last_msg_at", null]],
      },
    ]);
    expect(t.conversations).toHaveLength(0);
    expect(registrarTemplateEnviado).not.toHaveBeenCalled();
  });

  it("Meta recusa com conversa que já existia: não apaga nada, 502", async () => {
    const t = base();
    t.conversations.push({ id: "conv-old", lead_id: "lead-1", channel_id: "ch-a", status: "active", stage: "secretaria" });
    const { apagados } = instalar(t);
    vi.mocked(sendTemplateViaMeta).mockRejectedValue(new MetaRecusou("Meta API 400: x"));
    const res = await post(CORPO);
    expect(res.status).toBe(502);
    expect(apagados).toHaveLength(0);
    expect(registrarTemplateEnviado).not.toHaveBeenCalled();
  });

  it("falha incerta (rede/timeout/JSON): não apaga a conversa criada; 502 pedindo para conferir", async () => {
    const t = base();
    const { apagados } = instalar(t);
    vi.mocked(sendTemplateViaMeta).mockRejectedValue(new TypeError("fetch failed"));
    const res = await post(CORPO);
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({
      error: "Não deu para confirmar o envio. Confira a conversa antes de tentar de novo.",
      conversation_id: "conversations-nova",
    });
    expect(apagados).toHaveLength(0);
    expect(t.conversations.map((c) => c.id)).toEqual(["conversations-nova"]);
    expect(registrarTemplateEnviado).not.toHaveBeenCalled();
  });

  it("Meta recusa, conversa criada agora mas já com mensagem: não apaga", async () => {
    const t = base();
    const { apagados } = instalar(t);
    vi.mocked(sendTemplateViaMeta).mockImplementation(async () => {
      // Outro processo grava na conversa enquanto a Meta responde.
      t.messages.push({ id: "m1", conversation_id: "conversations-nova" });
      throw new MetaRecusou("Meta API 400: x");
    });
    const res = await post(CORPO);
    expect(res.status).toBe(502);
    expect(apagados).toHaveLength(0);
    expect(t.conversations.map((c) => c.id)).toEqual(["conversations-nova"]);
  });

  it("Meta recusa, conversa criada agora já com last_msg_at: o delete condicionado não apaga", async () => {
    const t = base();
    instalar(t);
    vi.mocked(sendTemplateViaMeta).mockImplementation(async () => {
      // Mensagem chegou e marcou a conversa (a linha da mensagem ainda não é visível).
      const conv = t.conversations.find((c) => c.id === "conversations-nova")!;
      conv.last_msg_at = "2026-10-31T10:00:00Z";
      throw new MetaRecusou("Meta API 400: x");
    });
    const res = await post(CORPO);
    expect(res.status).toBe(502);
    expect(t.conversations.map((c) => c.id)).toEqual(["conversations-nova"]);
  });
});

describe("POST iniciar-conversa — erro ao buscar a conversa do par", () => {
  it("select da conversa existente dá erro → 500, sem criar nem enviar", async () => {
    const { inseridos } = instalar(base(), ["conversations"]);
    const res = await post(CORPO);
    expect(res.status).toBe(500);
    expect(inseridos).toHaveLength(0);
    expect(sendTemplateViaMeta).not.toHaveBeenCalled();
  });
});

describe("sendTemplateViaMeta (real, fetch dublê)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("resposta não-ok da Meta vira MetaRecusou com a mesma mensagem", async () => {
    const real = await vi.importActual<typeof import("@/lib/meta-template")>("@/lib/meta-template");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("template inválido", { status: 400 })));
    const erro = await real.sendTemplateViaMeta(CFG, "5534988861441", "x", "pt_BR", null).catch((e) => e);
    expect(erro).toBeInstanceOf(real.MetaRecusou);
    expect(erro).toBeInstanceOf(Error);
    expect((erro as Error).message).toBe("Meta API 400: template inválido");
  });

  it("falha de rede e JSON inválido NÃO são MetaRecusou", async () => {
    const real = await vi.importActual<typeof import("@/lib/meta-template")>("@/lib/meta-template");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    const rede = await real.sendTemplateViaMeta(CFG, "5534988861441", "x", "pt_BR", null).catch((e) => e);
    expect(rede).toBeInstanceOf(Error);
    expect(rede).not.toBeInstanceOf(real.MetaRecusou);

    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 200 })));
    const json = await real.sendTemplateViaMeta(CFG, "5534988861441", "x", "pt_BR", null).catch((e) => e);
    expect(json).toBeInstanceOf(Error);
    expect(json).not.toBeInstanceOf(real.MetaRecusou);
  });
});

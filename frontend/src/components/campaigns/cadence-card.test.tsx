/**
 * @vitest-environment jsdom
 *
 * Não há precedente de teste deste componente com `fetch` mockado — segue a mesma
 * convenção de `esteiras-tab.test.tsx` (o primeiro teste de componente do repo):
 * imports explícitos do vitest, `global.fetch = vi.fn()`, comentários em português
 * explicando o porquê.
 *
 * Contrato exercitado: POST /api/campaigns/{id}/activate (e /pause), hoje um proxy
 * puro para `backend/app/campaigns/router.py`, que valida 12 regras antes de deixar
 * ativar e recusa com 400 + `{detail: {problemas: [{no_id, codigo, mensagem}]}}`.
 *
 * O bug fechado aqui: `handleToggle` fazia `alert(data.error ?? "Erro ao ativar: " +
 * res.statusText)`. Com `detail.problemas[]` (não `error`), o operador só via um
 * "Bad Request" genérico — nunca os motivos de verdade, e nunca os três de uma vez
 * quando havia mais de um problema.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { CadenceCard, parseActivationErrorMessages } from "./cadence-card";
import type { Campaign } from "@/lib/types";

const CAMPANHA: Campaign = {
  id: "camp-1",
  name: "Cadência de teste",
  description: null,
  status: "draft",
  channel_id: null,
  env_tag: "prod",
  start_date: null,
  created_at: "2026-09-16T12:00:00Z",
  updated_at: "2026-09-16T12:00:00Z",
  nodes: [],
};

type Corpo = Record<string, unknown>;
const resposta = (corpo: Corpo, status = 200) =>
  ({ ok: status < 400, status, statusText: "Bad Request", json: async () => corpo }) as Response;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CadenceCard — recusa de ativação aparece na tela", () => {
  it("resposta 400 com detail.problemas[] de 3 itens mostra as TRÊS mensagens, não só a primeira", async () => {
    // Quem monta a campanha quer consertar tudo numa passada, não descobrir um
    // problema por vez — clicar, corrigir, clicar de novo, descobrir o segundo.
    const problemas = [
      { no_id: "n1", codigo: "template_nao_aprovado", mensagem: "O toque 3 usa o template promo_v2, ainda em análise na Meta." },
      { no_id: "n2", codigo: "canal_ausente", mensagem: "O nó de envio não tem canal configurado." },
      { no_id: null, codigo: "ciclo", mensagem: "O fluxo tem um ciclo: o nó final aponta de volta para o início." },
    ];
    global.fetch = vi.fn(async () => resposta({ detail: { problemas } }, 400)) as unknown as typeof fetch;
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    render(<CadenceCard campaign={CAMPANHA} onClick={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(alertSpy).toHaveBeenCalledTimes(1));
    const mensagem = String(alertSpy.mock.calls[0][0]);
    for (const p of problemas) expect(mensagem).toContain(p.mensagem);
  });

  it("resposta com {error} string (proxy quando o backend está fora do ar) continua mostrando", async () => {
    // Formato do proxy Next em `activate/route.ts` quando o fetch pro FastAPI falha:
    // `NextResponse.json({ error: "Backend indisponível" }, { status: 502 })`.
    global.fetch = vi.fn(async () => resposta({ error: "Backend indisponível" }, 502)) as unknown as typeof fetch;
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    render(<CadenceCard campaign={CAMPANHA} onClick={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(alertSpy).toHaveBeenCalledWith("Backend indisponível"));
  });

  it("200 ativa normalmente — sem alert, chama onRefresh", async () => {
    global.fetch = vi.fn(async () => resposta({ status: "active" }, 200)) as unknown as typeof fetch;
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    const onRefresh = vi.fn();

    render(<CadenceCard campaign={CAMPANHA} onClick={vi.fn()} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("corpo inesperado (sem error e sem detail.problemas) não fica em silêncio", async () => {
    // Silêncio nunca é resposta aceitável para uma recusa — mesmo que o formato do
    // corpo seja uma surpresa (contrato novo, campo renomeado, etc.).
    global.fetch = vi.fn(async () => resposta({ algo_inesperado: true }, 400)) as unknown as typeof fetch;
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    render(<CadenceCard campaign={CAMPANHA} onClick={vi.fn()} onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(alertSpy).toHaveBeenCalledTimes(1));
    expect(String(alertSpy.mock.calls[0][0]).trim().length).toBeGreaterThan(0);
  });
});

// ── Helper puro — é aqui que mora a lógica de verdade ────────────────────────────
describe("parseActivationErrorMessages (helper puro)", () => {
  it("detail.problemas[] vira uma mensagem por problema, na ordem", () => {
    const corpo = { detail: { problemas: [{ mensagem: "a" }, { mensagem: "b" }, { mensagem: "c" }] } };
    expect(parseActivationErrorMessages(corpo)).toEqual(["a", "b", "c"]);
  });

  it("{error: string} vira mensagem única", () => {
    expect(parseActivationErrorMessages({ error: "fora do ar" })).toEqual(["fora do ar"]);
  });

  it("corpo sem error e sem detail.problemas nunca devolve [] — sempre uma mensagem genérica", () => {
    expect(parseActivationErrorMessages({})).toHaveLength(1);
    expect(parseActivationErrorMessages(null)).toHaveLength(1);
    expect(parseActivationErrorMessages(undefined)).toHaveLength(1);
  });

  it("detail.problemas presente mas vazio conta como inesperado (não alerta em branco)", () => {
    // Sem esta guarda, `[].join("\n\n")` é uma string vazia — um alert() mudo.
    expect(parseActivationErrorMessages({ detail: { problemas: [] } })).toHaveLength(1);
  });

  it("problema sem `mensagem` usável ainda vira texto, não undefined/[object Object]", () => {
    expect(parseActivationErrorMessages({ detail: { problemas: [{ codigo: "x" }] } })).toEqual(["Problema não especificado."]);
  });
});

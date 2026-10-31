/**
 * @vitest-environment jsdom
 *
 * Cartão 70d844a6: o link /conversas?lead_id= precisa abrir a conversa do lead,
 * trocar de conversa quando chega um segundo link e avisar quando o lead não tem
 * conversa (em vez de ficar calado na lista).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor, cleanup } from "@testing-library/react";
import type { Conversation } from "@/lib/types";
import { useDeepLinkLead, type DeepLinkLeadOptions } from "./use-deep-link-lead";

const conv = (id: string, leadId: string) =>
  ({ id, lead_id: leadId, leads: { id: leadId, name: id } }) as unknown as Conversation;

function opcoes(over: Partial<DeepLinkLeadOptions> = {}): DeepLinkLeadOptions {
  return {
    leadId: null,
    ready: true,
    conversations: [],
    ensureInList: vi.fn(),
    onFound: vi.fn(),
    onNotFound: vi.fn(),
    clearUrl: vi.fn(),
    ...over,
  };
}

function apiResponde(conversations: Conversation[], ok = true) {
  const f = vi.fn(async () => ({ ok, status: ok ? 200 : 500, json: async () => ({ conversations, next_cursor: null }) }));
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("useDeepLinkLead", () => {
  it("lead na lista carregada: seleciona sem ir à API e limpa a URL", () => {
    const f = apiResponde([]);
    const o = opcoes({ leadId: "L1", conversations: [conv("c1", "L1")] });
    renderHook(() => useDeepLinkLead(o));
    expect(o.onFound).toHaveBeenCalledWith(expect.objectContaining({ id: "c1" }));
    expect(o.clearUrl).toHaveBeenCalled();
    expect(f).not.toHaveBeenCalled();
  });

  it("espera a lista carregar (ready=false não faz nada)", () => {
    const f = apiResponde([]);
    const o = opcoes({ leadId: "L1", ready: false });
    renderHook(() => useDeepLinkLead(o));
    expect(o.onFound).not.toHaveBeenCalled();
    expect(f).not.toHaveBeenCalled();
  });

  it("lead fora da lista: busca na API, injeta e seleciona", async () => {
    const f = apiResponde([conv("c9", "L9")]);
    const o = opcoes({ leadId: "L9" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(o.onFound).toHaveBeenCalledWith(expect.objectContaining({ id: "c9" })));
    expect(f).toHaveBeenCalledWith("/api/conversations?lead_id=L9");
    expect(o.ensureInList).toHaveBeenCalledWith(expect.objectContaining({ id: "c9" }));
    expect(o.clearUrl).toHaveBeenCalled();
    expect(result.current.leadSemConversa).toBeNull();
  });

  it("lead sem conversa: avisa com o id do lead e chama onNotFound", async () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L0" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(result.current.leadSemConversa).toBe("L0"));
    expect(o.onNotFound).toHaveBeenCalled();
    expect(o.onFound).not.toHaveBeenCalled();
    expect(o.clearUrl).toHaveBeenCalled();
  });

  it("falha da API não afirma que o lead não tem conversa", async () => {
    apiResponde([], false);
    const o = opcoes({ leadId: "L0" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(o.clearUrl).toHaveBeenCalled());
    expect(result.current.leadSemConversa).toBeNull();
    expect(o.onNotFound).not.toHaveBeenCalled();
  });

  it("segundo link com outro lead na mesma montagem troca a seleção", () => {
    apiResponde([]);
    const lista = [conv("c1", "L1"), conv("c2", "L2")];
    const o = opcoes({ leadId: "L1", conversations: lista });
    const { rerender } = renderHook((p: DeepLinkLeadOptions) => useDeepLinkLead(p), { initialProps: o });
    rerender({ ...o, leadId: null }); // router.replace("/conversas") limpou a URL
    rerender({ ...o, leadId: "L2" }); // popup de SLA / notificação empurra outro lead
    expect(o.onFound).toHaveBeenNthCalledWith(1, expect.objectContaining({ id: "c1" }));
    expect(o.onFound).toHaveBeenNthCalledWith(2, expect.objectContaining({ id: "c2" }));
  });

  it("o mesmo link não é reaplicado a cada mudança da lista", () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L1", conversations: [conv("c1", "L1")] });
    const { rerender } = renderHook((p: DeepLinkLeadOptions) => useDeepLinkLead(p), { initialProps: o });
    rerender({ ...o, conversations: [conv("c1", "L1"), conv("c3", "L3")] });
    expect(o.onFound).toHaveBeenCalledTimes(1);
  });

  it("dispensar apaga o aviso", async () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L0" });
    const { result } = renderHook(() => useDeepLinkLead(o));
    await waitFor(() => expect(result.current.leadSemConversa).toBe("L0"));
    result.current.dispensar();
    await waitFor(() => expect(result.current.leadSemConversa).toBeNull());
  });
  // Revisão do cartão 70d844a6: a resposta de um link antigo não pode limpar a URL
  // (isso zera a marca e faz o link novo ser descartado, calado).
  it("resposta de um link antigo não mexe em nada, nem na URL", async () => {
    const pendentes: Record<string, (c: Conversation[]) => void> = {};
    vi.stubGlobal("fetch", vi.fn((url: string) => new Promise((resolve) => {
      const lead = new URL(url, "http://x").searchParams.get("lead_id") as string;
      pendentes[lead] = (conversations) =>
        resolve({ ok: true, status: 200, json: async () => ({ conversations, next_cursor: null }) });
    })));
    const o = opcoes({ leadId: "LA" });
    const { rerender, result } = renderHook((p: DeepLinkLeadOptions) => useDeepLinkLead(p), { initialProps: o });
    rerender({ ...o, leadId: "LB" });
    await waitFor(() => expect(pendentes.LB).toBeDefined());

    pendentes.LA([]); // LA "sem conversa", mas chegou atrasada
    await new Promise((r) => setTimeout(r, 0));
    expect(o.clearUrl).not.toHaveBeenCalled();
    expect(o.onNotFound).not.toHaveBeenCalled();
    expect(result.current.leadSemConversa).toBeNull();

    pendentes.LB([conv("cB", "LB")]);
    await waitFor(() => expect(o.onFound).toHaveBeenCalledWith(expect.objectContaining({ id: "cB" })));
    expect(o.clearUrl).toHaveBeenCalledTimes(1);
  });

  it("um link novo apaga o aviso do lead anterior (mesmo se a busca falhar)", async () => {
    apiResponde([]);
    const o = opcoes({ leadId: "L0" });
    const { rerender, result } = renderHook((p: DeepLinkLeadOptions) => useDeepLinkLead(p), { initialProps: o });
    await waitFor(() => expect(result.current.leadSemConversa).toBe("L0"));

    apiResponde([], false);
    rerender({ ...o, leadId: null });
    rerender({ ...o, leadId: "L2" });
    await waitFor(() => expect(result.current.leadSemConversa).toBeNull());
  });
});

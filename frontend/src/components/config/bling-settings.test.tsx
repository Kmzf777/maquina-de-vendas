/**
 * @vitest-environment jsdom
 *
 * Cobre o que mudou nesta task: uma linha por conta em /config, o aviso de
 * expiracao do refresh_token disparando POR CONTA (nao mais um unico booleano
 * para a integracao inteira), e o resultado de sync renderizado aninhado por
 * conta, inclusive quando uma conta falha isoladamente. Segue o padrao de
 * mock por substring de URL de esteiras-tab.test.tsx (primeiro teste de
 * componente do repositorio).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BlingSettings } from "./bling-settings";

type Corpo = Record<string, unknown> | unknown[];
const resposta = (corpo: Corpo, status = 200) =>
  ({ ok: status < 400, status, json: async () => corpo }) as Response;

const agora = Date.now();
const emDias = (n: number) => new Date(agora + n * 86_400_000).toISOString();

const CONTA_1 = {
  account: "default", label: "Canastra CNPJ 1", configured: true, connected: true,
  access_expires_at: null as string | null, refresh_expires_at: emDias(20), scope: "s",
};
const CONTA_2 = {
  account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true,
  access_expires_at: null as string | null, refresh_expires_at: emDias(20), scope: "s",
};

function statusCom(accounts: (typeof CONTA_1)[]): Corpo {
  return {
    enabled: true, connected: true, configured: true,
    access_expires_at: null, refresh_expires_at: null, scope: null,
    accounts,
  };
}

/** Mock do fetch global casando por substring da URL, mesmo padrao de esteiras-tab. */
function mockarFetch(status: Corpo, opts: { sync?: Corpo } = {}) {
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.includes("/api/bling/status")) return resposta(status);
    if (u.includes("/api/bling/sync")) return resposta(opts.sync ?? {});
    if (u.includes("/api/bling/sellers")) return resposta({ data: [] });
    if (u.includes("/api/bling/seller-map")) return resposta({ data: [] });
    if (u.includes("/api/users")) return resposta([]);
    return resposta({});
  }) as unknown as typeof fetch;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("BlingSettings", () => {
  it("lista uma linha por conta, rotulada com o label de cada uma", async () => {
    mockarFetch(statusCom([CONTA_1, CONTA_2]));
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("Canastra CNPJ 1")).toBeTruthy());
    expect(screen.getByText("Canastra CNPJ 2")).toBeTruthy();
    // Cada linha tem seu proprio pill de status — duas contas, dois "Conectado".
    expect(screen.getAllByText("Conectado").length).toBe(2);
  });

  it("aviso de expiracao dispara SO na conta perto de vencer, nao na outra", async () => {
    mockarFetch(statusCom([
      { ...CONTA_1, refresh_expires_at: emDias(3) },   // dentro dos 5 dias: avisa
      { ...CONTA_2, refresh_expires_at: emDias(20) },  // longe: nao avisa
    ]));
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getAllByText(/Autorização expirando/).length).toBe(1));
    // A conta 2 aparece na tela (linha dela existe) mas sem o aviso.
    expect(screen.getByText("Canastra CNPJ 2")).toBeTruthy();
  });

  it("sem nenhuma conta perto de vencer, nao mostra aviso nenhum", async () => {
    mockarFetch(statusCom([CONTA_1, CONTA_2]));
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("Canastra CNPJ 1")).toBeTruthy());
    expect(screen.queryByText(/Autorização expirando/)).toBeNull();
  });

  it("credenciais ausentes aparecem so na linha da conta sem credencial", async () => {
    mockarFetch(statusCom([
      CONTA_1,
      { ...CONTA_2, configured: false, connected: false },
    ]));
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText(/BLING_SECUNDARIA_CLIENT_ID/)).toBeTruthy());
    // A conta configurada nao ganha o aviso da outra.
    expect(screen.queryByText(/Credenciais do app Bling ausentes no servidor\./)).toBeNull();
  });

  it("resultado do sync vem aninhado por conta, inclusive quando uma conta falha", async () => {
    mockarFetch(statusCom([CONTA_1, CONTA_2]), {
      sync: {
        default: { produtos: 10, contatos: 3 },
        secundaria: { erro: "401 token expirado" },
      },
    });
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("Canastra CNPJ 1")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /Sincronizar agora/i }));

    await waitFor(() => expect(screen.getByText(/401 token expirado/)).toBeTruthy());
    expect(screen.getByText(/Produtos/)).toBeTruthy();
    expect(screen.getByText(/Contatos/)).toBeTruthy();
  });
});

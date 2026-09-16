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

const USUARIOS = [{ id: "u1", name: "João Brás", email: "joao@x.com" }];

/** Vendedores espelhados de cada CNPJ — ids diferentes, que e o ponto. */
const VENDEDORES: Record<string, { id: number; nome: string }[]> = {
  default: [{ id: 111, nome: "João do CNPJ 1" }],
  secundaria: [{ id: 222, nome: "João do CNPJ 2" }],
};

type LinhaVinculo = { user_email: string; account: string; bling_seller_id: number };

/**
 * Mock focado no bloco "Vendedores": responde `/api/bling/sellers` conforme o
 * `?account=` pedido e registra os PUTs de `/api/bling/seller-map`.
 */
function mockarVendedores(
  opts: { contas?: (typeof CONTA_1)[]; vinculos?: LinhaVinculo[] } = {},
) {
  const puts: string[] = [];
  const urls: string[] = [];
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    urls.push(u);
    if (u.includes("/api/bling/status")) {
      return resposta(statusCom(opts.contas ?? [CONTA_1, CONTA_2]));
    }
    if (u.includes("/api/bling/sellers")) {
      const conta = new URL(u, "http://x").searchParams.get("account") ?? "default";
      return resposta({ data: VENDEDORES[conta] ?? [] });
    }
    if (u.includes("/api/bling/seller-map")) {
      if (init?.method === "PUT") {
        puts.push(String(init.body));
        return resposta({ ok: true });
      }
      return resposta({ data: opts.vinculos ?? [] });
    }
    if (u.includes("/api/users")) return resposta(USUARIOS);
    return resposta({});
  }) as unknown as typeof fetch;
  return { puts, urls };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("BlingSettings", () => {
  it("lista uma linha por conta, rotulada com o label de cada uma", async () => {
    mockarFetch(statusCom([CONTA_1, CONTA_2]));
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("Canastra CNPJ 1", { selector: "p" })).toBeTruthy());
    expect(screen.getByText("Canastra CNPJ 2", { selector: "p" })).toBeTruthy();
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
    expect(screen.getByText("Canastra CNPJ 2", { selector: "p" })).toBeTruthy();
  });

  it("sem nenhuma conta perto de vencer, nao mostra aviso nenhum", async () => {
    mockarFetch(statusCom([CONTA_1, CONTA_2]));
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("Canastra CNPJ 1", { selector: "p" })).toBeTruthy());
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
    await waitFor(() => expect(screen.getByText("Canastra CNPJ 1", { selector: "p" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /Sincronizar agora/i }));

    await waitFor(() => expect(screen.getByText(/401 token expirado/)).toBeTruthy());
    expect(screen.getByText(/Produtos/)).toBeTruthy();
    expect(screen.getByText(/Contatos/)).toBeTruthy();
  });
});

describe("BlingSettings — vendedores por conta", () => {
  it("o seletor de conta troca a lista de vendedores oferecida", async () => {
    mockarVendedores();
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("João do CNPJ 1")).toBeTruthy());

    fireEvent.change(screen.getByLabelText("Conta"), {
      target: { value: "secundaria" },
    });

    await waitFor(() => expect(screen.getByText("João do CNPJ 2")).toBeTruthy());
    // A lista TROCA, nao acumula: oferecer o vendedor do outro CNPJ seria
    // oferecer um id que nao existe na conta que vai emitir o pedido.
    expect(screen.queryByText("João do CNPJ 1")).toBeNull();
  });

  it("salva o vinculo NA CONTA selecionada, nao na default", async () => {
    const { puts } = mockarVendedores();
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("João do CNPJ 1")).toBeTruthy());

    fireEvent.change(screen.getByLabelText("Conta"), {
      target: { value: "secundaria" },
    });
    await waitFor(() => expect(screen.getByText("João do CNPJ 2")).toBeTruthy());

    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 1], { target: { value: "222" } });

    await waitFor(() => expect(puts.length).toBe(1));
    expect(JSON.parse(puts[0])).toMatchObject({
      user_email: "joao@x.com",
      account: "secundaria",
      bling_seller_id: 222,
    });
  });

  it("mostra o vinculo DA CONTA selecionada quando o e-mail tem um em cada", async () => {
    mockarVendedores({
      vinculos: [
        { user_email: "joao@x.com", account: "default", bling_seller_id: 111 },
        { user_email: "joao@x.com", account: "secundaria", bling_seller_id: 222 },
      ],
    });
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("João do CNPJ 1")).toBeTruthy());

    const vendedor = () =>
      screen.getAllByRole("combobox").at(-1) as HTMLSelectElement;
    expect(vendedor().value).toBe("111");

    fireEvent.change(screen.getByLabelText("Conta"), {
      target: { value: "secundaria" },
    });
    await waitFor(() => expect(screen.getByText("João do CNPJ 2")).toBeTruthy());

    // Indexar so por e-mail colapsaria as duas linhas e mostraria o vendedor
    // da conta errada — que e o defeito que `indexarVinculos` existe para evitar.
    expect(vendedor().value).toBe("222");
  });

  it("cai para a conta conectada quando a default nao esta", async () => {
    mockarVendedores({
      contas: [{ ...CONTA_1, configured: false, connected: false }, CONTA_2],
    });
    render(<BlingSettings />);

    // Sem isto o quadro ficaria preso na 'default' (estado inicial), que nao
    // tem espelho nenhum — e o admin nao teria como mapear a conta que funciona.
    await waitFor(() => expect(screen.getByText("João do CNPJ 2")).toBeTruthy());
  });

  it("com uma conta so, nao mostra seletor — a tela fica como era", async () => {
    mockarVendedores({ contas: [CONTA_1] });
    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("João do CNPJ 1")).toBeTruthy());

    expect(screen.queryByLabelText("Conta")).toBeNull();
  });
});

describe("BlingSettings — rollback do vinculo", () => {
  it("falha de rede devolve o vinculo A CONTA de onde ele saiu", async () => {
    global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/api/bling/status")) {
        return resposta(statusCom([CONTA_1, CONTA_2]));
      }
      if (u.includes("/api/bling/sellers")) {
        const conta = new URL(u, "http://x").searchParams.get("account") ?? "default";
        return resposta({ data: VENDEDORES[conta] ?? [] });
      }
      if (u.includes("/api/bling/seller-map")) {
        if (init?.method === "PUT") throw new Error("rede caiu");
        return resposta({
          data: [{ user_email: "joao@x.com", account: "secundaria", bling_seller_id: 222 }],
        });
      }
      if (u.includes("/api/users")) return resposta(USUARIOS);
      return resposta({});
    }) as unknown as typeof fetch;

    render(<BlingSettings />);
    await waitFor(() => expect(screen.getByText("João do CNPJ 1")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Conta"), {
      target: { value: "secundaria" },
    });
    await waitFor(() => expect(screen.getByText("João do CNPJ 2")).toBeTruthy());

    const vendedor = () =>
      screen.getAllByRole("combobox").at(-1) as HTMLSelectElement;
    expect(vendedor().value).toBe("222");

    fireEvent.change(vendedor(), { target: { value: "" } });

    await waitFor(() => expect(screen.getByText("Backend inacessível.")).toBeTruthy());
    // O desfazer tem que voltar para a MESMA celula (conta + e-mail) de onde
    // o valor saiu — devolver na chave de e-mail cru perde o vinculo na tela.
    expect(vendedor().value).toBe("222");
  });
});

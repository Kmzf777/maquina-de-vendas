import { describe, expect, it } from "vitest";
import {
  CONTA_PADRAO,
  CONTA_PREFERIDA,
  contasDisponiveis,
  precisaSeletor,
  contaPadrao,
  trocaLimpaFormulario,
  interpretarStatus,
} from "./bling-accounts";

const CONTAS = [
  { account: "default", label: "Canastra CNPJ 1", configured: true, connected: true },
  { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
];

describe("contasDisponiveis", () => {
  it("devolve so as conectadas", () => {
    const contas = [...CONTAS, {
      account: "terceira", label: "T", configured: true, connected: false,
    }];
    expect(contasDisponiveis(contas).map((c) => c.account))
      .toEqual(["default", "secundaria"]);
  });

  it("devolve vazio quando nenhuma esta conectada", () => {
    expect(contasDisponiveis([{ ...CONTAS[0], connected: false }])).toEqual([]);
  });
});

describe("precisaSeletor", () => {
  it("esconde o seletor com uma conta so", () => {
    expect(precisaSeletor([CONTAS[0]])).toBe(false);
  });

  it("mostra o seletor com duas contas", () => {
    expect(precisaSeletor(CONTAS)).toBe(true);
  });

  // Consequencia para a Task 15 codificada aqui: com skipBling a venda nao vai
  // para ERP nenhum, entao a escolha de CNPJ some mesmo com duas contas
  // conectadas — oferece-la sugeriria um efeito que nao existe.
  it("esconde o seletor quando skipBling esta ligado, mesmo com duas contas", () => {
    expect(precisaSeletor(CONTAS, true)).toBe(false);
  });

  it("skipBling desligado (explicito) nao muda o resultado", () => {
    expect(precisaSeletor(CONTAS, false)).toBe(true);
  });
});

describe("contaPadrao", () => {
  it("prefere a CONTA_PREFERIDA (Cafe Rural) quando conectada", () => {
    expect(contaPadrao(CONTAS)).toBe("secundaria");
  });

  // O degrau 2 da escada, e a razao de ele existir: com a preferida fora do ar
  // a tela volta para a conta que todo mundo conhece, nao para a primeira da
  // lista por acaso.
  it("cai para a CONTA_PADRAO quando a preferida nao esta conectada", () => {
    const contas = [
      CONTAS[0],
      { ...CONTAS[1], connected: false },
      { account: "terceira", label: "T", configured: true, connected: true },
    ];
    expect(contaPadrao(contas)).toBe("default");
  });

  it("cai para a primeira conectada quando nem a preferida nem a padrao estao", () => {
    const contas = [
      { ...CONTAS[0], connected: false },
      { ...CONTAS[1], connected: false },
      { account: "terceira", label: "T", configured: true, connected: true },
    ];
    expect(contaPadrao(contas)).toBe("terceira");
  });

  it("devolve null sem nenhuma conta conectada", () => {
    expect(contaPadrao([{ ...CONTAS[0], connected: false }])).toBeNull();
  });

  // Trava de identidade: o slug historico nao pode ser arrastado pela mudanca
  // de preferencia. Se este teste quebrar, toda venda antiga sem bling_account
  // passou a ser rotulada como Cafe Rural.
  it("CONTA_PADRAO continua sendo o slug da conta 1", () => {
    expect(CONTA_PADRAO).toBe("default");
    expect(CONTA_PREFERIDA).toBe("secundaria");
  });
});

describe("trocaLimpaFormulario", () => {
  it("nao pede confirmacao com o formulario vazio", () => {
    expect(trocaLimpaFormulario({ itens: 0, contatoId: null })).toBe(false);
  });

  it("pede confirmacao quando ha itens", () => {
    expect(trocaLimpaFormulario({ itens: 2, contatoId: null })).toBe(true);
  });

  it("pede confirmacao quando ha contato escolhido", () => {
    expect(trocaLimpaFormulario({ itens: 0, contatoId: 55 })).toBe(true);
  });
});

// `useBlingStatus` nao tem suite propria: o projeto nao roda DOM (ver
// vitest.config.ts, environment "node") e o hook e so uma casca de
// useState/useEffect em cima desta funcao. Testar `interpretarStatus` isolada
// e o jeito de garantir que o booleano do hook continua funcionando quando
// `accounts` falta no payload.
describe("interpretarStatus", () => {
  it("liga quando enabled e connected (da conta default) sao true", () => {
    expect(interpretarStatus({ enabled: true, connected: true }).enabled).toBe(true);
  });

  it("desliga quando falta refresh_token, mesmo com o toggle ligado", () => {
    expect(interpretarStatus({ enabled: true, connected: false }).enabled).toBe(false);
  });

  it("desliga quando o toggle esta desligado, mesmo com refresh_token", () => {
    expect(interpretarStatus({ enabled: false, connected: true }).enabled).toBe(false);
  });

  // O caso que da nome ao teste: a rota Next devolve so {enabled, connected}
  // para quem nao e admin (`app/api/bling/status/route.ts`) — `accounts` nem
  // existe no payload nesse caso. O booleano top-level tem que continuar
  // valendo, senao um vendedor nao-admin nunca entraria em modo Bling.
  it("mantem o booleano funcionando quando accounts falta no payload", () => {
    const resultado = interpretarStatus({ enabled: true, connected: true });
    expect(resultado.enabled).toBe(true);
    expect(resultado.accounts).toEqual([]);
  });

  it("accounts vazio no payload tambem vira lista vazia, sem derrubar o booleano", () => {
    const resultado = interpretarStatus({ enabled: true, connected: true, accounts: [] });
    expect(resultado.enabled).toBe(true);
    expect(resultado.accounts).toEqual([]);
  });

  it("repassa accounts quando o payload traz (papel admin)", () => {
    const resultado = interpretarStatus({ enabled: true, connected: true, accounts: CONTAS });
    expect(resultado.accounts).toBe(CONTAS);
  });
});

/**
 * @vitest-environment jsdom
 *
 * Trava o modo de falha descrito na Task 15: se o seletor de conta nunca
 * aparecer para o vendedor, toda venda cai em silencio na conta padrao — CNPJ
 * errado, sem erro na tela, descoberto semanas depois por quem concilia os
 * livros. Estes testes cobrem so a CASCA (visibilidade, ordem, rotulo,
 * travamento) — a decisao pura (`precisaSeletor`, `contaPadrao`,
 * `trocaLimpaFormulario`) ja e testada em `lib/bling-accounts.test.ts` e nao e
 * reproduzida aqui.
 *
 * Sem `@testing-library/jest-dom` (nao esta nas dependencias do projeto) —
 * as assercoes usam a API crua do DOM/`screen`, mesmo padrao de
 * `stage-target-picker.test.tsx`.
 *
 * Nao ha teste de abrir o Select e escolher outra conta: o projeto nao tem
 * precedente de testar o `@/components/ui/select` (Radix) em jsdom — nenhum
 * arquivo hoje interage com o popover dele — e Radix Select depende de APIs
 * que o jsdom nao implementa (`hasPointerCapture`, `scrollIntoView`) sem
 * polyfill nenhum configurado neste projeto. Abrir o popover aqui arriscaria
 * um teste fragil por um ganho pequeno: a troca em si e so tres `set` diretos
 * mais `trocaLimpaFormulario`, que ja esta coberta.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { BlingOrderForm } from "./bling-order-form";
import { CONTA_PADRAO, type ContaBling } from "@/lib/bling-accounts";

const CONTAS: ContaBling[] = [
  { account: CONTA_PADRAO, label: "Canastra CNPJ 1", configured: true, connected: true },
  { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
];

const META = {
  leadId: "lead-1",
  dealId: null,
  soldAt: "2026-09-15",
  soldBy: null,
  notes: "",
};

/** `Response` minimo — so o que o componente le (`.ok`/`.json()`). */
const resposta = (corpo: unknown) => ({ ok: true, json: async () => corpo }) as Response;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockFetchVazio() {
  global.fetch = vi.fn(() => Promise.resolve(resposta({ data: [] }))) as unknown as typeof fetch;
}

describe("BlingOrderForm — seletor de conta", () => {
  it("nao renderiza nada quando a prop `conta` esta ausente (recurso desligado)", () => {
    mockFetchVazio();
    render(<BlingOrderForm meta={META} onChange={vi.fn()} />);
    expect(screen.queryByText("Conta Bling *")).toBeNull();
  });

  it("nao renderiza com uma unica conta conectada — nada muda para quem usa o CRM hoje", () => {
    mockFetchVazio();
    render(
      <BlingOrderForm
        meta={META}
        onChange={vi.fn()}
        conta={{ contas: [CONTAS[0]], onChange: vi.fn() }}
      />,
    );
    expect(screen.queryByText("Conta Bling *")).toBeNull();
  });

  it("some quando skipBling esta marcado, mesmo com duas contas conectadas", () => {
    mockFetchVazio();
    render(
      <BlingOrderForm
        meta={META}
        onChange={vi.fn()}
        conta={{ contas: CONTAS, skipBling: true, onChange: vi.fn() }}
      />,
    );
    expect(screen.queryByText("Conta Bling *")).toBeNull();
  });

  it("aparece como o PRIMEIRO campo quando ha duas contas conectadas, e avisa o pai da conta padrao", async () => {
    mockFetchVazio();
    const aoMudarConta = vi.fn();
    const { container } = render(
      <BlingOrderForm
        meta={META}
        onChange={vi.fn()}
        conta={{ contas: CONTAS, onChange: aoMudarConta }}
      />,
    );

    expect(screen.queryByText("Conta Bling *")).not.toBeNull();
    // "Itens do pedido" e o campo que hoje e o primeiro do formulario — a
    // conta precisa vir ANTES dele no documento (R1 da Task 15).
    const texto = container.textContent ?? "";
    expect(texto.indexOf("Conta Bling")).toBeGreaterThanOrEqual(0);
    expect(texto.indexOf("Conta Bling")).toBeLessThan(texto.indexOf("Itens do pedido"));

    // Rotula com `label`, nunca o slug cru.
    expect(screen.queryByText("Canastra CNPJ 1")).not.toBeNull();
    expect(screen.queryByText(CONTA_PADRAO)).toBeNull();

    // Conta padrao e comunicada ao pai (ele precisa dela para as PROPRIAS
    // chamadas — POST do pedido, resolvedor de contato).
    await waitFor(() => expect(aoMudarConta).toHaveBeenCalledWith(CONTA_PADRAO));
  });

  it("so lista contas CONECTADAS como opcao selecionavel", () => {
    mockFetchVazio();
    const contasComDesconectada: ContaBling[] = [
      ...CONTAS,
      { account: "terceira", label: "Canastra CNPJ 3", configured: true, connected: false },
    ];
    render(
      <BlingOrderForm
        meta={META}
        onChange={vi.fn()}
        conta={{ contas: contasComDesconectada, onChange: vi.fn() }}
      />,
    );
    // O seletor aparece (ha 2 conectadas), mas a conta desconectada nao pode
    // ser a selecionada por padrao nem aparecer como texto do campo.
    expect(screen.queryByText("Conta Bling *")).not.toBeNull();
    expect(screen.queryByText("Canastra CNPJ 3")).toBeNull();
  });

  it("modo travado mostra a conta como somente-leitura, com a dica, sem controle interativo", () => {
    mockFetchVazio();
    render(
      <BlingOrderForm
        meta={META}
        onChange={vi.fn()}
        conta={{
          contas: CONTAS,
          travada: { valor: "secundaria", dica: "Definido pelo orçamento #7" },
          onChange: vi.fn(),
        }}
      />,
    );
    expect(screen.queryByText("Canastra CNPJ 2")).not.toBeNull();
    expect(screen.queryByText("Definido pelo orçamento #7")).not.toBeNull();
    // Nao e um <select>/combobox real — e um campo somente-leitura (mesmo
    // padrao do "Deal" travado em SaleCreateModal), entao nao ha o que abrir.
    // Escopado ao campo da conta (`nextElementSibling` do rotulo): o form tem
    // OUTRO combobox de verdade mais abaixo ("Forma de pagamento"), entao uma
    // busca no documento inteiro acusaria esse, nao o da conta.
    const rotulo = screen.getByText("Conta Bling *");
    const campo = rotulo.nextElementSibling;
    expect(campo?.querySelector('[role="combobox"]')).toBeNull();
  });

  it("modo travado cai para o proprio slug se a conta sumiu da lista corrente", () => {
    mockFetchVazio();
    render(
      <BlingOrderForm
        meta={META}
        onChange={vi.fn()}
        conta={{
          contas: CONTAS,
          travada: { valor: "descontinuada", dica: "Definido pelo orçamento #9" },
          onChange: vi.fn(),
        }}
      />,
    );
    expect(screen.queryByText("descontinuada")).not.toBeNull();
  });
});

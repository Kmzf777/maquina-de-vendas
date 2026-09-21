/**
 * @vitest-environment jsdom
 *
 * Cobre o mesmo risco de "seletor invisivel" da Task 15, aqui na secao de
 * vinculo lead-contato. `useBlingStatus` e mockado (em vez de deixado rodar
 * de verdade) porque o hook mantem um cache em memoria por MODULO
 * (`use-bling-status.ts`), compartilhado entre todos os testes deste arquivo
 * — sem o mock, o segundo teste herdaria a resposta cacheada do primeiro.
 *
 * Sem `@testing-library/jest-dom` (nao esta nas dependencias) — assercoes
 * usam a API crua do DOM/`screen`, mesmo padrao de `stage-target-picker.test.tsx`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LeadBlingSection } from "./lead-bling-section";
import { CONTA_PADRAO, CONTA_PREFERIDA, type ContaBling } from "@/lib/bling-accounts";

const UMA_CONTA: ContaBling[] = [
  { account: CONTA_PADRAO, label: "Canastra CNPJ 1", configured: true, connected: true },
];
const DUAS_CONTAS: ContaBling[] = [
  ...UMA_CONTA,
  { account: "secundaria", label: "Canastra CNPJ 2", configured: true, connected: true },
];

const mockUseBlingStatus = vi.fn();
vi.mock("@/hooks/use-bling-status", () => ({
  useBlingStatus: () => mockUseBlingStatus(),
}));

const resposta = (corpo: unknown) => ({ ok: true, json: async () => corpo }) as Response;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  mockUseBlingStatus.mockReset();
});

describe("LeadBlingSection — seletor de conta", () => {
  it("nao renderiza o seletor com uma unica conta conectada", () => {
    mockUseBlingStatus.mockReturnValue({ enabled: true, accounts: UMA_CONTA, loading: false, error: null });
    global.fetch = vi.fn(() => Promise.resolve(resposta({ data: [] }))) as unknown as typeof fetch;

    render(<LeadBlingSection leadId="lead-1" blingContactIds={{}} onChanged={vi.fn()} />);
    expect(screen.queryByText("Conta Bling")).toBeNull();
  });

  it("renderiza o seletor com duas contas conectadas, rotulado com `label`", () => {
    mockUseBlingStatus.mockReturnValue({ enabled: true, accounts: DUAS_CONTAS, loading: false, error: null });
    global.fetch = vi.fn(() => Promise.resolve(resposta({ data: [] }))) as unknown as typeof fetch;

    render(<LeadBlingSection leadId="lead-1" blingContactIds={{}} onChanged={vi.fn()} />);
    expect(screen.queryByText("Conta Bling")).not.toBeNull();
    // O `Select` e do Radix: `SelectValue` renderiza APENAS o label da opcao
    // selecionada, e o `SelectContent` so monta quando o dropdown abre. Com a
    // conta preferida semeada, o unico label no documento e o dela.
    expect(screen.queryByText("Canastra CNPJ 2")).not.toBeNull();
    expect(screen.queryByText(CONTA_PREFERIDA)).toBeNull();
  });

  it("comeca na conta PREFERIDA — o vendedor cai direto no CNPJ que mais emite", async () => {
    mockUseBlingStatus.mockReturnValue({ enabled: true, accounts: DUAS_CONTAS, loading: false, error: null });
    global.fetch = vi.fn((url: string) =>
      String(url).includes(`account=${CONTA_PREFERIDA}`)
        ? Promise.resolve(resposta({ data: [{ id: 99, nome: "Cliente Cafe Rural" }] }))
        : Promise.resolve(resposta({ data: [] })),
    ) as unknown as typeof fetch;

    render(<LeadBlingSection leadId="lead-1" blingContactIds={{ [CONTA_PREFERIDA]: 99 }} onChanged={vi.fn()} />);
    expect(await screen.findByText("VINCULADO")).not.toBeNull();
    expect(await screen.findByText("Cliente Cafe Rural")).not.toBeNull();
  });

  // Com `UMA_CONTA` a preferida NAO esta no ar, entao a querystring tem que sair
  // com a default: e o efeito de reconciliacao corrigindo a semente sincrona
  // antes de qualquer chamada. Sem ele, a busca iria para uma conta inexistente
  // e voltaria vazia — sem seletor para o vendedor escapar (`precisaSeletor`
  // exige DUAS contas disponiveis).
  it("busca de vinculo manda a conta na querystring, ja reconciliada", async () => {
    mockUseBlingStatus.mockReturnValue({ enabled: true, accounts: UMA_CONTA, loading: false, error: null });
    const fetchSpy = vi.fn(() => Promise.resolve(resposta({ data: [] }))) as unknown as typeof fetch;
    global.fetch = fetchSpy;

    render(<LeadBlingSection leadId="lead-1" blingContactIds={{}} onChanged={vi.fn()} />);
    const campo = screen.getByPlaceholderText("Buscar por nome, fantasia ou CNPJ/CPF…");
    fireEvent.change(campo, { target: { value: "acme" } });

    await vi.waitFor(() => {
      const chamadas = (fetchSpy as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const chamouComConta = chamadas.some((c: unknown[]) =>
        String(c[0]).includes(`account=${CONTA_PADRAO}`),
      );
      expect(chamouComConta).toBe(true);
    });

    const chamouComPreferida = (
      fetchSpy as unknown as ReturnType<typeof vi.fn>
    ).mock.calls.some((c: unknown[]) => String(c[0]).includes(`account=${CONTA_PREFERIDA}`));
    expect(chamouComPreferida).toBe(false);
  });
});

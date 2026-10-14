/**
 * @vitest-environment jsdom
 *
 * Sem `@testing-library/jest-dom` (não está nas dependências): asserções com a API crua do
 * DOM/`screen`, mesmo padrão de lead-timeline.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Lead } from "@/lib/types";

// Filhos com fetch/Supabase próprios não interessam aqui.
vi.mock("./lead-broadcast-history", () => ({ LeadBroadcastHistory: () => null }));
vi.mock("./lead-bling-section", () => ({ LeadBlingSection: () => null }));
vi.mock("./lead-funis-tab", () => ({ LeadFunisTab: () => null }));
vi.mock("./lead-timeline", () => ({ LeadTimeline: () => null }));
vi.mock("@/components/leads/lead-origin-block", () => ({ LeadOriginBlock: () => null }));
vi.mock("@/components/sales/sale-create-modal", () => ({ SaleCreateModal: () => null }));
vi.mock("@/hooks/use-current-user", () => ({ useCurrentUserEmail: () => "teste@x.com" }));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    from: () => ({ select: () => ({ eq: () => Promise.resolve({ data: [] }) }) }),
  }),
}));

import { LeadDetailModal } from "./lead-detail-modal";

const LEAD = {
  id: "lead-1",
  name: "Lead Teste",
  phone: "5534999999999",
  email: "",
  instagram: "",
  company: "",
  // O modal não tem input de `company`; o campo "Empresa" editável é o bloco B2B.
  nome_fantasia: "teste",
  created_at: "2026-10-01T12:00:00Z",
  last_msg_at: null,
  first_response_at: null,
} as unknown as Lead;

function renderModal(
  onSave: (id: string, data: Partial<Lead>) => Promise<unknown> = vi.fn(() => Promise.resolve()),
  lead: Lead = LEAD,
) {
  render(
    <LeadDetailModal
      lead={lead}
      tags={[]}
      pipelines={[]}
      leadTagIds={[]}
      onClose={() => {}}
      onSave={onSave}
      onTagsChange={() => Promise.resolve()}
    />,
  );
  return onSave;
}

const header = () => screen.getByTestId("lead-detail-header");
const botaoSalvar = () => screen.queryByRole("button", { name: /Salvar altera/ });

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: async () => [] } as Response),
  ) as unknown as typeof fetch;
});
afterEach(cleanup);

describe("LeadDetailModal — Salvar alterações no cabeçalho", () => {
  it("sem edição, não mostra o botão", () => {
    renderModal();
    expect(botaoSalvar()).toBeNull();
  });

  it("ao editar um campo, o botão aparece dentro do cabeçalho, com acento", () => {
    renderModal();
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    const botao = botaoSalvar();
    expect(botao).not.toBeNull();
    expect(botao!.textContent).toBe("Salvar alterações");
    expect(header().contains(botao)).toBe(true);
    // Não existe uma segunda cópia no rodapé da aba.
    expect(screen.getAllByRole("button", { name: /Salvar altera/ })).toHaveLength(1);
  });

  it("trocando de aba depois de editar, o botão continua visível", () => {
    renderModal();
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    fireEvent.click(screen.getByRole("button", { name: "Metricas" }));
    expect(botaoSalvar()).not.toBeNull();
  });

  it("clicar salva só o campo alterado, mostra Salvando... e some ao terminar", async () => {
    let terminar!: () => void;
    const onSave = vi.fn(() => new Promise<void>((r) => { terminar = r; }));
    renderModal(onSave);
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    fireEvent.click(botaoSalvar()!);

    expect(onSave).toHaveBeenCalledWith("lead-1", { nome_fantasia: "teste agente" });
    const salvando = screen.getByRole("button", { name: "Salvando..." }) as HTMLButtonElement;
    expect(salvando.disabled).toBe(true);

    await act(async () => { terminar(); });
    expect(botaoSalvar()).toBeNull();
    expect(screen.queryByRole("button", { name: "Salvando..." })).toBeNull();
  });
});

describe("LeadDetailModal — endereço estruturado", () => {
  const campo = (rotulo: string) => screen.getByLabelText(rotulo) as HTMLInputElement;
  const bloco = () => screen.getByTestId("lead-address-block");

  it("mostra CEP, Rua, Número, Complemento, Bairro, Cidade e UF no lugar do campo único", () => {
    renderModal(undefined, { ...LEAD, endereco: "Rua Velha, 1", logradouro: "Rua Nova" } as Lead);
    for (const rotulo of ["CEP", "Rua", "Número", "Complemento", "Bairro", "Cidade", "UF"]) {
      expect(bloco().contains(campo(rotulo))).toBe(true);
    }
    expect(campo("Rua").value).toBe("Rua Nova");
    expect(screen.queryByDisplayValue("Rua Velha, 1")).toBeNull();
    expect(screen.queryByText(/Endereço antigo:/)).toBeNull();
  });

  it("só com o texto legado, mostra 'Endereço antigo:' abaixo dos campos", () => {
    renderModal(undefined, { ...LEAD, endereco: "Rua Velha, 1 - Frutal" } as Lead);
    expect(bloco().textContent).toContain("Endereço antigo: Rua Velha, 1 - Frutal");
  });

  it("CEP com 8 dígitos busca no ViaCEP e preenche só os campos vazios", async () => {
    global.fetch = vi.fn(async (url: RequestInfo | URL) =>
      String(url).startsWith("https://viacep.com.br/ws/38200000/")
        ? ({
            ok: true,
            status: 200,
            json: async () => ({ logradouro: "Avenida Brasil", bairro: "Centro", localidade: "Frutal", uf: "MG" }),
          } as Response)
        : ({ ok: true, status: 200, json: async () => [] } as Response),
    ) as unknown as typeof fetch;
    renderModal(undefined, { ...LEAD, logradouro: "Rua Digitada" } as Lead);

    fireEvent.change(campo("CEP"), { target: { value: "38200-000" } });

    await waitFor(() => expect(campo("Cidade").value).toBe("Frutal"));
    expect(campo("UF").value).toBe("MG");
    expect(campo("Bairro").value).toBe("Centro");
    expect(campo("Rua").value).toBe("Rua Digitada");
  });

  it("salvar envia os campos de endereço alterados", async () => {
    const onSave = vi.fn(() => Promise.resolve({}));
    renderModal(onSave);
    fireEvent.change(campo("Número"), { target: { value: "123" } });
    fireEvent.change(campo("Complemento"), { target: { value: "Sala 2" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(onSave).toHaveBeenCalledWith("lead-1", { numero: "123", complemento: "Sala 2" });
  });

  it("depois de salvar mostra o resultado do Bling", async () => {
    renderModal(() => Promise.resolve({ id: "lead-1", bling_endereco: { status: "updated", contas: [] } }));
    fireEvent.change(campo("Número"), { target: { value: "123" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(screen.getByText("Endereço atualizado no Bling")).toBeTruthy();
  });

  it("falha no Bling aparece com a mensagem", async () => {
    renderModal(() =>
      Promise.resolve({ bling_endereco: { status: "error", message: "Bling indisponível — tente salvar de novo" } }),
    );
    fireEvent.change(campo("Número"), { target: { value: "123" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(screen.getByText("Falha ao atualizar no Bling: Bling indisponível — tente salvar de novo")).toBeTruthy();
  });

  it("depois de salvar, a resposta vira a base: 2º salvamento não reenvia o endereço", async () => {
    const onSave = vi
      .fn<(id: string, data: Partial<Lead>) => Promise<unknown>>()
      .mockResolvedValueOnce({
        ...LEAD,
        cep: "38200000",
        numero: "123",
        endereco: "123 - 38200-000",
        bling_endereco: { status: "incomplete" },
      })
      .mockResolvedValueOnce({ ...LEAD, nome_fantasia: "teste agente" });
    renderModal(onSave);

    fireEvent.change(campo("CEP"), { target: { value: "38200-000" } });
    fireEvent.change(campo("Número"), { target: { value: "123" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(onSave).toHaveBeenLastCalledWith("lead-1", { cep: "38200-000", numero: "123" });
    // O CEP passa a aparecer como o banco gravou.
    expect(campo("CEP").value).toBe("38200000");

    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(onSave).toHaveBeenLastCalledWith("lead-1", { nome_fantasia: "teste agente" });
  });

  it("resposta de erro (sem id) não vira base: o próximo salvamento reenvia", async () => {
    const onSave = vi
      .fn<(id: string, data: Partial<Lead>) => Promise<unknown>>()
      .mockResolvedValue({ error: "boom" });
    renderModal(onSave);
    fireEvent.change(campo("Número"), { target: { value: "123" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(onSave).toHaveBeenLastCalledWith("lead-1", { numero: "123", nome_fantasia: "teste agente" });
  });

  it("salvar campo que não é de endereço não mostra mensagem do Bling", async () => {
    renderModal(() => Promise.resolve({ id: "lead-1" }));
    fireEvent.change(screen.getByDisplayValue("teste"), { target: { value: "teste agente" } });
    await act(async () => { fireEvent.click(botaoSalvar()!); });
    expect(screen.queryByText(/Bling/)).toBeNull();
  });
});

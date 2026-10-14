/**
 * @vitest-environment jsdom
 *
 * Sem `@testing-library/jest-dom` (não está nas dependências): asserções com a API crua do
 * DOM/`screen`, mesmo padrão de lead-timeline.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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

function renderModal(onSave = vi.fn(() => Promise.resolve())) {
  render(
    <LeadDetailModal
      lead={LEAD}
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

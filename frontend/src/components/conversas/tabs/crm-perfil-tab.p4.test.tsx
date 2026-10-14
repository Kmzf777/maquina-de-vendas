/**
 * @vitest-environment jsdom
 *
 * Revisão do P4: o CNPJ do Perfil e o do cabeçalho gravam do mesmo jeito —
 * só os dígitos (é como o Bling e o P1 casam o documento) e `null` quando o
 * campo é apagado.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/hooks/use-stages-by-pipeline", () => ({
  useStagesByPipeline: () => ({ stagesByPipeline: {} }),
}));
vi.mock("@/components/conversas/cadence-timeline", () => ({ CadenceTimeline: () => null }));
vi.mock("@/components/leads/lead-origin-block", () => ({ LeadOriginBlock: () => null }));

import { CrmPerfilTab } from "./crm-perfil-tab";
import type { Lead } from "@/lib/types";

afterEach(cleanup);

function abrir(cnpj: string | null, extra: Record<string, unknown> = {}) {
  const onSaveField = vi.fn(async () => {});
  render(
    <CrmPerfilTab
      lead={{ id: "lead-1", name: "Iago", phone: "5531999998888", cnpj, ...extra } as unknown as Lead}
      onSaveField={onSaveField}
      deals={[]}
      tags={[]}
      leadTags={[]}
      onTagToggle={vi.fn()}
      onCreateDeal={vi.fn()}
      onDealUpdate={vi.fn(async () => {})}
      sales={[]}
      onCreateSale={vi.fn()}
      onEditSale={vi.fn()}
      onDeleteSale={vi.fn()}
      quotes={[]}
      onCreateQuote={vi.fn()}
    />,
  );
  return { onSaveField };
}

function editar(atual: string, novo: string) {
  fireEvent.click(screen.getByText(atual));
  const campo = screen.getByDisplayValue(atual);
  fireEvent.change(campo, { target: { value: novo } });
  fireEvent.keyDown(campo, { key: "Enter" });
}

describe("CrmPerfilTab — CNPJ", () => {
  it("mostra formatado e grava só os dígitos", () => {
    const { onSaveField } = abrir("12345678000190");
    editar("12.345.678/0001-90", "11.222.333/0001-81");
    expect(onSaveField).toHaveBeenCalledWith("cnpj", "11222333000181");
  });

  it("campo apagado grava null, não string vazia", () => {
    const { onSaveField } = abrir("12345678000190");
    editar("12.345.678/0001-90", "");
    expect(onSaveField).toHaveBeenCalledWith("cnpj", null);
  });
});

describe("CrmPerfilTab — endereço estruturado", () => {
  it("troca o campo único por CEP, Rua, Número, Complemento, Bairro, Cidade e UF", () => {
    abrir(null);
    for (const rotulo of ["CEP", "Rua", "Número", "Complemento", "Bairro", "Cidade", "UF"]) {
      expect(screen.getByText(rotulo)).toBeTruthy();
    }
    expect(screen.queryByText("Endereco")).toBeNull();
  });

  it("cada campo grava na sua coluna", () => {
    const { onSaveField } = abrir(null, { logradouro: "Rua A", municipio: "Frutal" });
    editar("Rua A", "Rua B");
    expect(onSaveField).toHaveBeenCalledWith("logradouro", "Rua B");
    editar("Frutal", "Uberlândia");
    expect(onSaveField).toHaveBeenCalledWith("municipio", "Uberlândia");
  });

  it("só com o texto legado, mostra 'Endereço antigo:'", () => {
    abrir(null, { endereco: "Rua Velha, 1" });
    expect(screen.getByText("Endereço antigo: Rua Velha, 1")).toBeTruthy();
  });

  it("com campo estruturado, o texto legado não aparece", () => {
    abrir(null, { endereco: "Rua Velha, 1", logradouro: "Rua Nova" });
    expect(screen.queryByText(/Endereço antigo/)).toBeNull();
  });
});

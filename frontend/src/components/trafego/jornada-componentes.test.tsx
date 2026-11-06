// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
import { AtribuicaoSelect } from "@/components/trafego/atribuicao-select";
import { JornadasMulticanal } from "@/components/trafego/jornadas-multicanal";
import { SemRastreioDetalhe } from "@/components/trafego/sem-rastreio-detalhe";
import { PassouPor } from "@/components/trafego/passou-por";
import { CampaignLeadsTable, type CampaignLead } from "@/components/trafego/campaign-leads-table";

afterEach(cleanup);

describe("AtribuicaoSelect", () => {
  it("começa na última origem e troca para a primeira", () => {
    const onChange = vi.fn();
    render(<AtribuicaoSelect value="ultima" onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Última origem" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Primeira origem" }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Primeira origem" }));
    expect(onChange).toHaveBeenCalledWith("primeira");
  });
});

describe("JornadasMulticanal", () => {
  it("mostra leads, vendas e os caminhos", () => {
    render(<JornadasMulticanal jornadas={{
      leads: 5, clientes: 4, pedidos: 4, receita: 1200, total_leads: 40,
      caminhos: [{ caminho: "Meta Ads → Google Ads", leads: 4, clientes: 4, pedidos: 4, receita: 1200 }],
    }} />);
    expect(screen.getByText("Jornadas com mais de um canal")).toBeTruthy();
    expect(screen.getByText(/5 de 40 leads · 4 vendas/)).toBeTruthy();
    expect(screen.getByText("Meta Ads → Google Ads")).toBeTruthy();
    expect(screen.getByText(/4 leads · 4 vendas · R\$\s?1\.200/)).toBeTruthy();
  });
  it("sem caminho avisa", () => {
    render(<JornadasMulticanal jornadas={{ leads: 0, clientes: 0, pedidos: 0, receita: 0, total_leads: 3, caminhos: [] }} />);
    expect(screen.getByText(/Nenhum lead do período passou por mais de um canal/)).toBeTruthy();
  });
  it("backend sem F5: não renderiza", () => {
    const { container } = render(<JornadasMulticanal jornadas={undefined} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("SemRastreioDetalhe", () => {
  it("lista os motivos e abre os leads", () => {
    const onAbrir = vi.fn();
    render(<SemRastreioDetalhe onAbrir={onAbrir} resumo={{ leads: 3, motivos: [
      { motivo: "Nunca mandou mensagem", leads: 2 }, { motivo: "Sem origem de cadastro", leads: 1 }] }} />);
    expect(screen.getByText("Sem rastreio: 3 leads")).toBeTruthy();
    expect(screen.getByText("Nunca mandou mensagem")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ver leads" }));
    expect(onAbrir).toHaveBeenCalled();
  });
  it("zero sobra: some", () => {
    const { container } = render(<SemRastreioDetalhe resumo={{ leads: 0, motivos: [] }} />);
    expect(container.innerHTML).toBe("");
  });
});

const JORNADA = {
  primeira_origem: "Meta Ads", primeira_em: "2026-10-01T12:00:00+00:00", ultima_origem: "Google Ads",
  ultima_em: "2026-10-09T12:00:00+00:00", origens: ["Meta Ads", "Google Ads"],
  toques: [{ canal: "Meta Ads", em: "2026-10-01T12:00:00+00:00" }, { canal: "Google Ads", em: "2026-10-09T12:00:00+00:00" }],
  n_toques: 2, multicanal: true, estimado: false,
};

describe("Passou por", () => {
  it("célula com as datas no title", () => {
    render(<PassouPor jornada={JORNADA} />);
    const el = screen.getByText("Meta Ads → Google Ads");
    expect(el.getAttribute("title")).toBe("Meta Ads em 01/10 · Google Ads em 09/10");
  });

  const base: CampaignLead = {
    lead_id: "L1", name: "Tati", phone: "1", created_at: null, utm_source: null, utm_medium: null,
    utm_campaign: null, traffic_type: null, conversou: true, stage: null, comprou: false, valor: 0, sold_at: null,
  };

  it("a tabela de leads tem a coluna Passou por", () => {
    render(<CampaignLeadsTable leads={[{ ...base, jornada: JORNADA }]} />);
    const cab = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(cab).toContain("Passou por");
    expect(cab).not.toContain("Motivo");
    expect(screen.getByText("Meta Ads → Google Ads")).toBeTruthy();
  });

  it("no Sem rastreio aparece a coluna Motivo", () => {
    render(<CampaignLeadsTable leads={[{ ...base, motivo_sem_rastreio: "Nunca mandou mensagem" }]} />);
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toContain("Motivo");
    expect(screen.getByText("Nunca mandou mensagem")).toBeTruthy();
  });
});

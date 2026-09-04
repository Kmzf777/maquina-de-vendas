/**
 * @vitest-environment jsdom
 *
 * Primeiro teste de componente do repositório. O default do vitest.config.ts continua
 * `node`; este arquivo opta por jsdom no docblock acima.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { EsteirasTab } from "./esteiras-tab";

const RESPOSTA = {
  esteiras: [
    { key: "novo_sem_resposta", nome: "Esteira — Novo sem resposta nossa", descricao: "d",
      ativa: false, canal_id: null, funil_id: null, etapa_id: null, etapa_key: null,
      toques: [{ ordem: 1, dias: 3, template_name: "esteira_novo_sem_resposta_v1" }],
      acao_final: "alert_seller" },
    { key: "reposicao", nome: "Esteira — Reposicao", descricao: "d",
      ativa: true, canal_id: "ch", funil_id: "p", etapa_id: "s", etapa_key: null,
      toques: [{ ordem: 1, dias: 15, template_name: "esteira_reposicao_v1" }],
      acao_final: "mark_deal_lost" },
  ],
};

beforeEach(() => {
  global.fetch = vi.fn(async (url: string) => {
    if (String(url).includes("/api/automation/esteiras")) {
      return { ok: true, json: async () => RESPOSTA } as Response;
    }
    return { ok: true, json: async () => ({ templates: [] }) } as Response;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("EsteirasTab", () => {
  // Consulta por HEADING e não por texto solto: o nome do template configurado aparece
  // no select ("esteira_reposicao_v1"), então /Reposicao/i casa duas vezes na tela. O que
  // o teste quer garantir é que existe um CARTÃO por esteira — o título é o que prova isso.
  it("lista as esteiras vindas da API", async () => {
    render(<EsteirasTab />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Novo sem resposta/i })).toBeTruthy()
    );
    expect(screen.getByRole("heading", { name: /Reposicao/i })).toBeTruthy();
  });

  it("mostra o estado ligado/desligado de cada esteira", async () => {
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getAllByRole("switch").length).toBe(2));
    const switches = screen.getAllByRole("switch");
    expect(switches[0].getAttribute("aria-checked")).toBe("false");
    expect(switches[1].getAttribute("aria-checked")).toBe("true");
  });

  it("mostra a acao final como texto, nao como campo editavel", async () => {
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getByText(/move para Perdido/i)).toBeTruthy());
    expect(screen.getByText(/avisa o vendedor/i)).toBeTruthy();
  });

  // ── Regras que vieram da execução do backend ────────────────────────────────

  it("não deixa ligar esteira sem etapa configurada, e diz por quê", async () => {
    // Sem stage_id nem stage_key a RPC trata etapa como 'qualquer etapa': a esteira
    // ficaria elegível a todo card aberto de todo funil. O PUT recusa com 400 — a tela
    // não pode oferecer o clique e só depois falhar.
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getAllByRole("switch").length).toBe(2));
    const [semEtapa, comEtapa] = screen.getAllByRole("switch");
    expect((semEtapa as HTMLButtonElement).disabled).toBe(true);
    expect((comEtapa as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/Escolha o funil e a etapa/i)).toBeTruthy();
  });

  it("pede confirmação antes de ligar, mostrando quantos cards ficam elegíveis", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (url: string) => {
        if (String(url).includes("/api/automation/esteiras/preview")) {
          return { ok: true, json: async () => ({ elegiveis: 137 }) } as Response;
        }
        if (String(url).includes("/api/automation/esteiras")) {
          return { ok: true, json: async () => RESPOSTA } as Response;
        }
        return { ok: true, json: async () => ({ templates: [] }) } as Response;
      }
    );
    // A esteira ligada é a de reposição; desligar não pede confirmação, ligar pede.
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getAllByRole("switch").length).toBe(2));
    fireEvent.click(screen.getAllByRole("switch")[1]); // desliga (sem confirmação)
    await waitFor(() =>
      expect(screen.getAllByRole("switch")[1].getAttribute("aria-checked")).toBe("false")
    );
    fireEvent.click(screen.getAllByRole("switch")[1]); // liga → confirmação
    await waitFor(() => expect(screen.getByText(/137/)).toBeTruthy());
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("só oferece template aprovado no select", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (url: string) => {
        if (String(url).includes("/api/automation/esteiras")) {
          return { ok: true, json: async () => RESPOSTA } as Response;
        }
        if (String(url).includes("/api/templates")) {
          return {
            ok: true,
            json: async () => [
              { id: "1", name: "aprovado_v1", language: "pt_BR", status: "approved" },
              { id: "2", name: "em_analise_v1", language: "pt_BR", status: "pending" },
              { id: "3", name: "recusado_v1", language: "pt_BR", status: "rejected" },
            ],
          } as Response;
        }
        return { ok: true, json: async () => [] } as Response;
      }
    );
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getAllByRole("combobox").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getAllByText("aprovado_v1").length).toBe(2));
    expect(screen.queryByText("em_analise_v1")).toBeNull();
    expect(screen.queryByText("recusado_v1")).toBeNull();
  });
});

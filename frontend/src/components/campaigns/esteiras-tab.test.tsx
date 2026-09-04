/**
 * @vitest-environment jsdom
 *
 * Primeiro teste de componente do repositório. O default do vitest.config.ts continua
 * `node`; este arquivo opta por jsdom no docblock acima.
 *
 * Contrato exercitado aqui: `backend/app/campaigns/esteiras_router.py`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { EsteirasTab } from "./esteiras-tab";

const NOVO = {
  key: "novo_sem_resposta",
  campaign_id: "camp-novo",
  nome: "Esteira — Novo sem resposta nossa",
  descricao: "d",
  ativa: false,
  canal_id: null,
  funil_id: null,
  etapa_id: null,
  etapa_key: null,
  relogio: "silence_days",
  gatilho: { silence_days: 3, stage_days: 0, last_speaker: "lead", stage_key: null },
  toques: [{ ordem: 1, dias: 3, template_name: "esteira_novo_sem_resposta_v1" }],
  acao_final: "alert_seller",
  stage_id_perdido: null,
};

const REPOSICAO = {
  key: "reposicao",
  campaign_id: "camp-repo",
  nome: "Esteira — Reposicao",
  descricao: "d",
  ativa: true,
  canal_id: "ch",
  funil_id: "p",
  etapa_id: "s",
  etapa_key: null,
  relogio: "silence_days",
  gatilho: { silence_days: 15, stage_days: 0, last_speaker: "qualquer", stage_key: null },
  toques: [{ ordem: 1, dias: 15, template_name: "esteira_reposicao_v1" }],
  acao_final: "mark_deal_lost",
  stage_id_perdido: "stage-perdido",
};

/**
 * A esteira de proposta é o caso que expõe a guarda do canal: ela nasce do seed com
 * `etapa_key = 'proposta_enviada'`, então a checagem de etapa já a considera pronta —
 * mas sem canal ela envia pelo número da conversa mais recente (pode ser o da Valéria)
 * e passa por cima da flag "Finalizar Conversa" marcada em /conversas.
 */
const PROPOSTA = {
  key: "proposta",
  campaign_id: "camp-prop",
  nome: "Esteira Proposta",
  descricao: "d",
  ativa: false,
  canal_id: null,
  funil_id: null,
  etapa_id: null,
  etapa_key: "proposta_enviada",
  relogio: "stage_days",
  gatilho: { silence_days: 0, stage_days: 3, last_speaker: "nos", stage_key: "proposta_enviada" },
  toques: [{ ordem: 1, dias: 3, template_name: "esteira_proposta_d3_v1" }],
  acao_final: "alert_seller",
  stage_id_perdido: null,
};

const RESPOSTA = { esteiras: [NOVO, REPOSICAO] };

type Corpo = Record<string, unknown> | unknown[];
const resposta = (corpo: Corpo, status = 200) =>
  ({ ok: status < 400, status, json: async () => corpo }) as Response;

/**
 * Monta o `fetch` global. `rotas` casa por substring da URL; `aoGravar` responde ao PUT.
 * Sem entrada específica, a rota devolve lista vazia — o formato que as APIs de canais,
 * funis e templates usam.
 */
function mockarFetch(opts: {
  esteiras?: Corpo;
  rotas?: Record<string, Corpo>;
  aoGravar?: () => Response;
} = {}) {
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (init?.method === "PUT") return opts.aoGravar?.() ?? resposta({ ok: true, aviso: null });
    for (const [trecho, corpo] of Object.entries(opts.rotas ?? {})) {
      if (u.includes(trecho)) return resposta(corpo);
    }
    if (u.includes("/api/automation/esteiras")) return resposta(opts.esteiras ?? RESPOSTA);
    return resposta([]);
  }) as unknown as typeof fetch;
}

beforeEach(() => mockarFetch());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const switches = () => screen.getAllByRole("switch");
const aparecemOsCartoes = () => waitFor(() => expect(switches().length).toBe(2));

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
    await aparecemOsCartoes();
    expect(switches()[0].getAttribute("aria-checked")).toBe("false");
    expect(switches()[1].getAttribute("aria-checked")).toBe("true");
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
    await aparecemOsCartoes();
    const [semEtapa, comEtapa] = switches();
    expect((semEtapa as HTMLButtonElement).disabled).toBe(true);
    expect((comEtapa as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/Escolha o funil e a etapa/i)).toBeTruthy();
  });

  it("não deixa ligar esteira sem canal, e diz por quê", async () => {
    // A etapa da proposta vem presa por `key`, então a guarda de etapa passa sozinha.
    // Sem canal, `_conversation_followup_disabled(lead, None)` devolve False (a flag
    // "Finalizar Conversa" do vendedor deixa de valer) e o envio cai em
    // `get_channel_for_lead` — a conversa ativa mais recente, que pode ser a da Valéria.
    mockarFetch({ esteiras: { esteiras: [PROPOSTA, REPOSICAO] } });
    render(<EsteirasTab />);
    await aparecemOsCartoes();
    const semCanal = screen.getByRole("switch", { name: /Ligar Esteira Proposta/i });
    expect((semCanal as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Escolha o canal/i)).toBeTruthy();
    // E não é a mensagem da etapa: essa esteira TEM etapa.
    expect(screen.queryByText(/Escolha o funil e a etapa/i)).toBeNull();
  });

  it("limpar o canal de uma esteira ligada trava o Salvar", async () => {
    // Salvar manda `ativa` junto; com a esteira ligada e sem canal o PUT devolve 400.
    mockarFetch({
      rotas: { "/api/channels": [{ id: "ch", name: "Número do João", is_active: true }] },
    });
    render(<EsteirasTab />);
    await aparecemOsCartoes();
    await waitFor(() => expect(screen.getAllByText("Número do João").length).toBe(2));

    const salvar = () => screen.getAllByRole("button", { name: "Salvar" })[1] as HTMLButtonElement;
    fireEvent.change(screen.getAllByLabelText("Canal")[1], { target: { value: "" } });

    await waitFor(() => expect(salvar().disabled).toBe(true));
    expect(screen.getByText(/escolha o canal para poder salvar/i)).toBeTruthy();
    const chamadas = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(chamadas.some((c) => (c[1] as RequestInit | undefined)?.method === "PUT")).toBe(false);
  });

  it("o primeiro toque não aceita zero dias; as esperas seguintes aceitam", async () => {
    // O toque 1 grava no GATILHO. Com ele em 0 (e a proposta já nasce com o outro
    // relógio em 0), a RPC para de aplicar filtro temporal e todo card da etapa entra
    // no próximo tick — inclusive a proposta enviada há cinco minutos.
    mockarFetch({
      esteiras: {
        esteiras: [
          {
            ...REPOSICAO,
            toques: [
              { ordem: 1, dias: 15, template_name: "esteira_reposicao_v1" },
              { ordem: 2, dias: 7, template_name: "esteira_reposicao_v1" },
            ],
          },
        ],
      },
    });
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getByLabelText("Dias do toque 2")).toBeTruthy());
    expect(screen.getByLabelText("Dias do toque 1").getAttribute("min")).toBe("1");
    expect(screen.getByLabelText("Dias do toque 2").getAttribute("min")).toBe("0");
  });

  it("pede confirmação antes de ligar, mostrando quantos cards ficam elegíveis", async () => {
    mockarFetch({ rotas: { "/api/automation/esteiras/preview": { elegiveis: 137 } } });
    // A esteira ligada é a de reposição; desligar não pede confirmação, ligar pede.
    render(<EsteirasTab />);
    await aparecemOsCartoes();
    fireEvent.click(switches()[1]); // desliga (sem confirmação)
    await waitFor(() => expect(switches()[1].getAttribute("aria-checked")).toBe("false"));
    fireEvent.click(switches()[1]); // liga → confirmação
    await waitFor(() => expect(screen.getByText(/137/)).toBeTruthy());
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("só oferece template aprovado no select", async () => {
    mockarFetch({
      rotas: {
        "/api/templates": [
          { id: "1", name: "aprovado_v1", language: "pt_BR", status: "approved" },
          { id: "2", name: "em_analise_v1", language: "pt_BR", status: "pending" },
          { id: "3", name: "recusado_v1", language: "pt_BR", status: "rejected" },
        ],
      },
    });
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getAllByText("aprovado_v1").length).toBe(2));
    expect(screen.queryByText("em_analise_v1")).toBeNull();
    expect(screen.queryByText("recusado_v1")).toBeNull();
  });

  // ── Contrato final do esteiras_router ───────────────────────────────────────

  it("usa o `relogio` do backend para rotular o prazo do primeiro toque", async () => {
    // O mesmo "3" significa coisas diferentes: 3 dias parado na etapa Proposta Enviada
    // ou 3 dias sem nenhuma conversa. Só o backend sabe qual, porque deriva do seed.
    mockarFetch({
      esteiras: {
        esteiras: [
          NOVO,
          { ...REPOSICAO, key: "proposta", nome: "Esteira — Proposta", relogio: "stage_days" },
        ],
      },
    });
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getByText(/dias parado nesta etapa/i)).toBeTruthy());
    expect(screen.getByText(/dias sem nenhuma conversa/i)).toBeTruthy();
  });

  it("trata `aviso` como sucesso com ressalva, não como erro", async () => {
    const aviso =
      "O funil escolhido nao tem etapa de Perdido. A esteira vai enviar os toques e " +
      "terminar SEM mover o card.";
    mockarFetch({ aoGravar: () => resposta({ ok: true, aviso, stage_id_perdido: null }) });
    render(<EsteirasTab />);
    await aparecemOsCartoes();
    fireEvent.click(switches()[1]); // desliga → grava
    await waitFor(() => expect(screen.getByText(/Salvo, com uma ressalva/i)).toBeTruthy());
    expect(screen.queryByText(/Não salvou/i)).toBeNull();
    // Gravou de verdade: o estado do interruptor acompanhou.
    expect(switches()[1].getAttribute("aria-checked")).toBe("false");
  });

  it("o aviso de funil sem etapa de Perdido reaparece na linha do tempo", async () => {
    mockarFetch({
      esteiras: { esteiras: [NOVO, { ...REPOSICAO, stage_id_perdido: null }] },
    });
    render(<EsteirasTab />);
    await waitFor(() => expect(screen.getByText(/não tem coluna de Perdido/i)).toBeTruthy());
    // Continua sendo "move para Perdido" no texto da ação — o que muda é a ressalva.
    expect(screen.getByText(/move para Perdido/i)).toBeTruthy();
  });

  it("no 409 diz que o seed não rodou e o que fazer, em vez de 'tente de novo'", async () => {
    const detail =
      "a esteira 'reposicao' ainda nao existe no banco — o seed roda no startup da API " +
      "e pode ter falhado (migration 20260904 aplicada?). Reinicie a API e tente de novo.";
    mockarFetch({ aoGravar: () => resposta({ detail }, 409) });
    render(<EsteirasTab />);
    await aparecemOsCartoes();
    fireEvent.click(switches()[1]);
    await waitFor(() => expect(screen.getByText(/Esteira indisponível/i)).toBeTruthy());
    expect(screen.getByText(/migration 20260904/i)).toBeTruthy();
    // Falhou: o interruptor não pode ter mudado de estado.
    expect(switches()[1].getAttribute("aria-checked")).toBe("true");
  });

  it("trocar o funil de uma esteira ligada limpa a etapa e trava o Salvar", async () => {
    // O backend valida que a etapa pertence ao funil e recusa com 400. Correto — mas a
    // tela não deve produzir esse estado: ela pede a etapa nova antes de deixar salvar.
    mockarFetch({
      rotas: {
        "/api/pipelines/p/stages": [{ id: "s", label: "Já chamado", pipeline_id: "p" }],
        "/api/pipelines": [
          { id: "p", name: "Funil do João" },
          { id: "p2", name: "Funil do Arthur" },
        ],
      },
    });
    render(<EsteirasTab />);
    await aparecemOsCartoes();
    await waitFor(() => expect(screen.getAllByText("Funil do Arthur").length).toBe(2));

    const salvar = () => screen.getAllByRole("button", { name: "Salvar" })[1] as HTMLButtonElement;

    // Suja o cartão por um caminho que NÃO mexe na etapa: aqui Salvar tem de ficar ativo.
    // Sem esta metade, o teste passaria só porque um cartão limpo já tem Salvar desligado.
    fireEvent.change(screen.getAllByLabelText("Dias do toque 1")[1], { target: { value: "20" } });
    await waitFor(() => expect(salvar().disabled).toBe(false));

    fireEvent.change(screen.getAllByLabelText("Funil")[1], { target: { value: "p2" } });

    await waitFor(() => expect(salvar().disabled).toBe(true));
    expect(screen.getByText(/escolha a etapa do novo funil/i)).toBeTruthy();
    // E não chegou a mandar PUT nenhum.
    const chamadas = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(chamadas.some((c) => (c[1] as RequestInit | undefined)?.method === "PUT")).toBe(false);
  });
});

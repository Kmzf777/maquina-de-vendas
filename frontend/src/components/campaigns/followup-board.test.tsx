/**
 * @vitest-environment jsdom
 *
 * O editor de cadências da aba Follow-up — DOIS motores num painel só, e o motor do
 * João navegado por FUNIL primeiro (spec 2026-09-21).
 *
 * A regra que estes testes existem para travar é a de 16/09/2026: uma validação de
 * ativação idêntica a esta já existiu no builder de campanhas, recusava CERTO no
 * backend e a TELA NÃO MOSTRAVA NADA. O operador clicava em "Ativar", nada acontecia,
 * e ninguém descobriu até produção. Por isso o teste da recusa não checa só que o PUT
 * foi feito: ele exige o NOME de cada template pendente visível na tela.
 *
 * A outra metade é a ValerIA: o payload dela está em produção e este painel é o único
 * consumidor. Um teste dedicado prova que ela continua sendo só leitura — o spec §6 é
 * explícito em que o objetivo de cada toque dela é prompt de LLM e fica no código.
 *
 * As asserções de TEXTO olham `textContent` do container (ou do `role="alert"`) em vez
 * de `getByText`: o alvo aqui é "isto está NA TELA", e `getByText` com regex casa
 * também os ancestrais, transformando uma asserção verdadeira em "found multiple
 * elements". Interação continua por papel/rótulo acessível, que é inequívoco.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { DefinitionStrip } from "./followup-board";

/** Tudo que está renderizado agora (cleanup() esvazia o body entre testes). */
function naTela(): string {
  return document.body.textContent ?? "";
}

// ── Fixtures ───────────────────────────────────────────────────────────────────
const TEMPLATES = [
  { id: "1", name: "joao_reposicao_atacado_t1", status: "approved", language: "pt_BR" },
  { id: "2", name: "joao_reposicao_atacado_t2", status: "approved", language: "pt_BR" },
  { id: "3", name: "joao_reposicao_privatelabel_t1", status: "APPROVED", language: "pt_BR" },
  // PENDING na Meta: não pode virar opção do <select>. Oferecer um template pendente é
  // oferecer a recusa da ativação como se fosse escolha válida.
  { id: "4", name: "joao_ainda_pendente", status: "PENDING", language: "pt_BR" },
];

function valeriaTouch(sequence: number, offsetHours: number, objective: string) {
  return {
    sequence,
    offset_hours: offsetHours,
    jitter_minutes: null,
    objective,
    objective_prompt: "...",
  };
}

const VALERIA = {
  touches: [
    valeriaTouch(1, 0, "reengajar"),
    valeriaTouch(2, 24, "reforco_valor"),
    valeriaTouch(3, 72, "prova_social"),
  ],
  outbound_nudge: valeriaTouch(1, 18, "reengajar"),
  min_gap_hours: 6,
  business_window: { start: "09:00", end: "16:00", days: "seg-sex", timezone: "America/Sao_Paulo" },
};

function toque(
  sequence: number,
  dias: number,
  template_name: string | null,
  aceita_adiamento = false,
  /** Para onde o card vai depois DESTE toque sair (spec 2026-09-26 §3.2), em RÓTULO.
   * `null` em 30 dos 32 toques do motor — hoje só o 1º de cada Reposição move. */
  move_para_rotulo: string | null = null,
) {
  return {
    sequence,
    dias,
    dias_codigo: dias,
    template_name,
    template_name_codigo: template_name,
    aceita_adiamento,
    move_para_rotulo,
  };
}

/** `joao.ajustes` como o backend o monta: o efetivo e o default de código de cada uma
 * das duas chaves globais. Os números aqui são os `AJUSTES_PADRAO` do motor em
 * 26/09/2026 — e todo teste que MEDE se a tela lê o payload troca os dois. */
function ajustesDoMotor(teto = 100, espera = 30) {
  return {
    teto_diario_disparos: teto,
    teto_diario_disparos_codigo: 100,
    adiamento_estoque_dias: espera,
    adiamento_estoque_dias_codigo: 30,
  };
}

function cadenciaDoFunil(
  codigo: string,
  rotulo: string,
  gatilhoStageRotulo: string,
  gatilhoDias: number,
  toques: ReturnType<typeof toque>[],
  extra: Partial<{
    repete_ultimo: boolean;
    pode_ligar: boolean;
    /** Os três SÓ-LEITURA de 23/09/2026. Os defaults aqui são os do backend
     * (`Cadencia`): silêncio 0, sem etapa de destino — e `dias_ate_mover: 1` MESMO
     * assim, que é exatamente a armadilha que os testes abaixo travam. */
    gatilho_silencio_dias: number;
    etapa_final_rotulo: string | null;
    dias_ate_mover: number;
    /** O QUARTO só-leitura (spec 2026-09-25 §4): quantos dias os toques restantes
     * deslizam quando o lead responde. O backend manda
     * `cadence_joao.ADIAMENTO_RESPOSTA.days` — hoje 3 — o MESMO valor em todas as
     * cadências dos cinco funis, e é isso que o default abaixo imita. Os testes que
     * mexem neste número provam que a tela lê o payload. */
    adiamento_resposta_dias: number;
    /** O QUINTO só-leitura (spec 2026-09-26 §2.1): as etapas em que a esteira segue
     * viva, em rótulo. O default imita o backend — `etapas_vivas=()` cai na etapa de
     * ENTRADA, e é ele que mantém as oito cadências de etapa única como sempre
     * foram. Só as de Reposição declaram duas. */
    etapas_vivas_rotulos: string[];
  }> = {},
) {
  const semTemplate = toques.filter((t) => !t.template_name).map((t) => t.sequence);
  return {
    codigo,
    rotulo,
    job_type: `joao_${codigo}`,
    gatilho_stage_key: "novo",
    gatilho_stage_rotulo: gatilhoStageRotulo,
    gatilho_dias: gatilhoDias,
    gatilho_dias_codigo: gatilhoDias,
    gatilho_silencio_dias: extra.gatilho_silencio_dias ?? 0,
    etapa_final_rotulo: extra.etapa_final_rotulo ?? null,
    dias_ate_mover: extra.dias_ate_mover ?? 1,
    adiamento_resposta_dias: extra.adiamento_resposta_dias ?? 3,
    etapas_vivas_rotulos: extra.etapas_vivas_rotulos ?? [gatilhoStageRotulo],
    ativa: false,
    repete_ultimo: extra.repete_ultimo ?? false,
    pode_ligar: extra.pode_ligar ?? semTemplate.length === 0,
    toques,
    toques_sem_template: semTemplate,
  };
}

/** Uma das três cadências de prospecção (Atacado / Private Label) como o backend as
 * declara desde 23/09/2026: TODO toque sem template (spec §2, decisão do dono) e
 * sempre com destino "Em atenção" 1 dia depois do último toque. */
function prospeccao(
  codigo: string,
  rotulo: string,
  gatilhoStageRotulo: string,
  gatilhoDias: number,
  silencioDias: number,
  diasDosToques: number[],
) {
  return cadenciaDoFunil(
    codigo,
    rotulo,
    gatilhoStageRotulo,
    gatilhoDias,
    diasDosToques.map((d, i) => toque(i + 1, d, null)),
    {
      gatilho_silencio_dias: silencioDias,
      etapa_final_rotulo: "Em atenção",
      dias_ate_mover: 1,
    },
  );
}

/** As TRÊS cadências que Atacado e Private Label passaram a ter (spec §1). */
function cadenciasDeProspeccao() {
  return [
    prospeccao("novo", "Novo", "Novo", 2, 2, [0, 2, 4]),
    prospeccao("em_conversa", "Em conversa", "Em conversa", 2, 2, [0, 2, 4, 9]),
    prospeccao("proposta", "Proposta Enviada", "Proposta Enviada", 1, 0, [0, 1, 4, 8]),
  ];
}

function funil(codigo: string, rotulo: string, cadencias: ReturnType<typeof cadenciaDoFunil>[]) {
  return { codigo, rotulo, pipeline_id: `pipe-${codigo}`, cadencias };
}

/** A cadência "Reposição" como o backend a declara DESDE 26/09/2026 (spec §1): entra
 * em "Cliente Ativo", o 1º toque MOVE o card para "Já chamado", a esteira segue viva
 * nas duas etapas e no fim o card vai para "Em atenção".
 *
 * Até 25/09 ela era a cadência que NÃO movia card (`etapa_final_rotulo: null`). Quem
 * procurar esse caso agora tem de olhar "Em atenção", que segue com destino nulo e
 * `dias_ate_mover: 1` — é ela que protege a tela de escrever "move o card para null". */
function cadenciaDeReposicao(prefixoDoTemplate: string) {
  return cadenciaDoFunil(
    "reposicao",
    "Reposição",
    "Cliente Ativo",
    45,
    [
      toque(1, 0, `${prefixoDoTemplate}_t1`, true, "Já chamado"),
      toque(2, 15, `${prefixoDoTemplate}_t2`, true),
    ],
    {
      etapa_final_rotulo: "Em atenção",
      dias_ate_mover: 1,
      etapas_vivas_rotulos: ["Cliente Ativo", "Já chamado"],
    },
  );
}

/** O payload REAL de `GET /api/cadence/definition` (backend/app/follow_up/api.py):
 * `joao.funis`, cinco funis, "Recuperação" com `cadencias: []` de propósito, e o bloco
 * `joao.ajustes` com os dois números do motor (spec 2026-09-26 §3.5).
 *
 * Desde 23/09/2026, Atacado e Private Label têm TRÊS cadências (Novo, Em conversa e a
 * nova Proposta Enviada), todas sem template em toque nenhum. */
function definicao() {
  return {
    ...VALERIA,
    valeria: VALERIA,
    joao: {
      ajustes: ajustesDoMotor(),
      funis: [
        funil("atacado", "João - Atacado", cadenciasDeProspeccao()),
        funil("private_label", "João - Private Label", cadenciasDeProspeccao()),
        funil("reposicao_atacado", "João - Reposição Atacado", [
          cadenciaDeReposicao("joao_reposicao_atacado"),
          cadenciaDoFunil(
            "em_atencao",
            "Em atenção",
            // Armadilha da spec §2: a cadência "Em atenção" vigia a etapa "novo", o
            // rótulo do gatilho tem que ser "Cliente Ativo", NUNCA "Em atenção".
            "Cliente Ativo",
            90,
            [toque(1, 3, null, true)],
            { repete_ultimo: true, pode_ligar: false },
          ),
        ]),
        funil("reposicao_private_label", "João - Reposição Private Label", [
          cadenciaDeReposicao("joao_reposicao_privatelabel"),
          cadenciaDoFunil(
            "em_atencao",
            "Em atenção",
            "Cliente Ativo",
            90,
            [toque(1, 3, null, true)],
            { repete_ultimo: true, pode_ligar: false },
          ),
        ]),
        // Espaço reservado (spec §1): funil de verdade, zero cadências.
        funil("recuperacao", "João - Recuperação", []),
      ],
    },
  };
}

/** A recusa REAL do FastAPI: HTTPException(400, detail={"problemas": [...]}). */
const RECUSA_EM_ATENCAO = {
  detail: {
    problemas: [
      {
        codigo: "toque_sem_template",
        mensagem:
          "O toque 1 não tem template configurado. Escolha um template aprovado para esse toque antes de ligar a cadência.",
        cadencia: "em_atencao",
        funil: "reposicao_atacado",
        sequence: 1,
      },
    ],
  },
};

const RECUSA_TEMPLATE_PENDENTE = {
  detail: {
    problemas: [
      {
        codigo: "template_nao_aprovado",
        mensagem:
          "O toque 2 usa o template `joao_reposicao_atacado_t2`, que está PENDING na Meta. Espere a aprovação da Meta e ligue a cadência depois.",
        cadencia: "reposicao",
        funil: "reposicao_atacado",
        sequence: 2,
      },
    ],
  },
};

// ── fetch mock ─────────────────────────────────────────────────────────────────
type Resposta = { ok?: boolean; status?: number; body: unknown };

let putRespostas: Resposta[];
let chamadas: { url: string; init?: RequestInit }[];

function resposta(r: Resposta) {
  return {
    ok: r.ok ?? true,
    status: r.status ?? 200,
    statusText: "",
    json: async () => r.body,
  } as unknown as Response;
}

function corposDoPut(): Record<string, unknown>[] {
  return chamadas
    .filter((c) => c.url === "/api/cadence/joao" && c.init?.method === "PUT")
    .map((c) => JSON.parse(String(c.init?.body)));
}

beforeEach(() => {
  putRespostas = [];
  chamadas = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      chamadas.push({ url, init });
      if (url.startsWith("/api/templates")) return resposta({ body: TEMPLATES });
      if (url === "/api/cadence/joao") {
        const next = putRespostas.shift();
        if (next) return resposta(next);
        // Sucesso padrão: o backend devolve a cadência já RESOLVIDA (do funil
        // "reposicao_atacado", cadência "reposicao" — o par mais usado nos testes).
        return resposta({ body: definicao().joao.funis[2].cadencias[0] });
      }
      throw new Error(`fetch inesperado: ${url}`);
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function abrirJoao(def: ReturnType<typeof definicao> = definicao()) {
  const utils = render(<DefinitionStrip definition={def as never} />);
  fireEvent.click(screen.getByRole("button", { name: "João" }));
  // O primeiro funil (Atacado) é selecionado por padrão — espera o <select> de
  // template dele responder antes de prosseguir.
  await screen.findByLabelText("Template do toque 1");
  return utils;
}

async function abrirFunil(rotulo: string) {
  fireEvent.click(screen.getByRole("button", { name: rotulo }));
  await waitFor(() => expect(screen.getByLabelText("Prazo do gatilho (dias)")).toBeTruthy());
}

async function abrirCadencia(rotulo: string) {
  fireEvent.click(screen.getByRole("button", { name: rotulo }));
  await waitFor(() => expect(screen.getByLabelText("Prazo do gatilho (dias)")).toBeTruthy());
}

// ═══════════════════════════════════════════════════════════════════════════════
describe("DefinitionStrip — o seletor de motor", () => {
  it("abre na ValerIA e a mantém SOMENTE LEITURA", () => {
    render(<DefinitionStrip definition={definicao() as never} />);

    // A esteira dela continua desenhada como sempre esteve.
    expect(naTela()).toContain("T1");
    expect(naTela()).toContain("T3");
    expect(naTela()).toContain("Reengajar");

    // E nenhum campo editável: o objetivo de cada toque dela é prompt de LLM (spec §6).
    expect(screen.queryByLabelText(/^Dias do toque/)).toBeNull();
    expect(screen.queryByLabelText(/^Template do toque/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Salvar" })).toBeNull();
  });

  it("troca para o João e mostra os cinco funis pelo nome completo", async () => {
    await abrirJoao();
    expect(screen.getByRole("button", { name: "João - Atacado" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "João - Private Label" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "João - Reposição Atacado" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "João - Reposição Private Label" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "João - Recuperação" })).toBeTruthy();
  });

  it("volta para a ValerIA sem deixar campo editável para trás", async () => {
    await abrirJoao();
    fireEvent.click(screen.getByRole("button", { name: "Valéria" }));
    expect(screen.queryByLabelText(/^Dias do toque/)).toBeNull();
    expect(naTela()).toContain("T1");
  });
});

describe("DefinitionStrip — navegação por funil, depois por cadência", () => {
  it("dentro de um funil, lista só as cadências dele", async () => {
    await abrirJoao();
    // Funil Atacado começa selecionado: Novo + Em conversa + Proposta Enviada.
    expect(screen.getByRole("button", { name: "Novo" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Em conversa" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reposição" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Em atenção" })).toBeNull();
  });

  it("o funil Atacado mostra as TRÊS cadências, com a nova Proposta Enviada", async () => {
    // Nenhum código de navegação foi escrito para isto (spec §6): este nível renderiza
    // `funil.cadencias` inteiro, então a terceira aparece sozinha. O teste existe para
    // provar que aparece MESMO, e não porque alguém a listou à mão.
    await abrirJoao();
    const cadencias = ["Novo", "Em conversa", "Proposta Enviada"];
    for (const nome of cadencias) {
      expect(screen.getByRole("button", { name: nome })).toBeTruthy();
    }
    // E ela abre como qualquer outra: 4 toques editáveis.
    await abrirCadencia("Proposta Enviada");
    expect(screen.getByLabelText("Dias do toque 4")).toBeTruthy();
    expect(screen.queryByLabelText("Dias do toque 5")).toBeNull();
  });

  it("Private Label também tem as três", async () => {
    await abrirJoao();
    await abrirFunil("João - Private Label");
    expect(screen.getByRole("button", { name: "Proposta Enviada" })).toBeTruthy();
  });

  it("os funis de Reposição continuam com duas cadências", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    expect(screen.getByRole("button", { name: "Reposição" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Em atenção" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Proposta Enviada" })).toBeNull();
  });

  it("trocar de funil troca as cadências oferecidas", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    expect(screen.getByRole("button", { name: "Reposição" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Em atenção" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Novo" })).toBeNull();
  });

  it("funil Recuperação (vazio) mostra o estado vazio, sem quebrar a tela", async () => {
    await abrirJoao();
    fireEvent.click(screen.getByRole("button", { name: "João - Recuperação" }));
    expect(naTela()).toContain("Nenhuma cadência configurada ainda para este funil.");
    // Nada de editor para uma cadência que não existe.
    expect(screen.queryByLabelText("Prazo do gatilho (dias)")).toBeNull();
    expect(screen.queryByRole("button", { name: "Salvar" })).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// O cabeçalho da cadência — DUAS frases condicionais (spec 2026-09-23 §5 e §6)
//
// A tentação é montar a frase inteira sempre, com os números que vierem. Os dois
// testes negativos deste bloco são o que impede isso: a tela mentiria sobre o gatilho
// das cadências de Reposição ("0 dia(s) sem conversa", quando elas disparam só por
// tempo de etapa) e inventaria um destino que não existe ("move o card para null",
// porque `dias_ate_mover` chega 1 até quando não há para onde mover).
// ═══════════════════════════════════════════════════════════════════════════════
describe("DefinitionStrip — o relógio completo no cabeçalho", () => {
  it("Novo: mostra OS DOIS números do gatilho e o destino do card", async () => {
    await abrirJoao(); // abre em Atacado / Novo
    expect(naTela()).toContain("Dispara com o card parado 2 dia(s) na etapa Novo");
    expect(naTela()).toContain("2 dia(s) sem conversa");
    expect(naTela()).toContain("espera 1 dia e move o card para Em atenção");
  });

  it("Proposta Enviada: SEM frase de silêncio, COM frase do move", async () => {
    // O caso misto, e o que prova que as duas frases são independentes: silêncio 0
    // (o dono pediu "24h depois da proposta", não "24h sem conversar") mas o card
    // vai para "Em atenção" igual.
    await abrirJoao();
    await abrirCadencia("Proposta Enviada");
    expect(naTela()).toContain(
      "Dispara com o card parado 1 dia(s) na etapa Proposta Enviada",
    );
    expect(naTela()).not.toContain("sem conversa");
    expect(naTela()).toContain("espera 1 dia e move o card para Em atenção");
  });

  it("Reposição: sem frase de silêncio, e o destino sai da linha do gatilho", async () => {
    // `gatilho_silencio_dias: 0` — ela dispara só por tempo de ETAPA. E o destino
    // final NÃO aparece mais aqui em cima: ele virou o último passo da jornada (o
    // bloco de baixo), porque dizer duas vezes para onde o card vai é repetição em
    // que o operador lê uma metade e ignora a outra.
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("Dispara com o card parado 45 dia(s) na etapa Cliente Ativo");
    expect(naTela()).not.toContain("sem conversa");
    expect(naTela()).not.toContain("depois do último toque");
  });

  it("dias_ate_mover sozinho NUNCA basta: sem rótulo, sem frase", async () => {
    // A mutação explícita: um payload com `dias_ate_mover: 3` e destino nulo. Quem
    // condicionar a frase ao número escreve "move o card para null" aqui.
    //
    // O caso mora em "Em atenção" desde 26/09: ela é a cadência que sobrou sem
    // destino, depois que "Reposição" ganhou o dela (spec §1).
    const def = definicao();
    def.joao.funis[2].cadencias[1].dias_ate_mover = 3;
    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Em atenção");
    expect(naTela()).not.toContain("move o card para");
    expect(naTela()).not.toContain("null");
    expect(naTela()).not.toContain("undefined");
  });

  it('"Em atenção" mantém a frase do repete_ultimo e não ganha frase de move', async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Em atenção");
    expect(naTela()).toContain("o último toque se repete até o lead pedir para parar");
    expect(naTela()).not.toContain("move o card para");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// O que a RESPOSTA do lead faz — a frase de 25/09/2026 (spec §4)
//
// Desde 25/09 responder não mata mais a esteira: os toques restantes DESLIZAM e
// continuam de onde pararam. Sem esta frase o comportamento é invisível, e um toque
// chegando três dias depois de uma conversa é lido como atraso do motor.
//
// O que estes testes existem para travar não é a frase, é a FONTE do número. Ele mora
// em `cadence_joao.ADIAMENTO_RESPOSTA` e chega por `adiamento_resposta_dias`; um "3"
// digitado no componente passaria em qualquer teste que usasse o payload padrão — por
// isso o teste da mutação abaixo troca o valor e exige que a TELA mude junto. Escrever
// o número à mão é a classe de defeito que mandou `{{nome}}` literal para clientes no
// WhatsApp em setembro.
// ═══════════════════════════════════════════════════════════════════════════════
describe("DefinitionStrip — a resposta do lead adia os toques restantes", () => {
  it("Novo: a frase aparece com o número que veio no payload", async () => {
    await abrirJoao(); // abre em Atacado / Novo
    expect(naTela()).toContain(
      "Se o lead responder, os toques restantes esperam 3 dias e continuam de onde pararam.",
    );
  });

  it("vale para as CINCO esteiras, inclusive as de Reposição", async () => {
    // As de Reposição são o caso que mudou de comportamento nesta entrega (antes a
    // resposta matava; agora adia igual às outras) e são também as que NÃO movem card
    // — ou seja, o lugar natural para alguém condicionar a frase ao
    // `etapa_final_rotulo` por engano.
    await abrirJoao();
    for (const c of ["Novo", "Em conversa", "Proposta Enviada"]) {
      await abrirCadencia(c);
      expect(naTela()).toContain("os toques restantes esperam 3 dias");
    }
    await abrirFunil("João - Reposição Atacado");
    for (const c of ["Reposição", "Em atenção"]) {
      await abrirCadencia(c);
      expect(naTela()).toContain("os toques restantes esperam 3 dias");
    }
  });

  it("MUTAÇÃO: payload com 7 → a tela diz 7, nunca o 3 do motor de hoje", async () => {
    // O teste que separa "lê o payload" de "tem um 3 escrito à mão". Com um literal no
    // componente, os dois testes acima ficariam VERDES e só este fica vermelho.
    const def = definicao();
    def.joao.funis[0].cadencias[0].adiamento_resposta_dias = 7;
    await abrirJoao(def);
    expect(naTela()).toContain("os toques restantes esperam 7 dias");
    expect(naTela()).not.toContain("esperam 3 dias");
  });

  it("MUTAÇÃO: payload com 1 → singular, sem o (s) preguiçoso", async () => {
    const def = definicao();
    def.joao.funis[0].cadencias[0].adiamento_resposta_dias = 1;
    await abrirJoao(def);
    expect(naTela()).toContain("os toques restantes esperam 1 dia e continuam");
    expect(naTela()).not.toContain("esperam 1 dias");
  });

  it("campo AUSENTE (backend antigo): sem frase, e sem 'undefined' na tela", async () => {
    // O CRM e o FastAPI sobem separados — um frontend novo contra o backend de ontem
    // recebe a cadência sem a chave. Calar é a única saída honesta: a tela não tem
    // como saber o prazo, e "esperam undefined dias" é pior que silêncio.
    const def = definicao();
    const cadencias = def.joao.funis[0].cadencias as Partial<
      ReturnType<typeof cadenciaDoFunil>
    >[];
    delete cadencias[0].adiamento_resposta_dias;
    await abrirJoao(def);
    expect(naTela()).not.toContain("os toques restantes");
    expect(naTela()).not.toContain("undefined");
    // O resto do cabeçalho continua inteiro: a frase que falta não derruba as outras.
    expect(naTela()).toContain("Dispara com o card parado 2 dia(s) na etapa Novo");
  });

  it("campo 0: sem frase (mesma leitura do silêncio 0)", async () => {
    // `0` não é "adia zero dias", é "não sei" — e "esperam 0 dias" descreveria um
    // motor que dispara em cima da resposta do lead, que é o oposto da regra.
    const def = definicao();
    def.joao.funis[0].cadencias[0].adiamento_resposta_dias = 0;
    await abrirJoao(def);
    expect(naTela()).not.toContain("os toques restantes");
    expect(naTela()).not.toContain("esperam 0");
  });

  it("a frase sobrevive ao salvar (o PUT devolve a cadência com o campo)", async () => {
    // Depois de salvar, o componente substitui a cadência pela que o PUT devolveu. Se
    // essa resposta perdesse o campo, a frase sumiria da tela sem erro nenhum — que é
    // exatamente como um campo só-leitura costuma desaparecer.
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    fireEvent.change(screen.getByLabelText("Prazo do gatilho (dias)"), {
      target: { value: "50" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(naTela()).toContain("os toques restantes esperam 3 dias");
  });
});

describe("DefinitionStrip — edição dos toques do João", () => {
  it("só oferece template APROVADO no <select>", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");

    const select = screen.getByLabelText("Template do toque 1") as HTMLSelectElement;
    const nomes = Array.from(select.options).map((o) => o.value);
    expect(nomes).toContain("joao_reposicao_atacado_t1");
    expect(nomes).toContain("joao_reposicao_atacado_t2");
    // PENDING na Meta nunca vira opção.
    expect(nomes).not.toContain("joao_ainda_pendente");
  });

  it("grava MERGE: 1 PUT só, com funil + cadência + o que mudou", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");

    fireEvent.change(screen.getByLabelText("Dias do toque 2"), {
      target: { value: "20" },
    });
    fireEvent.change(screen.getByLabelText("Template do toque 1"), {
      target: { value: "joao_reposicao_atacado_t2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({
      funil: "reposicao_atacado",
      cadencia: "reposicao",
      toques: {
        "1": { template_name: "joao_reposicao_atacado_t2" },
        "2": { dias: 20 },
      },
    });
  });

  it("na cadência nova, `toques` vai como MAPA e `ativa` não vai sem clique", async () => {
    // Os dois jeitos de o PUT dar errado, e nenhum deles aparece na tela:
    //  1. `toques` é LISTA no GET e MAPA `{sequence: {...}}` no PUT — ecoar o objeto
    //     do GET devolve 400 `toques_invalidos`;
    //  2. `ativa` ecoado do GET é GRAVADO — uma tela que devolve o objeto inteiro
    //     desliga a cadência sem ninguém ter clicado em desligar.
    // Por isso o corpo é conferido por igualdade EXATA: campo a mais reprova.
    const def = definicao();
    putRespostas = [{ ok: true, status: 200, body: def.joao.funis[0].cadencias[2] }];
    await abrirJoao(def);
    await abrirCadencia("Proposta Enviada");

    fireEvent.change(screen.getByLabelText("Dias do toque 3"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(corposDoPut().length).toBe(1));
    const corpo = corposDoPut()[0];
    expect(corpo).toEqual({
      funil: "atacado",
      cadencia: "proposta",
      toques: { "3": { dias: 5 } },
    });
    // Explícito, porque a igualdade acima é fácil de afrouxar num refactor:
    expect(Array.isArray(corpo.toques)).toBe(false);
    expect("ativa" in corpo).toBe(false);
  });

  it("grava o prazo do gatilho num PUT sem toques", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");

    fireEvent.change(screen.getByLabelText("Prazo do gatilho (dias)"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({
      funil: "reposicao_atacado",
      cadencia: "reposicao",
      gatilho_dias: 60,
    });
  });

  it("mostra o que o CÓDIGO manda por baixo da sobreposição", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("padrão 45");
  });

  it("mostra o rótulo da etapa do gatilho, não a chave crua", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("na etapa Cliente Ativo");
  });

  it('a cadência "Em atenção" mostra o gatilho como "Cliente Ativo", nunca "Em atenção"', async () => {
    // Armadilha da spec §2: "Em atenção" vigia a etapa `novo` ("Cliente Ativo"), não a
    // etapa DE VERDADE chamada "Em atenção" que as quatro pipelines também têm.
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Em atenção");
    expect(naTela()).toContain("na etapa Cliente Ativo");
  });

  it("informa o botão 'Ainda tenho estoque' sem deixar editá-lo", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("Aceita adiamento");
    expect(screen.queryByLabelText(/Aceita adiamento do toque/)).toBeNull();
  });
});

describe("DefinitionStrip — A RECUSA APARECE (o erro de 16/09/2026)", () => {
  it("lista o toque recusado quando o backend recusa ligar", async () => {
    putRespostas = [{ ok: false, status: 400, body: RECUSA_TEMPLATE_PENDENTE }];
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    const alerta = await screen.findByRole("alert");
    const texto = alerta.textContent ?? "";
    // O NOME do template e o toque: é isso que diz ao operador o que fazer sem abrir
    // o console.
    expect(texto).toContain("joao_reposicao_atacado_t2");
    expect(texto).toContain("Toque 2");
  });

  it("não deixa a tela dizer que salvou quando o backend recusou", async () => {
    putRespostas = [{ ok: false, status: 400, body: RECUSA_TEMPLATE_PENDENTE }];
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await screen.findByRole("alert");
    expect(naTela()).not.toContain("Configuração salva");
    // E o rascunho não se perde: o operador corrige em cima do que digitou.
    expect((screen.getByLabelText("Ligar cadência") as HTMLInputElement).checked).toBe(true);
  });

  it("recusa sem `problemas` ainda diz alguma coisa", async () => {
    putRespostas = [{ ok: false, status: 502, body: { error: "backend respondeu 502" } }];
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");

    fireEvent.change(screen.getByLabelText("Dias do toque 2"), {
      target: { value: "20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent ?? "").toContain("502");
  });
});

describe("DefinitionStrip — Em atenção", () => {
  it("mostra 'sem template' antes mesmo de tentar ligar", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Em atenção");
    expect(naTela().toLowerCase()).toContain("sem template");
  });

  it("recusa ligar, nomeando o toque sem template", async () => {
    putRespostas = [{ ok: false, status: 400, body: RECUSA_EM_ATENCAO }];
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Em atenção");

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    const alerta = await screen.findByRole("alert");
    const texto = alerta.textContent ?? "";
    expect(texto).toContain("Toque 1");
    expect(corposDoPut()).toEqual([
      { funil: "reposicao_atacado", cadencia: "em_atencao", ativa: true },
    ]);
  });
});

describe("DefinitionStrip — desligar sempre funciona", () => {
  it("manda ativa:false e não mostra recusa nenhuma", async () => {
    const def = definicao();
    def.joao.funis[2].cadencias[0].ativa = true;
    putRespostas = [
      { ok: true, status: 200, body: { ...def.joao.funis[2].cadencias[0], ativa: false } },
    ];

    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect((screen.getByLabelText("Ligar cadência") as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() =>
      expect(corposDoPut()).toEqual([
        { funil: "reposicao_atacado", cadencia: "reposicao", ativa: false },
      ]),
    );
    await waitFor(() => expect(naTela()).toContain("Configuração salva"));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("DefinitionStrip — o payload da ValerIA não pode sumir", () => {
  it("aguenta um backend SEM o bloco do João (deploy antigo)", () => {
    const semJoao: Record<string, unknown> = { ...definicao() };
    delete semJoao.joao;
    render(<DefinitionStrip definition={semJoao as never} />);
    expect(naTela()).toContain("T1");
    expect(screen.queryByRole("button", { name: "João" })).toBeNull();
  });

  it("sem definição nenhuma, avisa em vez de quebrar", () => {
    render(<DefinitionStrip definition={null} />);
    expect(naTela()).toContain("indisponível");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// A JORNADA da Reposição — o cabeçalho conta as três etapas (spec 2026-09-26 §7)
//
// A esteira de Reposição passou a mover o card DUAS vezes: para "Já chamado" no 1º
// toque e para "Em atenção" no fim. Contar isso em pedaços ("dispara em X", "no fim
// vai para Y") esconde justamente o passo do meio — e é o passo do meio que faz o
// operador procurar no funil errado o card que sumiu de "Cliente Ativo".
//
// Nenhum rótulo de etapa é escrito no componente: "Cliente Ativo", "Já chamado" e
// "Em atenção" vêm os três do payload, porque a MESMA key significa coisas diferentes
// em funis diferentes (`novo` é "Novo" na prospecção). O teste de mutação abaixo é o
// que separa "lê o payload" de "tem os nomes digitados lá dentro".
// ═══════════════════════════════════════════════════════════════════════════════
describe("DefinitionStrip — a jornada completa da Reposição", () => {
  const JORNADA =
    "Entra em Cliente Ativo · o 1º toque move para Já chamado · no fim move para Em atenção";

  it("Reposição: a jornada inteira, numa frase só", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain(JORNADA);
  });

  it("vale igual em Reposição Private Label", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Private Label");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain(JORNADA);
  });

  it("e diz que a esteira segue viva nas DUAS etapas", async () => {
    // A metade não óbvia: a guarda de 25/09 cancela todo toque cujo card saiu da
    // etapa vigiada, então sem esta frase o card indo para "Já chamado" no toque 1
    // parece matar os toques 2, 3 e 4. É o oposto — é o que permite o move existir.
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain(
      "A esteira segue viva em Cliente Ativo e Já chamado: sair de Cliente Ativo não cancela os toques que faltam.",
    );
  });

  it("as outras cadências NÃO ganham jornada — o texto delas é o de antes", async () => {
    // O teste que protege as oito que não mudaram. Elas seguem com a frase do move no
    // fim da linha do gatilho, do jeito que estava em 23/09.
    await abrirJoao(); // Atacado / Novo
    expect(naTela()).toContain("espera 1 dia e move o card para Em atenção");
    expect(naTela()).not.toContain("Entra em");
    expect(naTela()).not.toContain("move para Já chamado");
    expect(naTela()).not.toContain("A esteira segue viva");
  });

  it('"Em atenção" também não: um toque, nenhum move no meio', async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Em atenção");
    expect(naTela()).not.toContain("Entra em");
    expect(naTela()).not.toContain("A esteira segue viva");
  });

  it("MUTAÇÃO: rótulos diferentes no payload → a tela diz os novos", async () => {
    // O teste que separa "lê o payload" de "tem 'Já chamado' digitado no componente".
    // Com literais no código, todos os testes acima ficariam VERDES e só este cai.
    const def = definicao();
    const reposicao = def.joao.funis[2].cadencias[0];
    reposicao.gatilho_stage_rotulo = "Cliente VIP";
    reposicao.toques[0].move_para_rotulo = "Já cutucado";
    reposicao.etapa_final_rotulo = "Geladeira";
    reposicao.etapas_vivas_rotulos = ["Cliente VIP", "Já cutucado"];

    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain(
      "Entra em Cliente VIP · o 1º toque move para Já cutucado · no fim move para Geladeira",
    );
    expect(naTela()).toContain("A esteira segue viva em Cliente VIP e Já cutucado");
    expect(naTela()).not.toContain("Já chamado");
    expect(naTela()).not.toContain("Cliente Ativo");
  });

  it("MUTAÇÃO: o move no toque 2 → a tela diz 2º, não 1º", async () => {
    // O ordinal vem do `sequence` do toque que move, não de um "1º" fixo.
    const def = definicao();
    const reposicao = def.joao.funis[2].cadencias[0];
    reposicao.toques[0].move_para_rotulo = null;
    reposicao.toques[1].move_para_rotulo = "Já chamado";

    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("o 2º toque move para Já chamado");
    expect(naTela()).not.toContain("o 1º toque move");
  });

  it("campo AUSENTE em todo toque (backend antigo): sem jornada, sem 'undefined'", async () => {
    // O CRM e o FastAPI sobem separados. Sem `move_para_rotulo`, a tela volta ao
    // cabeçalho de antes — inclusive com a frase do move na linha do gatilho, que é
    // a única informação de destino que ela tem.
    const def = definicao();
    const toques = def.joao.funis[2].cadencias[0].toques as Partial<
      ReturnType<typeof toque>
    >[];
    for (const t of toques) delete t.move_para_rotulo;

    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).not.toContain("Entra em");
    expect(naTela()).not.toContain("undefined");
    expect(naTela()).toContain("espera 1 dia e move o card para Em atenção");
  });

  it("`etapas_vivas_rotulos` ausente não apaga a jornada", async () => {
    // As duas frases são independentes: a jornada depende do MOVE, a de etapas vivas
    // depende da LISTA. Um backend que mandasse uma e não a outra não pode derrubar
    // as duas.
    const def = definicao();
    const cadencias = def.joao.funis[2].cadencias as Partial<
      ReturnType<typeof cadenciaDoFunil>
    >[];
    delete cadencias[0].etapas_vivas_rotulos;

    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(naTela()).toContain(JORNADA);
    expect(naTela()).not.toContain("A esteira segue viva");
    expect(naTela()).not.toContain("undefined");
  });

  it("a jornada sobrevive ao salvar (o PUT devolve a cadência com os campos)", async () => {
    await abrirJoao();
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    fireEvent.change(screen.getByLabelText("Prazo do gatilho (dias)"), {
      target: { value: "50" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(naTela()).toContain(JORNADA);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Os dois ajustes do MOTOR — FORA do bloco por-cadência (spec 2026-09-26 §7)
//
// O teto diário conta os disparos das cinco esteiras somadas e o adiamento do botão é
// uma constante do motor: se esses campos morassem dentro de uma cadência, haveria
// cinco cópias do mesmo número e a pergunta "qual delas vale?".
//
// Como em toda a aba, NENHUM número é escrito no componente. O teste de mutação troca
// os dois valores do payload e exige que a tela mude junto — com um "100" digitado lá
// dentro, os outros testes ficariam verdes e só ele cairia.
// ═══════════════════════════════════════════════════════════════════════════════
describe("DefinitionStrip — os ajustes globais do motor", () => {
  const TETO = "Teto diário de disparos";
  const ESPERA = 'Espera do botão "Ainda tenho estoque" (dias)';

  const valorDe = (rotulo: string) =>
    (screen.getByLabelText(rotulo) as HTMLInputElement).value;

  it("mostra os dois valores efetivos e os dois padrões de código", async () => {
    await abrirJoao();
    expect(valorDe(TETO)).toBe("100");
    expect(valorDe(ESPERA)).toBe("30");
    expect(naTela()).toContain("padrão 100");
    expect(naTela()).toContain("padrão 30");
  });

  it("MUTAÇÃO: payload com 250 e 7 → a tela diz 250 e 7, nunca 100 e 30", async () => {
    const def = definicao();
    def.joao.ajustes = ajustesDoMotor(250, 7);
    await abrirJoao(def);
    expect(valorDe(TETO)).toBe("250");
    expect(valorDe(ESPERA)).toBe("7");
    // E o PADRÃO continua visível ao lado: é o que diz ao operador de onde ele saiu
    // e como voltar.
    expect(naTela()).toContain("padrão 100");
    expect(naTela()).toContain("padrão 30");
  });

  it("ficam FORA da cadência: aparecem até no funil que não tem cadência nenhuma", async () => {
    // A prova estrutural de que não são campos por-cadência. "Recuperação" tem zero
    // cadências de propósito, e os dois ajustes continuam lá.
    await abrirJoao();
    fireEvent.click(screen.getByRole("button", { name: "João - Recuperação" }));
    expect(naTela()).toContain("Nenhuma cadência configurada ainda para este funil.");
    expect(screen.getByLabelText(TETO)).toBeTruthy();
    expect(screen.getByLabelText(ESPERA)).toBeTruthy();
  });

  it("não vazam para o corpo do PUT de cadência", async () => {
    // O PUT por cadência é conferido por igualdade exata em outros testes; aqui o
    // ponto é o inverso: mexer no ajuste global não pode entrar naquele corpo.
    await abrirJoao();
    fireEvent.change(screen.getByLabelText(TETO), { target: { value: "250" } });
    fireEvent.change(screen.getByLabelText("Dias do toque 2"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({
      funil: "atacado",
      cadencia: "novo",
      toques: { "2": { dias: 7 } },
    });
  });

  it("editar e salvar manda UM PUT com o corpo `{ajustes}`", async () => {
    putRespostas = [{ ok: true, status: 200, body: ajustesDoMotor(250, 7) }];
    await abrirJoao();
    fireEvent.change(screen.getByLabelText(TETO), { target: { value: "250" } });
    fireEvent.change(screen.getByLabelText(ESPERA), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajustes" }));

    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({
      ajustes: { teto_diario_disparos: 250, adiamento_estoque_dias: 7 },
    });
    await waitFor(() => expect(naTela()).toContain("Ajustes salvos."));
  });

  it("manda SÓ o que mudou — ausente é 'não mexe'", async () => {
    putRespostas = [{ ok: true, status: 200, body: ajustesDoMotor(250, 30) }];
    await abrirJoao();
    fireEvent.change(screen.getByLabelText(TETO), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajustes" }));
    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({ ajustes: { teto_diario_disparos: 250 } });
  });

  it("campo vazio vira `null` — o botão de desfazer", async () => {
    putRespostas = [{ ok: true, status: 200, body: ajustesDoMotor() }];
    await abrirJoao();
    fireEvent.change(screen.getByLabelText(TETO), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajustes" }));
    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({ ajustes: { teto_diario_disparos: null } });
  });

  it("A RECUSA APARECE — o erro de 16/09/2026 também vale aqui", async () => {
    putRespostas = [
      {
        ok: false,
        status: 400,
        body: {
          detail: {
            problemas: [
              {
                codigo: "ajuste_invalido",
                mensagem:
                  "`teto_diario_disparos` precisa ser um inteiro de 1 para cima (veio 0).",
              },
            ],
          },
        },
      },
    ];
    await abrirJoao();
    fireEvent.change(screen.getByLabelText(TETO), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar ajustes" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta.textContent ?? "").toContain("teto_diario_disparos");
    expect(naTela()).not.toContain("Ajustes salvos.");
  });

  it("bloco `ajustes` AUSENTE (backend antigo): a seção some, sem 'undefined'", async () => {
    // O CRM e o FastAPI sobem separados. Dois campos numéricos escrevendo `undefined`
    // em cima de uma configuração que o operador acha que está editando é pior que
    // não oferecer a edição.
    const def = definicao();
    const joao = def.joao as Partial<typeof def.joao>;
    delete joao.ajustes;

    await abrirJoao(def as ReturnType<typeof definicao>);
    expect(screen.queryByLabelText(TETO)).toBeNull();
    expect(screen.queryByLabelText(ESPERA)).toBeNull();
    expect(screen.queryByRole("button", { name: "Salvar ajustes" })).toBeNull();
    expect(naTela()).not.toContain("undefined");
    // E o resto da aba continua inteiro: a seção que falta não derruba o editor.
    expect(naTela()).toContain("Dispara com o card parado 2 dia(s) na etapa Novo");
  });

  it("o selo 'Aceita adiamento' usa o prazo do payload, nunca um 60 escrito à mão", async () => {
    // Até 25/09 o texto deste selo dizia "adia 60 dias" em código, e o motor adiava
    // 60. Agora o número é editável nesta mesma tela: um literal aqui viraria uma
    // frase calada, convincente e errada no instante em que alguém salvasse outro.
    const def = definicao();
    def.joao.ajustes = ajustesDoMotor(250, 7);
    await abrirJoao(def);
    await abrirFunil("João - Reposição Atacado");
    await abrirCadencia("Reposição");
    expect(screen.getAllByTitle(/adia 7 dias/).length).toBeGreaterThan(0);
    expect(screen.queryAllByTitle(/adia 60 dias/)).toHaveLength(0);
    expect(screen.queryAllByTitle(/adia 30 dias/)).toHaveLength(0);
  });
});

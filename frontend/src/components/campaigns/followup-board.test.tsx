/**
 * @vitest-environment jsdom
 *
 * O editor de cadências da aba Follow-up — DOIS motores num painel só.
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
) {
  return {
    sequence,
    dias,
    dias_codigo: dias,
    template_name,
    template_name_codigo: template_name,
    aceita_adiamento,
  };
}

function linha(nome: string, rotulo: string, toques: ReturnType<typeof toque>[]) {
  return {
    linha: nome,
    rotulo,
    pipeline_id: `pipe-${nome}`,
    toques,
    toques_sem_template: toques.filter((t) => !t.template_name).map((t) => t.sequence),
  };
}

/** O payload REAL de `GET /api/cadence/definition` (backend/app/follow_up/api.py). */
function definicao() {
  return {
    ...VALERIA,
    valeria: VALERIA,
    joao: {
      cadencias: [
        {
          codigo: "novo",
          rotulo: "Novo",
          job_type: "joao_novo",
          gatilho_stage_key: "novo",
          gatilho_dias: 2,
          gatilho_dias_codigo: 2,
          ativa: false,
          repete_ultimo: false,
          pode_ligar: true,
          linhas: [
            linha("atacado", "Atacado", [toque(1, 0, "joao_novo_atacado_t1")]),
            linha("private_label", "Private Label", [toque(1, 0, "joao_novo_privatelabel_t1")]),
          ],
        },
        {
          codigo: "reposicao",
          rotulo: "Reposição",
          job_type: "joao_reposicao",
          gatilho_stage_key: "novo",
          gatilho_dias: 45,
          gatilho_dias_codigo: 45,
          ativa: false,
          repete_ultimo: false,
          pode_ligar: true,
          linhas: [
            linha("atacado", "Atacado", [
              toque(1, 0, "joao_reposicao_atacado_t1", true),
              toque(2, 15, "joao_reposicao_atacado_t2", true),
            ]),
            linha("private_label", "Private Label", [
              toque(1, 0, "joao_reposicao_privatelabel_t1", true),
              toque(2, 15, "joao_reposicao_privatelabel_t2", true),
            ]),
          ],
        },
        {
          // Os 24 templates aprovados em 13/09/2026 cobrem Novo + Em conversa +
          // Reposição. "Em atenção" nasceu depois do lote e NÃO tem texto aprovado —
          // ligá-la é sempre recusado, e isso é declaração de `cadence_joao.py`.
          codigo: "em_atencao",
          rotulo: "Em atenção",
          job_type: "joao_em_atencao",
          gatilho_stage_key: "novo",
          gatilho_dias: 90,
          gatilho_dias_codigo: 90,
          ativa: false,
          repete_ultimo: true,
          pode_ligar: false,
          linhas: [
            linha("atacado", "Atacado", [toque(1, 3, null, true)]),
            linha("private_label", "Private Label", [toque(1, 3, null, true)]),
          ],
        },
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
          "O toque 1 da linha Atacado não tem template configurado. Escolha um template aprovado para esse toque antes de ligar a cadência.",
        cadencia: "em_atencao",
        linha: "atacado",
        sequence: 1,
      },
      {
        codigo: "toque_sem_template",
        mensagem:
          "O toque 1 da linha Private Label não tem template configurado. Escolha um template aprovado para esse toque antes de ligar a cadência.",
        cadencia: "em_atencao",
        linha: "private_label",
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
          "O toque 2 da linha Atacado usa o template `joao_reposicao_atacado_t2`, que está PENDING na Meta. Espere a aprovação da Meta e ligue a cadência depois.",
        cadencia: "reposicao",
        linha: "atacado",
        sequence: 2,
      },
      {
        codigo: "template_nao_aprovado",
        mensagem:
          "O toque 2 da linha Private Label usa o template `joao_reposicao_privatelabel_t2`, que NÃO EXISTE na Meta — nunca foi submetido, ou foi criado com outro nome.",
        cadencia: "reposicao",
        linha: "private_label",
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
        // Sucesso padrão: o backend devolve a cadência já RESOLVIDA.
        return resposta({ body: definicao().joao.cadencias[1] });
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
  // O <select> de template só existe depois que /api/templates responde.
  await screen.findByLabelText("Template do toque 1 (Atacado)");
  return utils;
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

  it("troca para o João e mostra as cadências dele", async () => {
    await abrirJoao();
    expect(screen.getByRole("button", { name: "Novo" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reposição" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Em atenção" })).toBeTruthy();
  });

  it("volta para a ValerIA sem deixar campo editável para trás", async () => {
    await abrirJoao();
    fireEvent.click(screen.getByRole("button", { name: "Valéria" }));
    expect(screen.queryByLabelText(/^Dias do toque/)).toBeNull();
    expect(naTela()).toContain("T1");
  });
});

describe("DefinitionStrip — edição dos toques do João", () => {
  it("só oferece template APROVADO no <select>", async () => {
    await abrirJoao();
    await abrirCadencia("Reposição");

    const select = screen.getByLabelText("Template do toque 1 (Atacado)") as HTMLSelectElement;
    const nomes = Array.from(select.options).map((o) => o.value);
    expect(nomes).toContain("joao_reposicao_atacado_t1");
    expect(nomes).toContain("joao_reposicao_atacado_t2");
    // PENDING na Meta nunca vira opção.
    expect(nomes).not.toContain("joao_ainda_pendente");
  });

  it("grava MERGE: o PUT leva só o toque e o campo que mudaram", async () => {
    await abrirJoao();
    await abrirCadencia("Reposição");

    fireEvent.change(screen.getByLabelText("Dias do toque 2 (Atacado)"), {
      target: { value: "20" },
    });
    fireEvent.change(screen.getByLabelText("Template do toque 1 (Atacado)"), {
      target: { value: "joao_reposicao_atacado_t2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({
      cadencia: "reposicao",
      // `template_name` é específico da LINHA: sem ela o backend recusa
      // (linha_obrigatoria) e o texto do Atacado iria para o Private Label.
      linha: "atacado",
      toques: {
        "1": { template_name: "joao_reposicao_atacado_t2" },
        "2": { dias: 20 },
      },
    });
  });

  it("grava o prazo do gatilho num PUT de cadência, sem toques", async () => {
    await abrirJoao();
    await abrirCadencia("Reposição");

    fireEvent.change(screen.getByLabelText("Prazo do gatilho (dias)"), {
      target: { value: "60" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(corposDoPut().length).toBe(1));
    expect(corposDoPut()[0]).toEqual({ cadencia: "reposicao", gatilho_dias: 60 });
  });

  it("mostra o que o CÓDIGO manda por baixo da sobreposição", async () => {
    await abrirJoao();
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("padrão 45");
  });

  it("informa o botão 'Ainda tenho estoque' sem deixar editá-lo", async () => {
    await abrirJoao();
    await abrirCadencia("Reposição");
    expect(naTela()).toContain("Aceita adiamento");
    expect(screen.queryByLabelText(/Aceita adiamento do toque/)).toBeNull();
  });
});

describe("DefinitionStrip — A RECUSA APARECE (o erro de 16/09/2026)", () => {
  it("lista template por template quando o backend recusa ligar", async () => {
    putRespostas = [{ ok: false, status: 400, body: RECUSA_TEMPLATE_PENDENTE }];
    await abrirJoao();
    await abrirCadencia("Reposição");

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    const alerta = await screen.findByRole("alert");
    const texto = alerta.textContent ?? "";
    // O NOME de cada template, e a linha + o toque de cada um: é isso que diz ao
    // operador o que fazer sem abrir o console.
    expect(texto).toContain("joao_reposicao_atacado_t2");
    expect(texto).toContain("joao_reposicao_privatelabel_t2");
    expect(texto).toContain("Toque 2 · Atacado");
    expect(texto).toContain("Toque 2 · Private Label");
  });

  it("não deixa a tela dizer que salvou quando o backend recusou", async () => {
    putRespostas = [{ ok: false, status: 400, body: RECUSA_TEMPLATE_PENDENTE }];
    await abrirJoao();
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
    await abrirCadencia("Reposição");

    fireEvent.change(screen.getByLabelText("Dias do toque 2 (Atacado)"), {
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
    await abrirCadencia("Em atenção");
    expect(naTela().toLowerCase()).toContain("sem template");
  });

  it("recusa ligar, nomeando os dois toques sem template", async () => {
    putRespostas = [{ ok: false, status: 400, body: RECUSA_EM_ATENCAO }];
    await abrirJoao();
    await abrirCadencia("Em atenção");

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    const alerta = await screen.findByRole("alert");
    const texto = alerta.textContent ?? "";
    expect(texto).toContain("Toque 1 · Atacado");
    expect(texto).toContain("Toque 1 · Private Label");
    expect(corposDoPut()).toEqual([{ cadencia: "em_atencao", ativa: true }]);
  });
});

describe("DefinitionStrip — desligar sempre funciona", () => {
  it("manda ativa:false e não mostra recusa nenhuma", async () => {
    const def = definicao();
    def.joao.cadencias[1].ativa = true;
    putRespostas = [{ ok: true, status: 200, body: { ...def.joao.cadencias[1], ativa: false } }];

    await abrirJoao(def);
    await abrirCadencia("Reposição");
    expect((screen.getByLabelText("Ligar cadência") as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByLabelText("Ligar cadência"));
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(corposDoPut()).toEqual([{ cadencia: "reposicao", ativa: false }]));
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

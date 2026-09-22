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

function cadenciaDoFunil(
  codigo: string,
  rotulo: string,
  gatilhoStageRotulo: string,
  gatilhoDias: number,
  toques: ReturnType<typeof toque>[],
  extra: Partial<{ repete_ultimo: boolean; pode_ligar: boolean }> = {},
) {
  return {
    codigo,
    rotulo,
    job_type: `joao_${codigo}`,
    gatilho_stage_key: "novo",
    gatilho_stage_rotulo: gatilhoStageRotulo,
    gatilho_dias: gatilhoDias,
    gatilho_dias_codigo: gatilhoDias,
    ativa: false,
    repete_ultimo: extra.repete_ultimo ?? false,
    pode_ligar: extra.pode_ligar ?? true,
    toques,
    toques_sem_template: toques.filter((t) => !t.template_name).map((t) => t.sequence),
  };
}

function funil(codigo: string, rotulo: string, cadencias: ReturnType<typeof cadenciaDoFunil>[]) {
  return { codigo, rotulo, pipeline_id: `pipe-${codigo}`, cadencias };
}

/** O payload REAL de `GET /api/cadence/definition` (backend/app/follow_up/api.py):
 * `joao.funis`, cinco funis, "Recuperação" com `cadencias: []` de propósito. */
function definicao() {
  return {
    ...VALERIA,
    valeria: VALERIA,
    joao: {
      funis: [
        funil("atacado", "João - Atacado", [
          cadenciaDoFunil("novo", "Novo", "Novo", 2, [toque(1, 0, "joao_novo_atacado_t1")]),
          cadenciaDoFunil("em_conversa", "Em conversa", "Novo", 5, [
            toque(1, 0, "joao_em_conversa_atacado_t1"),
          ]),
        ]),
        funil("private_label", "João - Private Label", [
          cadenciaDoFunil("novo", "Novo", "Novo", 2, [
            toque(1, 0, "joao_novo_privatelabel_t1"),
          ]),
          cadenciaDoFunil("em_conversa", "Em conversa", "Novo", 5, [
            toque(1, 0, "joao_em_conversa_privatelabel_t1"),
          ]),
        ]),
        funil("reposicao_atacado", "João - Reposição Atacado", [
          cadenciaDoFunil("reposicao", "Reposição", "Cliente Ativo", 45, [
            toque(1, 0, "joao_reposicao_atacado_t1", true),
            toque(2, 15, "joao_reposicao_atacado_t2", true),
          ]),
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
          cadenciaDoFunil("reposicao", "Reposição", "Cliente Ativo", 45, [
            toque(1, 0, "joao_reposicao_privatelabel_t1", true),
            toque(2, 15, "joao_reposicao_privatelabel_t2", true),
          ]),
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
  it("dentro de um funil, lista só as cadências dele (no máximo 2)", async () => {
    await abrirJoao();
    // Funil Atacado começa selecionado: Novo + Em conversa.
    expect(screen.getByRole("button", { name: "Novo" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Em conversa" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Reposição" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Em atenção" })).toBeNull();
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

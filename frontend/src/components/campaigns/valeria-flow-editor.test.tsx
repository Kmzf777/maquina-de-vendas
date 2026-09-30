/**
 * @vitest-environment jsdom
 *
 * O painel da aba "Fluxo". Mesma convenção de `valeria-flow-modal.test.tsx`: docblock
 * de ambiente (o default do repo é `node`, `vitest.config.ts:10`), imports explícitos
 * do vitest, comentários em português.
 *
 * O que estes testes protegem, em uma frase cada:
 *
 *   • O contador BLOQUEIA o Salvar acima do limite e LIBERA exatamente NO limite. O
 *     backend também recusa (400), mas o operador tem de ver antes de gastar a ida e
 *     volta — e "exatamente no limite" é o off-by-one que faria a tela recusar um
 *     rótulo que a Meta aceita.
 *   • A PRÉVIA muda quando o rótulo muda. É a razão de existir do painel: sem isso o
 *     modal é uma caixa de texto que não explica nada a quem não lê código.
 *   • `destino` NÃO tem campo. `ConteudoUpdate` só aceita `corpo` e `rotulos`; um
 *     input de rota seria um controle que o operador mexe e o servidor descarta.
 *   • "Restaurar o texto original" só aparece onde há override (`editado`) — num item
 *     sem override o DELETE não tem o que apagar.
 *   • Selecionar um TERMINAL não estoura. `ItemFluxo` é união discriminada e o
 *     terminal não tem `botoes`: um `item.botoes.map` sem narrow quebra em runtime, não
 *     no build.
 *   • A chave reservada do botão de lista edita por `corpo`. Ler `.rotulo` (que o
 *     router não serializa) abriria o campo em branco e salvar esse branco é 400.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import {
  ValeriaFlowEditor,
  fragmentarMarcadores,
  montarGrupos,
  patchDoItem,
  problemasDoItem,
} from "./valeria-flow-editor";
import type {
  FluxoResposta,
  NoFluxo,
  PainelFluxoProps,
  ReservadoFluxo,
  TerminalFluxo,
} from "./valeria-flow-types";

// ═══════════════════════════════════════════════════════════════════════════════
// Fixtures — a forma que `valeria_flow_router.py` serializa, campo por campo
// ═══════════════════════════════════════════════════════════════════════════════

const N0: NoFluxo = {
  id: "N0",
  tipo: "no",
  rotulo_interno: "N0 · Setor",
  tela: "lista",
  ramo: "entrada",
  corpo: "Oi! Com o que você trabalha?",
  corpo_default: "Oi! Com o que você trabalha?",
  foto: null,
  produto: null,
  botoes: [
    {
      id: "atacado",
      rotulo: "Revenda / atacado",
      rotulo_default: "Revenda / atacado",
      destino: "N1",
      grava: [["setor", "atacado"]],
      descricao: "revenda, cafeteria, restaurante, hotel",
      // 24 porque N0 é tela de LISTA (`_limite_de_rotulo`).
      limite_rotulo: 24,
      editado: false,
    },
    {
      id: "consumo",
      rotulo: "Para casa",
      rotulo_default: "Para casa",
      destino: "C1",
      grava: [],
      descricao: "em casa ou de presente",
      limite_rotulo: 24,
      editado: false,
    },
  ],
  editaveis: ["corpo", "rotulos"],
  rotulos_antigos: [],
  editado: false,
};

const N1: NoFluxo = {
  id: "N1",
  tipo: "no",
  rotulo_interno: "N1 · Segmento",
  tela: "botoes",
  ramo: "atacado",
  corpo: "Qual é o seu segmento?",
  corpo_default: "Qual é o seu segmento?",
  foto: null,
  produto: null,
  botoes: [
    {
      id: "cafeteria",
      rotulo: "Cafeteria",
      rotulo_default: "Cafeteria",
      destino: "N2",
      grava: [["canal", "cafeteria"]],
      descricao: "",
      limite_rotulo: 20,
      editado: false,
    },
    {
      id: "mercado",
      rotulo: "Mercado",
      rotulo_default: "Mercado",
      destino: "N2",
      grava: [],
      descricao: "",
      limite_rotulo: 20,
      editado: false,
    },
  ],
  editaveis: ["corpo", "rotulos"],
  rotulos_antigos: [],
  editado: false,
};

const N5: NoFluxo = {
  id: "N5",
  tipo: "no",
  rotulo_interno: "N5 · Entrega + encaminhamento",
  tela: "foto_botoes",
  ramo: "atacado",
  corpo: "O Clássico 250g sai a {preco} a unidade.\nQuer que eu te passe pro João?",
  corpo_default: "O Clássico 250g sai a {preco} a unidade.\nQuer que eu te passe pro João?",
  foto: "atacado/foto_1_classico.jpg",
  produto: "Clássico 250g",
  botoes: [
    {
      id: "quero",
      rotulo: "Quero falar com o João",
      rotulo_default: "Quero falar com o João",
      destino: "T_HANDOFF",
      grava: [],
      descricao: "",
      limite_rotulo: 20,
      editado: true,
    },
  ],
  editaveis: ["corpo", "rotulos"],
  rotulos_antigos: [{ botao_id: "quero", rotulo: "Falar com o João", em: "2026-09-29T12:00:00Z" }],
  editado: true,
};

const T_HANDOFF: TerminalFluxo = {
  id: "T_HANDOFF",
  tipo: "terminal",
  rotulo_interno: "T_HANDOFF · Passa para o vendedor",
  corpo: "Vou te passar para o João.",
  corpo_default: "Vou te passar para o João.",
  vendedor: "joao",
  tags: ["handoff"],
  silenciar_ia: true,
  handoff: true,
  optout: false,
  prazos: false,
  editaveis: ["corpo"],
  editado: false,
};

const T_ADIAR: TerminalFluxo = {
  id: "T_ADIAR",
  tipo: "terminal",
  rotulo_interno: "T_ADIAR · Quando te procuro",
  corpo: "Quando você quer que eu te procure?",
  corpo_default: "Quando você quer que eu te procure?",
  vendedor: null,
  tags: [],
  silenciar_ia: false,
  handoff: false,
  optout: false,
  // BOOLEANO — a LISTA das linhas é `FluxoResposta.prazos`.
  prazos: true,
  editaveis: ["corpo"],
  editado: false,
};

const T_FIM: TerminalFluxo = {
  id: "T_FIM",
  tipo: "terminal",
  rotulo_interno: "T_FIM · Fim sem mensagem",
  // Vazio por CONTRATO no registry: este desfecho não gasta mensagem faturada.
  corpo: "",
  corpo_default: "",
  vendedor: null,
  tags: [],
  silenciar_ia: false,
  handoff: false,
  optout: false,
  prazos: false,
  editaveis: ["corpo"],
  editado: false,
};

const NUDGE: ReservadoFluxo = {
  chave: "__nudge__",
  id: "__nudge__",
  tipo: "reservado",
  rotulo_interno: "Reoferecimento (nudge)",
  corpo: "pra eu te passar o valor certo, é só tocar numa das opções 👇",
  corpo_default: "pra eu te passar o valor certo, é só tocar numa das opções 👇",
  editaveis: ["corpo"],
  editado: false,
  teto: 3,
};

// `_reservado_json` NÃO emite `rotulo`/`rotulo_default`: o texto mora em `corpo`.
const ROTULO_LISTA: ReservadoFluxo = {
  chave: "__rotulo_lista__",
  id: "__rotulo_lista__",
  tipo: "reservado",
  rotulo_interno: "Botão que abre a folha de opções",
  corpo: "Ver opções",
  corpo_default: "Ver opções",
  editaveis: ["corpo"],
  editado: false,
  limite: 20,
};

const FLUXO: FluxoResposta = {
  flow_id: "valeria_botoes_v1",
  no_entrada: "N0",
  limites: { rotulo_botao: 20, titulo_lista: 24, desc_lista: 72, max_botoes: 3, max_linhas_lista: 10 },
  editaveis: { no: ["corpo", "rotulos"], terminal: ["corpo"] },
  nos: [N0, N1, N5],
  terminais: [T_HANDOFF, T_ADIAR, T_FIM],
  nudge: NUDGE,
  rotulo_lista: ROTULO_LISTA,
  prazos: [
    { id: "p30", rotulo: "Em 30 dias", destino: "T_ADIADO", dias: 30, editavel: false },
    { id: "p60", rotulo: "Em 60 dias", destino: "T_ADIADO", dias: 60, editavel: false },
    // `dias` é `number | null`: `DIAS_POR_PRAZO.get()` é um `.get()` sem default.
    { id: "pnunca", rotulo: "Não me procure", destino: "T_ADIADO", dias: null, editavel: false },
  ],
};

function montar(sobrepor: Partial<FluxoResposta> = {}) {
  // Sem parâmetros declarados: `toHaveBeenCalledWith` lê os argumentos registrados de
  // qualquer jeito, e parâmetro nomeado e nunca usado é warning do eslint.
  const salvar = vi.fn<PainelFluxoProps["salvar"]>(async () => null);
  const restaurar = vi.fn<PainelFluxoProps["restaurar"]>(async () => null);
  render(
    <ValeriaFlowEditor
      dados={{ ...FLUXO, ...sobrepor }}
      salvar={salvar}
      restaurar={restaurar}
      salvando={null}
      erro={null}
    />,
  );
  return { salvar, restaurar };
}

const previa = () => screen.getByLabelText("Prévia do WhatsApp");
const botaoSalvar = () => screen.getByRole("button", { name: "Salvar" }) as HTMLButtonElement;
const irPara = (nome: RegExp) => fireEvent.click(screen.getByRole("button", { name: nome }));
/**
 * A coluna 2 lista só as telas do ramo selecionado — chegar a N1/N5 é DOIS cliques,
 * como para o operador. Clicar no ramo já seleciona a primeira tela dele (N1).
 */
const irParaAtacado = (tela?: RegExp) => {
  irPara(/^Atacado/);
  if (tela) irPara(tela);
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ═══════════════════════════════════════════════════════════════════════════════

describe("navegação em três colunas", () => {
  it("abre no nó de entrada e desenha o corpo dele na prévia", () => {
    montar();
    expect(screen.getByRole("heading", { name: "N0 · Setor" })).toBeTruthy();
    expect(within(previa()).getByText("Oi! Com o que você trabalha?")).toBeTruthy();
    // N0 é tela de lista: a prévia mostra o botão azul que abre a folha.
    expect(within(previa()).getByText("Ver opções")).toBeTruthy();
  });

  it("agrupa por ramo, com os desfechos e os dois textos reservados à parte", () => {
    const grupos = montarGrupos(FLUXO);
    expect(grupos.map((grupo) => grupo.rotulo)).toEqual(["Entrada", "Atacado", "Desfechos", "Textos soltos"]);
    expect(grupos[1].itens.map((item) => item.id)).toEqual(["N1", "N5"]);
    expect(grupos[3].itens.map((item) => item.id)).toEqual(["__nudge__", "__rotulo_lista__"]);
  });

  it("clicar num ramo seleciona a primeira tela dele", () => {
    montar();
    irPara(/^Atacado/);
    expect(screen.getByRole("heading", { name: "N1 · Segmento" })).toBeTruthy();
  });
});

describe("o contador manda no Salvar", () => {
  it("bloqueia um caractere ACIMA do limite, com o tamanho e o limite na mensagem", () => {
    montar();
    irParaAtacado();
    fireEvent.change(screen.getByLabelText("Rótulo do botão cafeteria"), {
      target: { value: "A".repeat(21) },
    });

    expect(botaoSalvar().disabled).toBe(true);
    expect(screen.getByText("rótulo de cafeteria tem 21 caracteres, o limite é 20")).toBeTruthy();
    expect(screen.getByText("21/20")).toBeTruthy();
  });

  it("libera EXATAMENTE no limite e manda só o rótulo que mudou", async () => {
    const { salvar } = montar();
    irParaAtacado();
    const vinte = "A".repeat(20);
    fireEvent.change(screen.getByLabelText("Rótulo do botão cafeteria"), { target: { value: vinte } });

    expect(botaoSalvar().disabled).toBe(false);
    expect(screen.getByText("20/20")).toBeTruthy();

    fireEvent.click(botaoSalvar());
    // `rotulos` é MERGE parcial no servidor: mandar o botão intocado seria reescrever
    // por cima do que outro operador acabou de salvar.
    expect(salvar).toHaveBeenCalledWith("N1", { rotulos: { cafeteria: vinte } });
  });

  it("usa o limite 24 da tela de LISTA, e não o 20 do botão comum", () => {
    montar();
    const vinteDois = "A".repeat(22);
    fireEvent.change(screen.getByLabelText("Rótulo do botão atacado"), { target: { value: vinteDois } });
    expect(screen.getByText("22/24")).toBeTruthy();
    expect(botaoSalvar().disabled).toBe(false);
  });

  it("bloqueia rótulo em branco — a Meta recusa a tela inteira, e o 400 do backend não pega esse caso", () => {
    montar();
    irParaAtacado();
    fireEvent.change(screen.getByLabelText("Rótulo do botão cafeteria"), { target: { value: "   " } });
    expect(botaoSalvar().disabled).toBe(true);
    expect(screen.getByText(/o rótulo de cafeteria não pode ficar vazio/)).toBeTruthy();
  });

  it("bloqueia corpo de nó em branco", () => {
    montar();
    fireEvent.change(screen.getByLabelText("Texto da tela"), { target: { value: " " } });
    expect(botaoSalvar().disabled).toBe(true);
    expect(screen.getByText("o corpo não pode ficar vazio")).toBeTruthy();
  });

  it("não deixa salvar quando nada mudou", () => {
    montar();
    expect(botaoSalvar().disabled).toBe(true);
    expect(screen.getByText("Nada alterado.")).toBeTruthy();
  });
});

describe("a prévia é o produto da tela", () => {
  it("troca a bolha no mesmo instante em que o rótulo é digitado", () => {
    montar();
    irParaAtacado();
    expect(within(previa()).getByText("Cafeteria")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Rótulo do botão cafeteria"), { target: { value: "Sou cafeteria" } });

    expect(within(previa()).getByText("Sou cafeteria")).toBeTruthy();
    expect(within(previa()).queryByText("Cafeteria")).toBeNull();
  });

  it("troca o corpo junto, e avisa que a linha com {marcador} é cortada no envio", () => {
    montar();
    irParaAtacado(/N5 · Entrega/);
    expect(within(previa()).getByText("{preco}")).toBeTruthy();
    expect(screen.getByText(/é CORTADA do envio quando o valor não existe/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Texto da tela"), { target: { value: "Sem marcador nenhum" } });
    expect(within(previa()).getByText("Sem marcador nenhum")).toBeTruthy();
    expect(screen.queryByText(/é CORTADA do envio quando o valor não existe/)).toBeNull();
  });

  it("diz que o desfecho de corpo vazio não manda nada, em vez de desenhar bolha vazia", () => {
    montar();
    irPara(/^Desfechos/);
    irPara(/T_FIM · Fim sem mensagem/);
    expect(within(previa()).getByText(/não gasta mensagem faturada/)).toBeTruthy();
  });
});

describe("o que a tela NÃO edita", () => {
  it("mostra o destino só-leitura, sem nenhum campo que o receba de volta", () => {
    montar();
    irParaAtacado();

    // Os dois botões de N1 levam a N2, e os dois aparecem como texto.
    expect(screen.getAllByText("→ N2")).toHaveLength(2);

    // Três campos e nada mais: o corpo e os dois rótulos.
    const campos = screen.getAllByRole("textbox") as HTMLInputElement[];
    expect(campos).toHaveLength(3);
    expect(campos.map((campo) => campo.value)).not.toContain("N2");
  });

  it("mostra os prazos 30/60/90 como leitura, inclusive o que não tem dias", () => {
    montar();
    irPara(/^Desfechos/);
    irPara(/T_ADIAR/);
    // A linha aparece nos DOIS lugares, e é isso que se quer: a tabela só-leitura do
    // editor e a folha que a prévia desenha por cima do desfecho.
    expect(screen.getAllByText("Em 30 dias")).toHaveLength(2);
    expect(screen.getByText(/30 dias · → T_ADIADO/)).toBeTruthy();
    expect(screen.getByText(/sem prazo · → T_ADIADO/)).toBeTruthy();
    expect(within(previa()).getByText("em 30 dias")).toBeTruthy();
    // E nenhum campo editável entrou junto: só o corpo do desfecho.
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
  });
});

describe("restaurar o texto original", () => {
  it("não aparece num item sem override", () => {
    montar();
    expect(screen.queryByRole("button", { name: "Restaurar o texto original" })).toBeNull();
  });

  it("aparece no item editado e chama o DELETE daquele id", () => {
    const { restaurar } = montar();
    irParaAtacado(/N5 · Entrega/);
    fireEvent.click(screen.getByRole("button", { name: "Restaurar o texto original" }));
    expect(restaurar).toHaveBeenCalledWith("N5");
  });
});

describe("terminal — a união discriminada", () => {
  it("seleciona um desfecho sem estourar e diz o que ele FAZ", () => {
    montar();
    irPara(/^Desfechos/);
    irPara(/T_HANDOFF/);

    expect(screen.getByRole("heading", { name: "T_HANDOFF · Passa para o vendedor" })).toBeTruthy();
    expect(screen.getByText("passa para um vendedor")).toBeTruthy();
    expect(screen.getByText("vendedor: joao")).toBeTruthy();
    expect(screen.getByText("silencia a IA")).toBeTruthy();
    expect(screen.getByText("tag: handoff")).toBeTruthy();

    // Terminal não tem `botoes`: nenhum campo de rótulo aparece, e o corpo é o único.
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByLabelText("Texto do desfecho")).toBeTruthy();
  });

  it("aceita esvaziar o corpo onde o DEFAULT já era vazio, e recusa onde não era", () => {
    montar();
    irPara(/^Desfechos/);

    irPara(/T_HANDOFF/);
    fireEvent.change(screen.getByLabelText("Texto do desfecho"), { target: { value: "" } });
    expect(botaoSalvar().disabled).toBe(true);

    irPara(/T_FIM/);
    fireEvent.change(screen.getByLabelText("Texto do desfecho"), { target: { value: "Tchau!" } });
    fireEvent.change(screen.getByLabelText("Texto do desfecho"), { target: { value: "" } });
    // Voltou ao valor do servidor: não há patch, então não há o que salvar.
    expect(screen.getByText("Nada alterado.")).toBeTruthy();
  });
});

describe("chaves reservadas — o texto mora em `corpo`", () => {
  it("abre o botão de lista com o texto do servidor, não em branco", () => {
    montar();
    irPara(/^Textos soltos/);
    irPara(/Botão que abre a folha/);

    const campo = screen.getByLabelText("Rótulo do botão que abre a folha") as HTMLInputElement;
    expect(campo.value).toBe("Ver opções");
    expect(screen.getByText("10/20")).toBeTruthy();
  });

  it("salva por `corpo` e nunca manda `rotulos` (que ali é 400)", () => {
    const { salvar } = montar();
    irPara(/^Textos soltos/);
    irPara(/Botão que abre a folha/);

    fireEvent.change(screen.getByLabelText("Rótulo do botão que abre a folha"), {
      target: { value: "Escolher aqui" },
    });
    // A prévia mostra o rótulo novo DENTRO da tela de lista, que é onde o lead o lê.
    expect(within(previa()).getByText("Escolher aqui")).toBeTruthy();

    fireEvent.click(botaoSalvar());
    expect(salvar).toHaveBeenCalledWith("__rotulo_lista__", { corpo: "Escolher aqui" });
  });

  it("bloqueia o botão de lista acima dos 20 caracteres da Meta", () => {
    montar();
    irPara(/^Textos soltos/);
    irPara(/Botão que abre a folha/);
    fireEvent.change(screen.getByLabelText("Rótulo do botão que abre a folha"), {
      target: { value: "A".repeat(21) },
    });

    expect(botaoSalvar().disabled).toBe(true);
    expect(screen.getByText("o rótulo do botão de lista tem 21 caracteres, o limite é 20")).toBeTruthy();
  });

  it("o nudge edita por `corpo` e mostra o teto de reoferecimentos", () => {
    const { salvar } = montar();
    irPara(/^Textos soltos/);
    expect(screen.getByRole("heading", { name: "Reoferecimento (nudge)" })).toBeTruthy();
    expect(screen.getByText(/O motor reoferece no máximo/).textContent).toContain("3");

    fireEvent.change(screen.getByLabelText("Texto do reoferecimento"), { target: { value: "Ainda por aí?" } });
    fireEvent.click(botaoSalvar());
    expect(salvar).toHaveBeenCalledWith("__nudge__", { corpo: "Ainda por aí?" });
  });
});

describe("funções puras", () => {
  it("patchDoItem manda só o que mudou, e nunca `rotulos` fora de um nó", () => {
    expect(patchDoItem(N1, undefined)).toBeNull();
    expect(patchDoItem(N1, { corpo: N1.corpo })).toBeNull();
    expect(patchDoItem(N1, { corpo: "Outro" })).toEqual({ corpo: "Outro" });
    expect(patchDoItem(N1, { rotulos: { cafeteria: "Cafeteria", mercado: "Mercadinho" } })).toEqual({
      rotulos: { mercado: "Mercadinho" },
    });
    // Um rascunho com `rotulos` num terminal não vira payload: ali o backend é 400.
    expect(patchDoItem(T_HANDOFF, { rotulos: { qualquer: "x" } })).toBeNull();
  });

  it("problemasDoItem fala as palavras do backend", () => {
    expect(problemasDoItem(N1, { rotulos: { cafeteria: "A".repeat(20) } })).toEqual([]);
    expect(problemasDoItem(N1, { rotulos: { cafeteria: "A".repeat(21) } })).toEqual([
      { campo: "cafeteria", mensagem: "rótulo de cafeteria tem 21 caracteres, o limite é 20" },
    ]);
    expect(problemasDoItem(NUDGE, { corpo: "" })).toEqual([
      { campo: "corpo", mensagem: "o corpo do nudge não pode ficar vazio" },
    ]);
    expect(problemasDoItem(ROTULO_LISTA, { corpo: "" })).toEqual([
      { campo: "corpo", mensagem: "o rótulo do botão de lista não pode ficar vazio" },
    ]);
    // Terminal: vazio só passa onde o DEFAULT já era vazio.
    expect(problemasDoItem(T_FIM, { corpo: "" })).toEqual([]);
    expect(problemasDoItem(T_HANDOFF, { corpo: "" })).toEqual([
      { campo: "corpo", mensagem: "o corpo não pode ficar vazio" },
    ]);
  });

  it("fragmentarMarcadores separa os `{marcadores}` do texto", () => {
    expect(fragmentarMarcadores("sai a {preco} a unidade")).toEqual([
      { texto: "sai a ", marcador: false },
      { texto: "{preco}", marcador: true },
      { texto: " a unidade", marcador: false },
    ]);
    expect(fragmentarMarcadores("sem nenhum")).toEqual([{ texto: "sem nenhum", marcador: false }]);
    // `{Preco}` com maiúscula não é marcador para `valeria_runner._MARCADOR`.
    expect(fragmentarMarcadores("{Preco}")).toEqual([{ texto: "{Preco}", marcador: false }]);
  });
});

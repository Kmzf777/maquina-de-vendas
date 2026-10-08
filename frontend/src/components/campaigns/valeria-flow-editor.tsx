"use client";

/**
 * O PAINEL da aba "Fluxo" do modal "ValerIA de Botões": três colunas — ramos → telas
 * do ramo → editor da tela — e a PRÉVIA do WhatsApp ao lado do editor.
 *
 * A casca (`valeria-flow-modal.tsx`) busca, guarda e grava; aqui só se escolhe o que
 * editar, se digita e se vê o resultado. As props são `PainelFluxoProps`, declaradas
 * em `valeria-flow-types.ts`.
 *
 * ── Por que a prévia é o centro do painel, e não um enfeite ─────────────────────
 * Quem edita este fluxo não lê código. Sem a prévia, "rótulo do botão atacado" é uma
 * caixa de texto que não explica nada: o operador não vê que 21 caracteres somem na
 * Meta, que a linha com `{preco}` é CORTADA quando o catálogo não tem preço
 * (`valeria_runner._resolver`), que numa tela de lista o `descricao` vira a segunda
 * linha da folha (`valeria_runner` monta `(id, titulo, descricao)`), nem que um
 * desfecho de corpo vazio não manda mensagem NENHUMA. A prévia mostra as quatro
 * coisas sem uma palavra de documentação.
 *
 * ── O que esta tela NÃO edita, de propósito ─────────────────────────────────────
 * `destino` e `grava` aparecem só-leitura. Não é preguiça: `ConteudoUpdate` declara
 * `corpo` e `rotulos` e mais nada, então um campo de rota aqui seria um controle que
 * o operador mexe e o servidor descarta em silêncio — a classe de bug que o cabeçalho
 * de `valeria_flow_router.py` chama de "override morto e invisível".
 *
 * ── As três formas em que este arquivo pisaria em falso ─────────────────────────
 *   1. `ItemFluxo` é união DISCRIMINADA. Terminal não tem `botoes`; `item.botoes.map`
 *      num terminal estoura em runtime. Toda leitura passa por `item.tipo`.
 *   2. As duas chaves reservadas guardam o texto em `corpo`, nunca em `rotulo` — é
 *      `corpo` que a coluna tem e que o `PUT` aceita. Ler `.rotulo` abriria o campo
 *      vazio e salvar esse vazio é 400.
 *   3. `prazos` é nome repetido: `TerminalFluxo.prazos` é BOOLEANO ("este desfecho
 *      oferece a folha 30/60/90") e `FluxoResposta.prazos` é a LISTA dessas linhas.
 *
 * ── O contador bloqueia o Salvar, e por quê ─────────────────────────────────────
 * O backend já recusa com 400 (`valeria_content.validar`), com a mensagem que a casca
 * mostra literal. O bloqueio local não substitui isso: evita a ida e volta e mostra o
 * problema no campo, no caractere em que ele acontece. Os limites vêm do servidor
 * (`botao.limite_rotulo`, 24 em lista e 20 em botão comum; `reservado.limite`), nunca
 * de constante local — dois números diferentes fariam o contador dizer "cabe" e o
 * save dizer "não cabe".
 *
 * Um rótulo VAZIO também bloqueia aqui, e isso é a única regra que este painel tem
 * além do backend: `validar` só compara TAMANHO de rótulo (`len > limite`), então
 * `{"rotulos": {"cafeteria": ""}}` passa pelo 400, é aplicado por
 * `valeria_content.aplicar` e a Meta recusa a tela INTEIRA no envio — a ValerIA fica
 * muda naquele nó. Bloquear na tela é mais barato que descobrir em produção.
 *
 * ── A v2 (vitrine) entra pelas MESMAS peças ─────────────────────────────────────
 * O `GET ?flow_id=valeria_botoes_v2` tem a forma da v1 e mais duas coisas (contrato C7
 * do plano `2026-10-08-valeria-botoes-v2-vitrine.md`):
 *   • `cards` nas vitrines (`tela: "carrossel"`). Cada card grava SOZINHO, pela chave
 *     canônica `card:<nó>:<id>` que o servidor manda em `chave` (o atalho `card:<id>`
 *     é 400 quando o id existe em duas vitrines), então tem caixa, contador e Salvar
 *     próprios dentro da tela do nó.
 *     O contador conta o `{preco:…}` como o preço que vai sair, não como o marcador cru,
 *     porque o limite de 160 do backend é medido DEPOIS dessa troca — e o 422 que ele
 *     devolve quando passa aparece no próprio card. O tamanho NÃO bloqueia o Salvar
 *     (só o servidor conhece o preço de verdade); vazio e mais de 2 quebras bloqueiam,
 *     porque não dependem de preço.
 *   • `textos` (regras do atacado, como funciona da marca própria, cada FAQ). Viram
 *     itens `reservado` num grupo próprio e reaproveitam o editor de corpo inteiro —
 *     gravam pela chave, como o nudge.
 */

import { useMemo, useState } from "react";
import type {
  BotaoFluxo,
  CardFluxo,
  ConteudoUpdate,
  FluxoResposta,
  ItemFluxo,
  NoFluxo,
  PainelFluxoProps,
  PrazoFluxo,
  RamoFluxo,
  ReservadoFluxo,
  TelaFluxo,
  TerminalFluxo,
  TextoFluxo,
} from "./valeria-flow-types";

// ═════════════════════════════════════════════════════════════════════════════════
// Constantes — as duas chaves reservadas e o marcador de corpo
// ═════════════════════════════════════════════════════════════════════════════════

/** `reg.CHAVE_NUDGE`. */
export const CHAVE_NUDGE = "__nudge__";
/** `reg.CHAVE_ROTULO_LISTA`. */
export const CHAVE_ROTULO_LISTA = "__rotulo_lista__";
/** `valeria_registry_v2.CHAVE_REGRAS_ATACADO`. */
export const CHAVE_REGRAS_ATACADO = "__regras_atacado__";
/** `valeria_registry_v2.CHAVE_COMO_FUNCIONA_PL`. */
export const CHAVE_COMO_FUNCIONA_PL = "__como_funciona_pl__";

/** `valeria_tabela.LIMITE_CARD_CHARS` e `LIMITE_CARD_QUEBRAS`: o card depois dos preços. */
export const LIMITE_CARD = 160;
export const LIMITE_QUEBRAS_CARD = 2;

/**
 * Quanto um `{preco:…}` ocupa depois de resolvido, para o contador. O backend formata
 * "R$ 35,90" (`valeria_tabela._formatar`); um preço de quatro dígitos ("R$ 1.169,70")
 * passa disso, e é por isso que o contador é estimativa e quem decide é o 422.
 */
const PRECO_ESTIMADO = "R$ 00,00";
const MARCADOR_PRECO = /\{preco:[^}]*\}/g;

/**
 * Os marcadores da v2: os de sempre (`{total_pl}`) e os com argumento
 * (`{preco:<nome do produto>}`, que o padrão da v1 não reconhece por causa dos `:`).
 */
const MARCADOR_V2 = /\{[a-z_]+(?::[^}]*)?\}/g;

/**
 * O MESMO padrão de `valeria_runner._MARCADOR`. Vale a duplicação porque o efeito é
 * visual e drástico: a linha que tem um marcador não resolvido é CORTADA do envio, e
 * a prévia precisa poder avisar.
 */
const MARCADOR = /\{[a-z_]+\}/g;

/** A hora falsa da bolha. Estática de propósito: prévia não é relógio. */
const HORA = "12:03";

/** O chat é um TELEFONE, não esta página: fonte de sistema, não a tipografia da casa. */
const FONTE_CHAT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

const RAMOS: { chave: RamoFluxo; rotulo: string; descricao: string }[] = [
  { chave: "entrada", rotulo: "Entrada", descricao: "A primeira tela — pergunta com o que o lead trabalha" },
  { chave: "atacado", rotulo: "Atacado", descricao: "Revenda, cafeteria, restaurante, hotel" },
  { chave: "private_label", rotulo: "Marca própria", descricao: "Café embalado com a marca do cliente" },
  { chave: "consumo", rotulo: "Consumo", descricao: "Consumidor final" },
  { chave: "exportacao", rotulo: "Exportação", descricao: "Mercado externo" },
];

const ROTULO_TELA: Record<TelaFluxo, string> = {
  lista: "lista",
  botoes: "botões",
  foto_botoes: "foto + botões",
  carrossel: "carrossel",
};

// ═════════════════════════════════════════════════════════════════════════════════
// Funções puras — agrupamento, rascunho, patch e validação
// ═════════════════════════════════════════════════════════════════════════════════

/** Uma coluna-1: um ramo, os desfechos, ou os textos que não são de tela nenhuma. */
export interface GrupoFluxo {
  chave: string;
  rotulo: string;
  descricao: string;
  itens: ItemFluxo[];
}

/**
 * Os grupos da primeira coluna, na ordem em que a conversa acontece.
 *
 * Um nó de `ramo` que este arquivo não conhece (ramo novo no registry, front antigo)
 * cai em "Outros" em vez de desaparecer: a tela some silenciosamente é justamente o
 * modo de falhar que `valeria-flow-types.ts` documenta no cabeçalho.
 */
export function montarGrupos(dados: FluxoResposta): GrupoFluxo[] {
  const grupos: GrupoFluxo[] = RAMOS.map(({ chave, rotulo, descricao }) => ({
    chave,
    rotulo,
    descricao,
    itens: dados.nos.filter((no) => no.ramo === chave),
  }));

  const conhecidos = new Set<string>(RAMOS.map((ramo) => ramo.chave));
  const orfaos = dados.nos.filter((no) => !conhecidos.has(no.ramo));
  if (orfaos.length) {
    grupos.push({
      chave: "outros",
      rotulo: "Outros",
      descricao: "Telas de um ramo que esta versão da tela ainda não conhece",
      itens: orfaos,
    });
  }

  grupos.push({
    chave: "desfechos",
    rotulo: "Desfechos",
    descricao: "O que a ValerIA faz quando a conversa chega ao fim de um ramo",
    itens: dados.terminais,
  });
  const vitrine = itensDosTextos(dados);
  if (vitrine.length) {
    grupos.push({
      chave: "vitrine",
      rotulo: "Textos da vitrine",
      descricao: "Regras do atacado, como funciona a marca própria e as respostas de cada dúvida",
      itens: vitrine,
    });
  }
  grupos.push({
    chave: "textos",
    rotulo: "Textos soltos",
    descricao: "Texto que o lead lê e que não pertence a tela nenhuma",
    // Filtro defensivo: a v2 serve as mesmas duas chaves, mas um registry sem uma delas
    // não pode virar `undefined` na lista e estourar o painel inteiro.
    itens: [dados.nudge, dados.rotulo_lista].filter(Boolean),
  });

  return grupos.filter((grupo) => grupo.itens.length > 0);
}

/** O nome que o operador lê para uma chave de `textos` da v2. */
export function rotuloDoTexto(chave: string): string {
  if (chave === CHAVE_REGRAS_ATACADO) return "Regras do atacado";
  if (chave === CHAVE_COMO_FUNCIONA_PL) return "Como funciona (marca própria)";
  const faq = /^faq:([^:]+):(.+)$/.exec(chave);
  if (faq) {
    const ramo = RAMOS.find((candidato) => candidato.chave === faq[1])?.rotulo.toLowerCase() ?? faq[1];
    return `FAQ ${ramo} · ${faq[2].replace(/_/g, " ")}`;
  }
  return chave;
}

/**
 * Os `textos` da v2 como itens `reservado`: assim eles passam pelo MESMO editor de
 * corpo, pelo mesmo `patchDoItem` e pelo mesmo Restaurar que o nudge já usa.
 *
 * As chaves do nudge e do botão de lista ficam de fora: a v2 também as lista em
 * `CHAVES_TEXTO`, mas elas já chegam como `nudge`/`rotulo_lista`, com `teto`/`limite`, e
 * aparecem em "Textos soltos". Desenhá-las duas vezes seria ter dois campos para o
 * mesmo texto, e o rascunho de um não apareceria no outro.
 */
export function itensDosTextos(dados: FluxoResposta): ReservadoFluxo[] {
  const jaMostradas = new Set([CHAVE_NUDGE, CHAVE_ROTULO_LISTA, dados.nudge?.id, dados.rotulo_lista?.id]);
  return (dados.textos ?? [])
    .filter((texto) => !jaMostradas.has(texto.chave))
    .map((texto: TextoFluxo) => ({
      chave: texto.chave,
      id: texto.chave,
      tipo: "reservado",
      rotulo_interno: texto.rotulo_interno || rotuloDoTexto(texto.chave),
      corpo: texto.corpo,
      corpo_default: texto.corpo_default,
      editaveis: ["corpo"],
      editado: texto.editado ?? texto.corpo !== texto.corpo_default,
    }));
}

/** É um texto da vitrine (v2), e não o nudge nem o botão de lista? */
function ehTextoVitrine(item: ItemFluxo): item is ReservadoFluxo {
  if (item.tipo !== "reservado") return false;
  // Sem chamar `ehRotuloLista`: ela é type guard, e o ramo falso dela tiraria
  // `ReservadoFluxo` da união — o resto desta linha viraria `never` para o compilador.
  const lista = item.chave === CHAVE_ROTULO_LISTA || typeof item.limite === "number";
  return !lista && item.chave !== CHAVE_NUDGE && typeof item.teto !== "number";
}

/** O que o operador digitou e ainda não salvou, por item. */
export interface RascunhoItem {
  corpo?: string;
  rotulos?: Record<string, string>;
}

export type Rascunhos = Record<string, RascunhoItem>;

/** O corpo na tela: o rascunho se existir, senão o que o servidor mandou. */
export function corpoEfetivo(item: ItemFluxo, rascunho?: RascunhoItem): string {
  return rascunho?.corpo ?? item.corpo;
}

/** O rótulo na tela. Mesma regra do corpo, por botão. */
export function rotuloEfetivo(botao: BotaoFluxo, rascunho?: RascunhoItem): string {
  return rascunho?.rotulos?.[botao.id] ?? botao.rotulo;
}

/**
 * É a chave do botão que abre a folha de opções?
 *
 * `chave` é o campo do router; `limite` é redundância defensiva (só `rotulo_lista`
 * recebe `limite` em `_reservado_json`) para o caso de a chave mudar de nome.
 */
export function ehRotuloLista(item: ItemFluxo): item is ReservadoFluxo {
  return item.tipo === "reservado" && (item.chave === CHAVE_ROTULO_LISTA || typeof item.limite === "number");
}

/**
 * O corpo do `PUT`, com só o que MUDOU — ou `null` quando nada mudou.
 *
 * `rotulos` é merge parcial no servidor, então mandar apenas o botão alterado é o
 * contrato, não economia. E `rotulos` NUNCA sai para terminal ou reservado: ali é 400
 * ("não tem botões próprios"), não 200 silencioso.
 */
export function patchDoItem(item: ItemFluxo, rascunho?: RascunhoItem): ConteudoUpdate | null {
  const patch: ConteudoUpdate = {};

  const corpo = rascunho?.corpo;
  if (corpo !== undefined && corpo !== item.corpo) patch.corpo = corpo;

  if (item.tipo === "no") {
    const rotulos: Record<string, string> = {};
    for (const botao of item.botoes) {
      const valor = rascunho?.rotulos?.[botao.id];
      if (valor !== undefined && valor !== botao.rotulo) rotulos[botao.id] = valor;
    }
    if (Object.keys(rotulos).length) patch.rotulos = rotulos;
  }

  return Object.keys(patch).length ? patch : null;
}

/** Um campo que impede o salvamento, com a mensagem que o operador lê. */
export interface ProblemaFluxo {
  /** `"corpo"` ou o `id` do botão. */
  campo: string;
  mensagem: string;
}

/**
 * O que ainda impede o `PUT`, nas palavras do backend.
 *
 * As mensagens espelham `valeria_content.validar` de propósito: quando o 400 vier
 * mesmo assim (dois operadores ao mesmo tempo, limite novo no registry), o operador lê
 * a MESMA frase nos dois lugares em vez de duas descrições do mesmo problema.
 */
export function problemasDoItem(item: ItemFluxo, rascunho?: RascunhoItem): ProblemaFluxo[] {
  const problemas: ProblemaFluxo[] = [];
  const corpo = corpoEfetivo(item, rascunho);

  if (item.tipo === "reservado") {
    if (ehRotuloLista(item)) {
      const limite = item.limite ?? 20;
      if (!corpo.trim()) {
        problemas.push({ campo: "corpo", mensagem: "o rótulo do botão de lista não pode ficar vazio" });
      } else if (corpo.length > limite) {
        problemas.push({
          campo: "corpo",
          mensagem: `o rótulo do botão de lista tem ${corpo.length} caracteres, o limite é ${limite}`,
        });
      }
    } else if (!corpo.trim()) {
      problemas.push({
        campo: "corpo",
        mensagem: ehTextoVitrine(item) ? "o texto não pode ficar vazio" : "o corpo do nudge não pode ficar vazio",
      });
    }
    return problemas;
  }

  if (item.tipo === "terminal") {
    // Vazio é CONTRATO onde o DEFAULT já era vazio (`T_HUMANO`, `T_FIM`): o desfecho
    // não gasta mensagem faturada. Nos outros, vazio é o mesmo 400 do backend — e a
    // pergunta que `validar` faz é sobre o default, não sobre o valor atual.
    if (!corpo.trim() && item.corpo_default !== "") {
      problemas.push({ campo: "corpo", mensagem: "o corpo não pode ficar vazio" });
    }
    return problemas;
  }

  if (!corpo.trim()) problemas.push({ campo: "corpo", mensagem: "o corpo não pode ficar vazio" });

  for (const botao of item.botoes) {
    const rotulo = rotuloEfetivo(botao, rascunho);
    if (!rotulo.trim()) {
      problemas.push({
        campo: botao.id,
        mensagem: `o rótulo de ${botao.id} não pode ficar vazio — a Meta recusa a tela inteira`,
      });
    } else if (rotulo.length > botao.limite_rotulo) {
      problemas.push({
        campo: botao.id,
        mensagem: `rótulo de ${botao.id} tem ${rotulo.length} caracteres, o limite é ${botao.limite_rotulo}`,
      });
    }
  }

  return problemas;
}

// ── Cards (v2) ────────────────────────────────────────────────────────────────

/**
 * A chave do rascunho de um card. Inclui o NÓ porque o mesmo `id` de card pode existir
 * em duas vitrines (`microlote` está na de atacado e na de marca própria): rascunhos
 * só pelo id de card vazariam de uma tela para a outra.
 */
export function chaveRascunhoCard(noId: string, cardId: string): string {
  return `${noId}#card:${cardId}`;
}

/**
 * A chave do `PUT`/`DELETE` do card: a do servidor, ou a forma canônica
 * `card:<nó>:<id>` — nunca o atalho `card:<id>`, que o backend recusa (400) quando o
 * id existe em duas vitrines.
 */
export function chaveDoCard(noId: string, card: CardFluxo): string {
  return card.chave || `card:${noId}:${card.id}`;
}

/** O card tem override? O servidor diz; sem o campo, compara com o default. */
function cardEditado(card: CardFluxo): boolean {
  return card.editado ?? card.corpo !== card.corpo_default;
}

/** O tamanho estimado do card depois de o backend trocar cada `{preco:…}` pelo preço. */
export function tamanhoCard(corpo: string): number {
  return corpo.replace(MARCADOR_PRECO, PRECO_ESTIMADO).length;
}

/**
 * O que impede o `PUT` do card AQUI. Só o que não depende do preço: vazio e quebras de
 * linha. O tamanho fica com o servidor (ver o cabeçalho do módulo).
 */
export function problemasDoCard(corpo: string, limiteQuebras: number = LIMITE_QUEBRAS_CARD): string[] {
  const problemas: string[] = [];
  if (!corpo.trim()) problemas.push("o texto do card não pode ficar vazio");
  const quebras = (corpo.match(/\n/g) ?? []).length;
  if (quebras > limiteQuebras) {
    problemas.push(`o card tem ${quebras} quebras de linha; a Meta aceita no máximo ${limiteQuebras} quebras de linha`);
  }
  return problemas;
}

/** Algum card deste nó tem rascunho diferente do servidor? Alimenta o "· não salvo". */
function cardsNaoSalvos(item: ItemFluxo, rascunhos: Rascunhos): boolean {
  if (item.tipo !== "no" || !item.cards) return false;
  return item.cards.some((card) => {
    const corpo = rascunhos[chaveRascunhoCard(item.id, card.id)]?.corpo;
    return corpo !== undefined && corpo !== card.corpo;
  });
}

/** Quebra o texto em pedaços, marcando os `{marcadores}` — a prévia os destaca. */
export function fragmentarMarcadores(texto: string, padrao: RegExp = MARCADOR): { texto: string; marcador: boolean }[] {
  const pedacos: { texto: string; marcador: boolean }[] = [];
  let ultimo = 0;
  for (const achado of texto.matchAll(padrao)) {
    const inicio = achado.index ?? 0;
    if (inicio > ultimo) pedacos.push({ texto: texto.slice(ultimo, inicio), marcador: false });
    pedacos.push({ texto: achado[0], marcador: true });
    ultimo = inicio + achado[0].length;
  }
  if (ultimo < texto.length) pedacos.push({ texto: texto.slice(ultimo), marcador: false });
  return pedacos;
}

// ═════════════════════════════════════════════════════════════════════════════════
// O painel
// ═════════════════════════════════════════════════════════════════════════════════

const CLASSE_ROTULO = "block text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]";
const CLASSE_CAMPO =
  "w-full rounded-[6px] border border-[#dedbd6] bg-white px-2 py-1.5 text-[13px] text-[#111111] outline-none transition-colors focus:border-[#111111] disabled:bg-[#faf9f6] disabled:text-[#7b7b78]";
const CLASSE_CAMPO_RUIM = "border-[#a4261b] focus:border-[#a4261b]";

export function ValeriaFlowEditor({ dados, salvar, restaurar, salvando, erro }: PainelFluxoProps) {
  const grupos = useMemo(() => montarGrupos(dados), [dados]);
  const indice = useMemo(() => {
    const mapa = new Map<string, { item: ItemFluxo; grupo: GrupoFluxo }>();
    for (const grupo of grupos) for (const item of grupo.itens) mapa.set(item.id, { item, grupo });
    return mapa;
  }, [grupos]);

  // Uma única fonte de verdade: o id selecionado. O grupo em destaque é DERIVADO dele,
  // então clicar num ramo e clicar numa tela nunca podem discordar.
  const [selecionadoId, setSelecionadoId] = useState<string>(() => dados.no_entrada);
  const [rascunhos, setRascunhos] = useState<Rascunhos>({});
  /** O card cujo último `PUT`/`DELETE` voltou recusado: é nele que a recusa aparece. */
  const [cardRecusado, setCardRecusado] = useState<string | null>(null);

  const atual = indice.get(selecionadoId) ?? indice.get(grupos[0]?.itens[0]?.id ?? "");

  if (!atual) {
    return <p className="px-4 py-12 text-center text-[13px] text-[#7b7b78]">Este fluxo não tem telas.</p>;
  }

  const { item, grupo } = atual;
  const rascunho = rascunhos[item.id];
  const problemas = problemasDoItem(item, rascunho);
  const patch = patchDoItem(item, rascunho);
  const gravandoEste = salvando === item.id;
  const podeSalvar = Boolean(patch) && problemas.length === 0 && !salvando;

  function escrever(id: string, mudanca: RascunhoItem) {
    setRascunhos((antes) => ({ ...antes, [id]: { ...antes[id], ...mudanca } }));
  }

  function escreverRotulo(id: string, botaoId: string, valor: string) {
    setRascunhos((antes) => ({
      ...antes,
      [id]: { ...antes[id], rotulos: { ...antes[id]?.rotulos, [botaoId]: valor } },
    }));
  }

  function descartar(id: string) {
    setRascunhos((antes) => {
      const proximo = { ...antes };
      delete proximo[id];
      return proximo;
    });
  }

  // O servidor devolve o item já mesclado e a casca o recoloca em `dados`; por isso o
  // rascunho é DESCARTADO no sucesso, em vez de virar o novo valor local — dois donos
  // do mesmo texto divergem na primeira gravação parcial.
  // Trocar de tela esquece qual card foi recusado: a recusa que ainda estiver em `erro`
  // volta para o rodapé em vez de ficar presa a um card que não é mais o assunto.
  function selecionar(id: string) {
    setCardRecusado(null);
    setSelecionadoId(id);
  }

  // Toda gravação que NÃO é de card zera `cardRecusado` antes de sair: a recusa que ela
  // trouxer é do corpo ou dos rótulos, e tem de aparecer no rodapé, não no card que
  // falhou antes.
  async function aoSalvar() {
    if (!patch || problemas.length || salvando) return;
    setCardRecusado(null);
    const salvo = await salvar(item.id, patch);
    if (salvo) descartar(item.id);
  }

  async function aoRestaurar() {
    if (salvando) return;
    setCardRecusado(null);
    const restaurado = await restaurar(item.id);
    if (restaurado) descartar(item.id);
  }

  // O card grava SOZINHO, pela chave dele (`card:<nó>:<id>`), e o rascunho dele mora
  // sob a chave que inclui o nó. Recusado, o rascunho FICA: o 422 do preço resolvido diz o
  // que encurtar, e apagar o texto junto obrigaria o operador a redigitar.
  async function aoGravarCard(noId: string, card: CardFluxo, corpo: string | null) {
    if (salvando) return;
    const chave = chaveRascunhoCard(noId, card.id);
    setCardRecusado(null);
    const nodeId = chaveDoCard(noId, card);
    const feito = corpo === null ? await restaurar(nodeId) : await salvar(nodeId, { corpo });
    if (feito) descartar(chave);
    else setCardRecusado(chave);
  }

  const problemaCorpo = problemas.find((problema) => problema.campo === "corpo");

  return (
    <div className="lg:grid lg:grid-cols-[132px_184px_minmax(0,1fr)] lg:divide-x lg:divide-[#dedbd6]">
      {/* ── Coluna 1: os ramos ─────────────────────────────────────────────── */}
      <nav
        aria-label="Ramos do fluxo"
        className="flex gap-1 overflow-x-auto border-b border-[#dedbd6] bg-[#faf9f6] px-3 py-2 lg:block lg:space-y-px lg:overflow-x-visible lg:border-b-0 lg:bg-transparent lg:px-2 lg:py-3"
      >
        <h3 className={`${CLASSE_ROTULO} hidden px-1.5 pb-1.5 lg:block`}>Ramos</h3>
        {grupos.map((candidato) => {
          const ativo = candidato.chave === grupo.chave;
          return (
            <button
              key={candidato.chave}
              type="button"
              title={candidato.descricao}
              aria-current={ativo ? "true" : undefined}
              // Clicar no ramo em que o operador JÁ está não mexe na seleção: ele
              // perderia a tela aberta (e o rascunho em foco) por um clique sem efeito.
              onClick={() => {
                if (candidato.chave !== grupo.chave) selecionar(candidato.itens[0].id);
              }}
              className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[4px] px-2 py-1.5 text-[12px] transition-colors lg:w-full lg:justify-between ${
                ativo
                  ? "bg-[#111111] text-white"
                  : "text-[#7b7b78] hover:bg-[#faf9f6] hover:text-[#111111] lg:hover:bg-[#f0ede8]"
              }`}
            >
              <span className="truncate">{candidato.rotulo}</span>
              <span className={`text-[10px] tabular-nums ${ativo ? "text-white/60" : "text-[#7b7b78]"}`}>
                {candidato.itens.length}
              </span>
            </button>
          );
        })}
      </nav>

      {/* ── Coluna 2: as telas do ramo ─────────────────────────────────────── */}
      <nav
        aria-label={`Telas de ${grupo.rotulo}`}
        className="flex gap-1 overflow-x-auto border-b border-[#dedbd6] px-3 py-2 lg:block lg:space-y-px lg:overflow-x-visible lg:border-b-0 lg:px-2 lg:py-3"
      >
        <h3 className={`${CLASSE_ROTULO} hidden px-1.5 pb-1.5 lg:block`}>{grupo.rotulo}</h3>
        {grupo.itens.map((candidato) => {
          const ativo = candidato.id === item.id;
          const naoSalvo =
            Boolean(patchDoItem(candidato, rascunhos[candidato.id])) || cardsNaoSalvos(candidato, rascunhos);
          return (
            <button
              key={candidato.id}
              type="button"
              aria-current={ativo ? "true" : undefined}
              onClick={() => selecionar(candidato.id)}
              className={`flex shrink-0 flex-col items-start gap-0.5 whitespace-nowrap border-l-2 px-2 py-1.5 text-left text-[12px] transition-colors lg:w-full lg:rounded-r-[4px] ${
                ativo
                  ? "border-[#111111] bg-[#faf9f6] font-medium text-[#111111]"
                  : "border-transparent text-[#7b7b78] hover:bg-[#faf9f6] hover:text-[#111111]"
              }`}
            >
              <span className="max-w-full truncate">{candidato.rotulo_interno}</span>
              <span className="flex items-center gap-1.5 text-[10px] font-normal uppercase tracking-[0.5px] text-[#7b7b78]">
                {candidato.tipo === "no" ? ROTULO_TELA[candidato.tela] : candidato.tipo === "terminal" ? "desfecho" : "texto"}
                {candidato.editado && <span className="normal-case tracking-normal">· editado</span>}
                {naoSalvo && <span className="normal-case tracking-normal text-[#a4261b]">· não salvo</span>}
              </span>
            </button>
          );
        })}
      </nav>

      {/* ── Coluna 3: o editor + a prévia ──────────────────────────────────── */}
      <div className="grid gap-4 px-3 py-3 sm:px-4 xl:grid-cols-[minmax(0,1fr)_276px]">
        <div className="min-w-0 space-y-3">
          <header>
            <h3 className="text-[14px] font-semibold tracking-tight text-[#111111]">{item.rotulo_interno}</h3>
            <p className="mt-0.5 text-[11px] text-[#7b7b78]">{explicacaoDoItem(item, dados)}</p>
          </header>

          {/* O corpo. Em `rotulo_lista` é uma linha só: é um rótulo de botão, não texto. */}
          <div>
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <label htmlFor="valeria-flow-corpo" className={CLASSE_ROTULO}>
                {rotuloDoCampoCorpo(item)}
              </label>
              <Contador
                atual={corpoEfetivo(item, rascunho).length}
                limite={ehRotuloLista(item) ? item.limite ?? null : null}
                ruim={Boolean(problemaCorpo)}
              />
            </div>
            {ehRotuloLista(item) ? (
              <input
                id="valeria-flow-corpo"
                aria-label="Rótulo do botão que abre a folha"
                aria-invalid={Boolean(problemaCorpo)}
                value={corpoEfetivo(item, rascunho)}
                disabled={gravandoEste || !item.editaveis.includes("corpo")}
                onChange={(evento) => escrever(item.id, { corpo: evento.target.value })}
                className={`${CLASSE_CAMPO} ${problemaCorpo ? CLASSE_CAMPO_RUIM : ""}`}
              />
            ) : (
              <textarea
                id="valeria-flow-corpo"
                aria-label={rotuloDoCampoCorpo(item)}
                aria-invalid={Boolean(problemaCorpo)}
                rows={item.tipo === "no" ? 5 : 4}
                value={corpoEfetivo(item, rascunho)}
                disabled={gravandoEste || !item.editaveis.includes("corpo")}
                onChange={(evento) => escrever(item.id, { corpo: evento.target.value })}
                className={`${CLASSE_CAMPO} resize-y leading-[19px] ${problemaCorpo ? CLASSE_CAMPO_RUIM : ""}`}
              />
            )}
            {problemaCorpo && <p className="mt-1 text-[11px] text-[#a4261b]">{problemaCorpo.mensagem}</p>}
            {item.tipo === "terminal" && item.corpo_default === "" && (
              <p className="mt-1 text-[11px] text-[#7b7b78]">
                Este desfecho nasce SEM mensagem, de propósito: vazio aqui significa que a ValerIA não manda nada e
                não gasta mensagem faturada.
              </p>
            )}
          </div>

          {item.tipo === "no" && item.cards && item.cards.length > 0 && (
            <CardsDoNo
              no={item}
              rascunhos={rascunhos}
              salvando={salvando}
              erro={erro}
              cardRecusado={cardRecusado}
              aoMudar={(chave, corpo) => escrever(chave, { corpo })}
              aoGravar={(card, corpo) => void aoGravarCard(item.id, card, corpo)}
            />
          )}
          {item.tipo === "no" && <CamposDoNo no={item} rascunho={rascunho} travado={gravandoEste} problemas={problemas} aoMudar={escreverRotulo} />}
          {item.tipo === "terminal" && <EfeitosDoTerminal terminal={item} prazos={dados.prazos} />}
          {item.tipo === "reservado" && typeof item.teto === "number" && (
            <p className="rounded-[6px] border border-[#dedbd6] bg-[#faf9f6] px-2.5 py-2 text-[11px] text-[#7b7b78]">
              O motor reoferece no máximo <span className="font-medium tabular-nums text-[#111111]">{item.teto}</span>{" "}
              vezes, com os MESMOS botões da tela em que o lead parou.
            </p>
          )}

          {/* ── Salvar / restaurar ──────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2 border-t border-[#dedbd6] pt-3">
            <button
              type="button"
              disabled={!podeSalvar}
              onClick={() => void aoSalvar()}
              className="rounded-[6px] bg-[#111111] px-3 py-1.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {gravandoEste ? "Salvando…" : "Salvar"}
            </button>

            {/* Só onde há override: `restaurar` é o DELETE do override inteiro deste
                item (corpo e rótulos juntos), e num item não editado não há o que apagar. */}
            {item.editado && (
              <button
                type="button"
                disabled={Boolean(salvando)}
                onClick={() => void aoRestaurar()}
                title="Apaga o override deste item — o corpo e os rótulos voltam ao texto do código."
                className="rounded-[6px] border border-[#dedbd6] px-3 py-1.5 text-[13px] text-[#111111] transition-colors hover:bg-[#faf9f6] disabled:opacity-40"
              >
                Restaurar o texto original
              </button>
            )}

            {problemas.length > 0 ? (
              <span className="text-[11px] text-[#a4261b]">Corrija o texto acima para salvar.</span>
            ) : !patch ? (
              <span className="text-[11px] text-[#7b7b78]">Nada alterado.</span>
            ) : null}

            {/* A recusa de um card já aparece DENTRO do card; repeti-la aqui faria o
                operador procurar o problema no corpo da tela. */}
            {erro && !cardRecusado && <span className="basis-full text-[11px] text-[#a4261b]">{erro}</span>}
          </div>
        </div>

        {/* A prévia acompanha a rolagem: o operador digita embaixo e vê em cima. */}
        <aside className="min-w-0 xl:sticky xl:top-0 xl:self-start">
          <PreviaDoItem item={item} dados={dados} rascunhos={rascunhos} />
        </aside>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// Pedaços do editor
// ═════════════════════════════════════════════════════════════════════════════════

function rotuloDoCampoCorpo(item: ItemFluxo): string {
  if (item.tipo === "no") return "Texto da tela";
  if (item.tipo === "terminal") return "Texto do desfecho";
  if (ehTextoVitrine(item)) return "Texto";
  if (ehRotuloLista(item)) return "Rótulo do botão que abre a folha";
  return "Texto do reoferecimento";
}

function explicacaoDoItem(item: ItemFluxo, dados: FluxoResposta): string {
  if (item.tipo === "no") {
    if (item.tela === "lista")
      return `Tela de lista: o corpo, o botão que abre a folha e até ${dados.limites.max_linhas_lista} linhas — cada linha aceita ${dados.limites.titulo_lista} caracteres.`;
    if (item.tela === "carrossel")
      return `Vitrine: o texto da tela, os cards do carrossel (cada um com foto e até ${LIMITE_CARD} caracteres depois dos preços) e até ${dados.limites.max_botoes} botões.`;
    if (item.tela === "foto_botoes")
      return `Foto no cabeçalho + até ${dados.limites.max_botoes} botões de ${dados.limites.rotulo_botao} caracteres.`;
    return `Até ${dados.limites.max_botoes} botões de resposta, de ${dados.limites.rotulo_botao} caracteres cada.`;
  }
  if (item.tipo === "terminal") return "Desfecho: o que a ValerIA faz quando a conversa chega aqui.";
  // Antes de `ehRotuloLista`: o ramo falso daquele type guard tira `ReservadoFluxo`
  // da união, e estas leituras de `chave` não compilariam depois dele.
  if (ehTextoVitrine(item)) {
    if (item.chave === CHAVE_REGRAS_ATACADO) return "As regras do atacado, que acompanham a tabela de preços da vitrine.";
    if (item.chave === CHAVE_COMO_FUNCIONA_PL)
      return "Como funciona a marca própria. Os {marcadores} são preenchidos com o catálogo no envio.";
    return "Resposta fixa que a ValerIA manda para esta dúvida.";
  }
  if (ehRotuloLista(item)) return "O botão azul que abre a folha de opções nas telas de lista.";
  return "O reoferecimento que o motor manda quando o lead não toca em nada.";
}

function Contador({
  atual,
  limite,
  ruim,
  testId,
  title,
}: {
  atual: number;
  limite: number | null;
  ruim: boolean;
  testId?: string;
  title?: string;
}) {
  return (
    <span
      data-testid={testId}
      title={title}
      className={`shrink-0 text-[11px] tabular-nums ${ruim ? "font-medium text-[#a4261b]" : "text-[#7b7b78]"}`}
    >
      {limite === null ? `${atual} caracteres` : `${atual}/${limite}`}
    </span>
  );
}

/**
 * Os cards do carrossel (v2). Cada um com caixa, contador, Salvar e Restaurar PRÓPRIOS:
 * o card grava pela chave canônica `card:<nó>:<id>` (a `chave` do servidor, ou
 * `chaveDoCard`), separado do corpo e dos botões do nó.
 */
function CardsDoNo({
  no,
  rascunhos,
  salvando,
  erro,
  cardRecusado,
  aoMudar,
  aoGravar,
}: {
  no: NoFluxo;
  rascunhos: Rascunhos;
  salvando: string | null;
  erro: string | null;
  cardRecusado: string | null;
  aoMudar: (chave: string, corpo: string) => void;
  aoGravar: (card: CardFluxo, corpo: string | null) => void;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className={CLASSE_ROTULO}>Cards do carrossel</h4>
        <span className="text-[10px] uppercase tracking-[0.5px] text-[#7b7b78]">preço = catálogo</span>
      </div>
      {(no.cards ?? []).map((card) => {
        const chave = chaveRascunhoCard(no.id, card.id);
        const rascunho = rascunhos[chave]?.corpo;
        const corpo = rascunho ?? card.corpo;
        const mudou = rascunho !== undefined && rascunho !== card.corpo;
        const limite = card.limite ?? LIMITE_CARD;
        const tamanho = tamanhoCard(corpo);
        const problemas = problemasDoCard(corpo, card.limite_quebras ?? LIMITE_QUEBRAS_CARD);
        const gravandoEste = salvando === chaveDoCard(no.id, card);
        const recusa = erro && cardRecusado === chave ? erro : null;
        const longo = tamanho > limite;
        const editado = cardEditado(card);
        return (
          <div key={card.id} data-testid={`card-${card.id}`} className="rounded-[6px] border border-[#dedbd6] bg-[#faf9f6] p-2.5">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <label htmlFor={`valeria-flow-card-${no.id}-${card.id}`} className="min-w-0 truncate text-[11px] text-[#7b7b78]">
                Card <span className="rounded-[4px] bg-white px-1 py-0.5 tabular-nums">{card.id}</span>
                {editado && <span> · editado</span>}
              </label>
              <Contador
                atual={tamanho}
                limite={limite}
                ruim={longo || problemas.length > 0}
                testId={`contador-card-${card.id}`}
                title="Cada {preco:…} conta como o preço que vai sair. O servidor confere com o preço real ao salvar."
              />
            </div>
            <textarea
              id={`valeria-flow-card-${no.id}-${card.id}`}
              aria-label={`Texto do card ${card.id}`}
              aria-invalid={longo || problemas.length > 0}
              rows={3}
              value={corpo}
              disabled={gravandoEste}
              onChange={(evento) => aoMudar(chave, evento.target.value)}
              className={`${CLASSE_CAMPO} resize-y leading-[19px] ${longo || problemas.length ? CLASSE_CAMPO_RUIM : ""}`}
            />
            {problemas.map((problema) => (
              <p key={problema} className="mt-1 text-[11px] text-[#a4261b]">
                {problema}
              </p>
            ))}
            {longo && !problemas.length && (
              <p className="mt-1 text-[11px] text-[#a4261b]">
                Passa de {limite} caracteres com os preços trocados — o servidor deve recusar.
              </p>
            )}
            {recusa && <p className="mt-1 text-[11px] text-[#a4261b]">{recusa}</p>}
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                aria-label={`Salvar card ${card.id}`}
                disabled={!mudou || problemas.length > 0 || Boolean(salvando)}
                onClick={() => aoGravar(card, corpo)}
                className="rounded-[6px] bg-[#111111] px-2.5 py-1 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {gravandoEste ? "Salvando…" : "Salvar card"}
              </button>
              {editado && (
                <button
                  type="button"
                  aria-label={`Restaurar card ${card.id}`}
                  disabled={Boolean(salvando)}
                  onClick={() => aoGravar(card, null)}
                  title="Apaga o override deste card — o texto volta ao do código."
                  className="rounded-[6px] border border-[#dedbd6] bg-white px-2.5 py-1 text-[12px] text-[#111111] transition-colors hover:bg-[#faf9f6] disabled:opacity-40"
                >
                  Restaurar
                </button>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}

/** Os rótulos dos botões do nó. `destino` e `grava` entram só-leitura. */
function CamposDoNo({
  no,
  rascunho,
  travado,
  problemas,
  aoMudar,
}: {
  no: NoFluxo;
  rascunho?: RascunhoItem;
  travado: boolean;
  problemas: ProblemaFluxo[];
  aoMudar: (id: string, botaoId: string, valor: string) => void;
}) {
  const editavel = no.editaveis.includes("rotulos");
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className={CLASSE_ROTULO}>{no.tela === "lista" ? "Linhas da folha" : "Botões"}</h4>
        <span className="text-[10px] uppercase tracking-[0.5px] text-[#7b7b78]">rota = código</span>
      </div>

      {no.foto && (
        <p className="rounded-[6px] border border-[#dedbd6] bg-[#faf9f6] px-2.5 py-2 text-[11px] text-[#7b7b78]">
          Foto do cabeçalho: <span className="text-[#111111]">{no.foto}</span>
          {no.produto && (
            <>
              {" · produto declarado: "}
              <span className="text-[#111111]">{no.produto}</span> (o preço vem do catálogo no instante do envio)
            </>
          )}
        </p>
      )}

      {no.botoes.map((botao, posicao) => {
        const valor = rotuloEfetivo(botao, rascunho);
        const problema = problemas.find((candidato) => candidato.campo === botao.id);
        return (
          <div key={botao.id} className="rounded-[6px] border border-[#dedbd6] bg-[#faf9f6] p-2.5">
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <label htmlFor={`valeria-flow-rotulo-${botao.id}`} className="min-w-0 truncate text-[11px] text-[#7b7b78]">
                {botao.descricao || `Botão ${posicao + 1}`}
              </label>
              <span
                title="Para onde este clique leva. A rota é estrutura e mora no código — não há campo que a receba de volta."
                className="shrink-0 rounded-[4px] border border-[#dedbd6] bg-white px-1.5 py-0.5 text-[11px] tabular-nums text-[#7b7b78]"
              >
                → {botao.destino}
              </span>
            </div>
            <input
              id={`valeria-flow-rotulo-${botao.id}`}
              aria-label={`Rótulo do botão ${botao.id}`}
              aria-invalid={Boolean(problema)}
              value={valor}
              disabled={travado || !editavel}
              onChange={(evento) => aoMudar(no.id, botao.id, evento.target.value)}
              className={`${CLASSE_CAMPO} ${problema ? CLASSE_CAMPO_RUIM : ""}`}
            />
            <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
              <span className="flex flex-wrap items-center gap-1 text-[10px] text-[#7b7b78]">
                <span className="rounded-[4px] bg-white px-1 py-0.5 tabular-nums">{botao.id}</span>
                {botao.editado && <span>· editado</span>}
                {botao.grava.map(([campo, valorGravado]) => (
                  <span key={campo} className="rounded-[4px] bg-white px-1 py-0.5" title="O clique grava isto no lead.">
                    {campo} = {String(valorGravado)}
                  </span>
                ))}
              </span>
              <Contador atual={valor.length} limite={botao.limite_rotulo} ruim={Boolean(problema)} />
            </div>
            {problema && <p className="mt-1 text-[11px] text-[#a4261b]">{problema.mensagem}</p>}
          </div>
        );
      })}
    </section>
  );
}

/** O que o desfecho FAZ. Tudo só-leitura: não há caminho de volta para efeitos. */
function EfeitosDoTerminal({ terminal, prazos }: { terminal: TerminalFluxo; prazos: PrazoFluxo[] }) {
  const efeitos: string[] = [];
  if (terminal.handoff) efeitos.push("passa para um vendedor");
  if (terminal.vendedor) efeitos.push(`vendedor: ${terminal.vendedor}`);
  if (terminal.silenciar_ia) efeitos.push("silencia a IA");
  if (terminal.optout) efeitos.push("marca opt-out");
  if (terminal.prazos) efeitos.push("oferece a folha 30/60/90");
  for (const tag of terminal.tags) efeitos.push(`tag: ${tag}`);

  return (
    <section className="space-y-2">
      <h4 className={CLASSE_ROTULO}>O que este desfecho faz</h4>
      {efeitos.length === 0 ? (
        <p className="text-[11px] text-[#7b7b78]">Nada além do texto acima.</p>
      ) : (
        <ul className="flex flex-wrap gap-1">
          {efeitos.map((efeito) => (
            <li
              key={efeito}
              className="rounded-[4px] border border-[#dedbd6] bg-[#faf9f6] px-1.5 py-0.5 text-[11px] text-[#7b7b78]"
            >
              {efeito}
            </li>
          ))}
        </ul>
      )}

      {/* `TerminalFluxo.prazos` é BOOLEANO; a lista é `FluxoResposta.prazos`. */}
      {terminal.prazos && (
        <div className="rounded-[6px] border border-[#dedbd6]">
          <p className="border-b border-[#dedbd6] bg-[#faf9f6] px-2.5 py-1.5 text-[10px] uppercase tracking-[0.6px] text-[#7b7b78]">
            A folha de adiamento — só-leitura
          </p>
          <ul>
            {prazos.map((prazo) => (
              <li
                key={prazo.id}
                className="flex items-baseline justify-between gap-2 border-b border-[#dedbd6] px-2.5 py-1.5 text-[12px] last:border-b-0"
              >
                <span className="truncate text-[#111111]">{prazo.rotulo}</span>
                <span className="shrink-0 text-[11px] tabular-nums text-[#7b7b78]">
                  {prazo.dias === null ? "sem prazo" : `${prazo.dias} dias`} · → {prazo.destino}
                </span>
              </li>
            ))}
          </ul>
          <p className="px-2.5 py-1.5 text-[11px] text-[#7b7b78]">
            Estes três vivem em <code className="rounded-[4px] bg-[#faf9f6] px-1">flows.PRAZOS</code>, que a Recuperação
            também serve — mudar aqui faria os dois fluxos dizerem números diferentes.
          </p>
        </div>
      )}
    </section>
  );
}

// ═════════════════════════════════════════════════════════════════════════════════
// A prévia
// ═════════════════════════════════════════════════════════════════════════════════

interface PreviaProps {
  corpo: string;
  /** `null` = mensagem de texto puro (desfecho, reoferecimento). */
  tela: TelaFluxo | null;
  linhas: { id: string; rotulo: string; descricao: string }[];
  foto: string | null;
  rotuloLista: string;
  /** Desfecho que por contrato não manda nada. */
  mudo: boolean;
  legenda: string;
  nota?: string;
  /** Só nas vitrines da v2: os cards do carrossel, com o rascunho já aplicado. */
  cards?: { id: string; corpo: string }[];
  /** Troca a nota genérica de `{marcador}` (a regra da v1) pela regra do item. */
  notaMarcador?: string;
  /** O padrão de marcador: o da v1 por omissão; os itens da v2 passam `MARCADOR_V2`. */
  padraoMarcador?: RegExp;
}

/** Escolhe o que a prévia recebe, a partir do item selecionado. Narra a união. */
function PreviaDoItem({
  item,
  dados,
  rascunhos,
}: {
  item: ItemFluxo;
  dados: FluxoResposta;
  rascunhos: Rascunhos;
}) {
  const rascunho = rascunhos[item.id];
  const corpo = corpoEfetivo(item, rascunho);
  const rotuloLista = dados.rotulo_lista
    ? corpoEfetivo(dados.rotulo_lista, rascunhos[dados.rotulo_lista.id])
    : "";

  if (item.tipo === "no") {
    const cards = item.cards?.map((card) => ({
      id: card.id,
      corpo: rascunhos[chaveRascunhoCard(item.id, card.id)]?.corpo ?? card.corpo,
    }));
    return (
      <PreviaWhatsApp
        corpo={corpo}
        cards={cards}
        padraoMarcador={cards?.length ? MARCADOR_V2 : undefined}
        notaMarcador={
          cards?.length
            ? "Cada {preco:…} vira o preço do catálogo no envio. Se um produto do card estiver sem preço, o card inteiro não sai."
            : undefined
        }
        tela={item.tela}
        linhas={item.botoes.map((botao) => ({
          id: botao.id,
          rotulo: rotuloEfetivo(botao, rascunho),
          descricao: botao.descricao,
        }))}
        foto={item.foto}
        rotuloLista={rotuloLista}
        mudo={false}
        legenda={item.id}
      />
    );
  }

  if (item.tipo === "terminal") {
    return (
      <PreviaWhatsApp
        corpo={corpo}
        tela={null}
        // `prazos` booleano do terminal escolhe a folha; as linhas são a lista do topo.
        linhas={
          item.prazos
            ? dados.prazos.map((prazo) => ({
                id: prazo.id,
                rotulo: prazo.rotulo,
                descricao: prazo.dias === null ? "" : `em ${prazo.dias} dias`,
              }))
            : []
        }
        foto={null}
        rotuloLista={rotuloLista}
        mudo={!corpo.trim()}
        legenda={item.id}
        nota={item.prazos ? "As três linhas da folha vêm do código, não desta tela." : undefined}
      />
    );
  }

  // Texto da vitrine (v2): mensagem de texto puro. Antes de `ehRotuloLista` pelo mesmo
  // motivo de `explicacaoDoItem`.
  if (ehTextoVitrine(item)) {
    return (
      <PreviaWhatsApp
        corpo={corpo}
        tela={null}
        linhas={[]}
        foto={null}
        rotuloLista={rotuloLista}
        mudo={false}
        legenda={item.chave}
        padraoMarcador={MARCADOR_V2}
        notaMarcador="Os {marcadores} são preenchidos com os valores do catálogo no envio."
      />
    );
  }

  // Reservado. O rótulo do botão de lista só faz sentido DENTRO de uma tela de lista,
  // então a prévia o mostra na tela de entrada — é ali que o lead o lê.
  if (ehRotuloLista(item)) {
    const noDaLista =
      dados.nos.find((no) => no.id === dados.no_entrada && no.tela === "lista") ??
      dados.nos.find((no) => no.tela === "lista");
    return (
      <PreviaWhatsApp
        corpo={noDaLista ? corpoEfetivo(noDaLista, rascunhos[noDaLista.id]) : ""}
        tela="lista"
        linhas={
          noDaLista
            ? noDaLista.botoes.map((botao) => ({
                id: botao.id,
                rotulo: rotuloEfetivo(botao, rascunhos[noDaLista.id]),
                descricao: botao.descricao,
              }))
            : []
        }
        foto={null}
        rotuloLista={corpo}
        mudo={false}
        legenda={noDaLista ? `na tela ${noDaLista.id}` : "tela de lista"}
        nota="Você edita só o botão azul; o resto da tela é do nó."
      />
    );
  }

  return (
    <PreviaWhatsApp
      corpo={corpo}
      tela={null}
      linhas={[]}
      foto={null}
      rotuloLista={rotuloLista}
      mudo={false}
      legenda="reoferecimento"
      nota="Sai com os MESMOS botões da tela em que o lead parou."
    />
  );
}

/**
 * A tela do WhatsApp, o mais fiel que HTML permite: chão do chat, bolha de entrada
 * branca, linhas de botão em `#027EB5` separadas por fio de cabelo, hora em
 * `#667781`. Fonte de SISTEMA — é um telefone, não a tipografia desta página.
 */
export function PreviaWhatsApp({ corpo, tela, linhas, foto, rotuloLista, mudo, legenda, nota, cards, notaMarcador, padraoMarcador }: PreviaProps) {
  // Pela MESMA função que a bolha usa: um `MARCADOR.test()` aqui mexeria no
  // `lastIndex` de um regex `/g` compartilhado e faria a segunda chamada mentir.
  const pedacos = fragmentarMarcadores(corpo, padraoMarcador);
  const temMarcador =
    pedacos.some((pedaco) => pedaco.marcador) ||
    Boolean(cards?.some((card) => fragmentarMarcadores(card.corpo, MARCADOR_V2).some((pedaco) => pedaco.marcador)));

  const comBotoes = tela === "botoes" || tela === "foto_botoes" || tela === "carrossel";
  const comLista = tela === "lista";

  return (
    <figure aria-label="Prévia do WhatsApp" className="overflow-hidden rounded-[8px] border border-[#dedbd6]">
      <figcaption className="flex items-baseline justify-between gap-2 border-b border-[#dedbd6] bg-[#faf9f6] px-2.5 py-1.5">
        <span className={CLASSE_ROTULO}>Como o lead vê</span>
        <span className="shrink-0 text-[10px] tabular-nums text-[#7b7b78]">{legenda}</span>
      </figcaption>

      <div
        className="space-y-2 bg-[#EFE7DE] px-2.5 py-3"
        style={{ fontFamily: FONTE_CHAT, backgroundImage: "radial-gradient(#e5dcd1 0.5px, transparent 0.5px)", backgroundSize: "14px 14px" }}
      >
        {mudo ? (
          <p className="mx-auto max-w-[236px] rounded-[7px] bg-white/70 px-2.5 py-1.5 text-center text-[12px] leading-[16px] text-[#667781]">
            Nada é enviado aqui. Este desfecho não gasta mensagem faturada.
          </p>
        ) : (
          <div className="max-w-[236px] overflow-hidden rounded-[7.5px] rounded-tl-[3px] bg-white shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]">
            {foto && (
              <div
                aria-hidden="true"
                className="flex h-[112px] flex-col items-center justify-center gap-1 bg-[#d9d2c8] text-[#5b5751]"
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4">
                  <rect x="3" y="4" width="18" height="16" rx="2" />
                  <circle cx="8.5" cy="9.5" r="1.6" />
                  <path d="M4 17l5-5 4 4 3-3 4 4" />
                </svg>
                <span className="max-w-[210px] truncate px-2 text-[10px]">{foto}</span>
              </div>
            )}
            <div className="px-2 pb-1 pt-1.5">
              <p className="whitespace-pre-wrap break-words text-[14px] leading-[19px] text-[#111b21]">
                {/* Corpo em branco num item que NÃO é o desfecho mudo: a bolha diria
                    nada e pareceria defeito da prévia, não do texto. */}
                {!corpo.trim() && <span className="italic text-[#667781]">(sem texto)</span>}
                {/* O pedaço comum sai como TEXTO, não como `<span>`: um span em volta
                    do corpo inteiro duplicaria o nó de texto e faria qualquer busca por
                    essa frase achar dois elementos (o `<p>` e o `<span>`). */}
                {pedacos.map((pedaco, indice) =>
                  pedaco.marcador ? (
                    <span
                      key={indice}
                      className="border-b border-dashed border-[#667781] text-[#667781]"
                      title="Marcador: se o valor não existir no envio, a Meta não recebe esta LINHA inteira."
                    >
                      {pedaco.texto}
                    </span>
                  ) : (
                    pedaco.texto
                  ),
                )}
              </p>
              <p aria-hidden="true" className="mt-0.5 text-right text-[11px] leading-[15px] text-[#667781]">
                {HORA}
              </p>
            </div>

            {comBotoes && linhas.length > 0 && (
              <div className="border-t border-[rgba(0,0,0,0.08)]">
                {linhas.map((linha, indice) => (
                  <div
                    key={linha.id}
                    className={`px-2 py-2 text-center text-[14px] leading-[18px] text-[#027EB5] ${
                      indice ? "border-t border-[rgba(0,0,0,0.08)]" : ""
                    }`}
                  >
                    {linha.rotulo.trim() ? linha.rotulo : <span className="italic text-[#667781]">(sem texto)</span>}
                  </div>
                ))}
              </div>
            )}

            {comLista && (
              <div className="flex items-center justify-center gap-1.5 border-t border-[rgba(0,0,0,0.08)] px-2 py-2 text-[14px] leading-[18px] text-[#027EB5]">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M4 6h16M4 12h16M4 18h16" />
                </svg>
                {rotuloLista.trim() ? rotuloLista : <span className="italic text-[#667781]">(sem texto)</span>}
              </div>
            )}
          </div>
        )}

        {/* O carrossel da vitrine: um card por produto, com a foto no topo. */}
        {cards && cards.length > 0 && (
          <ul aria-label="Cards do carrossel" className="flex gap-2 overflow-x-auto pb-1">
            {cards.map((card) => (
              <li
                key={card.id}
                className="w-[172px] shrink-0 overflow-hidden rounded-[7.5px] bg-white shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]"
              >
                <div aria-hidden="true" className="flex h-[72px] items-center justify-center bg-[#d9d2c8] text-[10px] text-[#5b5751]">
                  foto · {card.id}
                </div>
                <p className="whitespace-pre-wrap break-words px-2 py-1.5 text-[12px] leading-[16px] text-[#111b21]">
                  {!card.corpo.trim() && <span className="italic text-[#667781]">(sem texto)</span>}
                  {fragmentarMarcadores(card.corpo, MARCADOR_V2).map((pedaco, indice) =>
                    pedaco.marcador ? (
                      <span key={indice} className="border-b border-dashed border-[#667781] text-[#667781]">
                        {pedaco.texto}
                      </span>
                    ) : (
                      pedaco.texto
                    ),
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}

        {/* A folha que abre ao tocar: numa lista são os botões do nó; num desfecho de
            adiamento são os 30/60/90 do código. Sem ela, editar o rótulo de uma linha
            de lista não mudaria nada visível. */}
        {linhas.length > 0 && !comBotoes && (
          <div className="overflow-hidden rounded-[8px] border border-[rgba(0,0,0,0.08)] bg-white">
            <p className="border-b border-[rgba(0,0,0,0.06)] px-2.5 py-1.5 text-[11px] uppercase tracking-[0.5px] text-[#667781]">
              A folha que abre ao tocar
            </p>
            <ul>
              {linhas.map((linha) => (
                <li key={linha.id} className="border-b border-[rgba(0,0,0,0.06)] px-2.5 py-1.5 last:border-b-0">
                  <p className="text-[14px] leading-[18px] text-[#111b21]">
                    {linha.rotulo.trim() ? linha.rotulo : <span className="italic text-[#667781]">(sem texto)</span>}
                  </p>
                  {linha.descricao && <p className="text-[12px] leading-[16px] text-[#667781]">{linha.descricao}</p>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {(temMarcador || nota) && (
        <div className="space-y-1 border-t border-[#dedbd6] bg-[#faf9f6] px-2.5 py-1.5">
          {temMarcador && notaMarcador && <p className="text-[10px] leading-[14px] text-[#7b7b78]">{notaMarcador}</p>}
          {temMarcador && !notaMarcador && (
            <p className="text-[10px] leading-[14px] text-[#7b7b78]">
              A linha com <code className="rounded-[3px] bg-white px-1">{"{marcador}"}</code> é CORTADA do envio quando o
              valor não existe — o lead não lê o marcador, lê uma mensagem sem aquela linha.
            </p>
          )}
          {nota && <p className="text-[10px] leading-[14px] text-[#7b7b78]">{nota}</p>}
        </div>
      )}
    </figure>
  );
}

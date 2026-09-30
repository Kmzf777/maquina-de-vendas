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
 */

import { useMemo, useState } from "react";
import type {
  BotaoFluxo,
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
} from "./valeria-flow-types";

// ═════════════════════════════════════════════════════════════════════════════════
// Constantes — as duas chaves reservadas e o marcador de corpo
// ═════════════════════════════════════════════════════════════════════════════════

/** `reg.CHAVE_NUDGE`. */
export const CHAVE_NUDGE = "__nudge__";
/** `reg.CHAVE_ROTULO_LISTA`. */
export const CHAVE_ROTULO_LISTA = "__rotulo_lista__";

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
  grupos.push({
    chave: "textos",
    rotulo: "Textos soltos",
    descricao: "Texto que o lead lê e que não pertence a tela nenhuma",
    itens: [dados.nudge, dados.rotulo_lista],
  });

  return grupos.filter((grupo) => grupo.itens.length > 0);
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
      problemas.push({ campo: "corpo", mensagem: "o corpo do nudge não pode ficar vazio" });
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

/** Quebra o texto em pedaços, marcando os `{marcadores}` — a prévia os destaca. */
export function fragmentarMarcadores(texto: string): { texto: string; marcador: boolean }[] {
  const pedacos: { texto: string; marcador: boolean }[] = [];
  let ultimo = 0;
  for (const achado of texto.matchAll(MARCADOR)) {
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
  async function aoSalvar() {
    if (!patch || problemas.length || salvando) return;
    const salvo = await salvar(item.id, patch);
    if (salvo) descartar(item.id);
  }

  async function aoRestaurar() {
    if (salvando) return;
    const restaurado = await restaurar(item.id);
    if (restaurado) descartar(item.id);
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
                if (candidato.chave !== grupo.chave) setSelecionadoId(candidato.itens[0].id);
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
          const naoSalvo = Boolean(patchDoItem(candidato, rascunhos[candidato.id]));
          return (
            <button
              key={candidato.id}
              type="button"
              aria-current={ativo ? "true" : undefined}
              onClick={() => setSelecionadoId(candidato.id)}
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

            {erro && <span className="basis-full text-[11px] text-[#a4261b]">{erro}</span>}
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
  if (ehRotuloLista(item)) return "Rótulo do botão que abre a folha";
  return "Texto do reoferecimento";
}

function explicacaoDoItem(item: ItemFluxo, dados: FluxoResposta): string {
  if (item.tipo === "no") {
    if (item.tela === "lista")
      return `Tela de lista: o corpo, o botão que abre a folha e até ${dados.limites.max_linhas_lista} linhas — cada linha aceita ${dados.limites.titulo_lista} caracteres.`;
    if (item.tela === "foto_botoes")
      return `Foto no cabeçalho + até ${dados.limites.max_botoes} botões de ${dados.limites.rotulo_botao} caracteres.`;
    return `Até ${dados.limites.max_botoes} botões de resposta, de ${dados.limites.rotulo_botao} caracteres cada.`;
  }
  if (item.tipo === "terminal") return "Desfecho: o que a ValerIA faz quando a conversa chega aqui.";
  if (ehRotuloLista(item)) return "O botão azul que abre a folha de opções nas telas de lista.";
  return "O reoferecimento que o motor manda quando o lead não toca em nada.";
}

function Contador({ atual, limite, ruim }: { atual: number; limite: number | null; ruim: boolean }) {
  return (
    <span className={`shrink-0 text-[11px] tabular-nums ${ruim ? "font-medium text-[#a4261b]" : "text-[#7b7b78]"}`}>
      {limite === null ? `${atual} caracteres` : `${atual}/${limite}`}
    </span>
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
  const rotuloLista = corpoEfetivo(dados.rotulo_lista, rascunhos[dados.rotulo_lista.id]);

  if (item.tipo === "no") {
    return (
      <PreviaWhatsApp
        corpo={corpo}
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
export function PreviaWhatsApp({ corpo, tela, linhas, foto, rotuloLista, mudo, legenda, nota }: PreviaProps) {
  // Pela MESMA função que a bolha usa: um `MARCADOR.test()` aqui mexeria no
  // `lastIndex` de um regex `/g` compartilhado e faria a segunda chamada mentir.
  const pedacos = fragmentarMarcadores(corpo);
  const temMarcador = pedacos.some((pedaco) => pedaco.marcador);

  const comBotoes = tela === "botoes" || tela === "foto_botoes";
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
          {temMarcador && (
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

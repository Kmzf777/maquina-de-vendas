"use client";

/**
 * A CASCA do modal "ValerIA de Botões" — as duas abas, o carregamento e o estado
 * compartilhado. Aberto de `/campanhas`, ao lado de `ValeriaScoreModal`.
 *
 * O que mora aqui e por quê:
 *
 *   • O `GET /api/valeria-flow` UMA vez por abertura. A resposta já vem com os
 *     overrides mesclados (o servidor mescla, não a tela — cabeçalho de
 *     `backend/app/button_flow/valeria_flow_router.py`), então a casca só a guarda.
 *
 *   • UMA implementação de gravação (`gravarConteudo`), servida aos dois painéis por
 *     props. Duas telas com dois `fetch` próprios divergiriam na leitura do erro, e o
 *     erro é o único conteúdo acionável que o backend devolve.
 *
 *   • A MENSAGEM DO BACKEND, LITERAL. `validar` recusa com textos escritos para o
 *     operador ("o rótulo do botão de lista não pode ficar vazio", "a migration
 *     20260929_valeria_botoes.sql ainda não foi aplicada neste banco"). Trocá-los por
 *     "Erro ao salvar" apagaria a única informação que diz o que fazer — e o 503 da
 *     migration pendente é justamente o estado atual do banco.
 *
 * ── Por que a mensagem sai de `detail`, e não de `error` ────────────────────────
 * As rotas de `/api/valeria-flow` são proxy puro (mesmo desenho de
 * `src/app/api/campaigns/[id]/activate/route.ts`: "status e corpo do upstream são
 * repassados sem tradução"), então o que chega à tela é o `{"detail": "..."}` do
 * FastAPI, não `{"error": "..."}`. É o bug que `cadence-card.test.tsx` documenta ter
 * fechado: ler só `data.error` fazia o operador ver "Bad Request" em vez do motivo.
 * `mensagemDeErro` cobre as duas chaves para não depender dessa escolha do proxy. Ela
 * mora em `valeria-flow-shared.ts`, e não aqui, porque `valeria-flow-channels.tsx`
 * também a lê e esta casca importa aquele painel: o cabeçalho do módulo compartilhado
 * conta o ciclo de módulos que a mudança desfez.
 *
 * ── Por que os painéis recebem props, e não montam o próprio estado ─────────────
 * O contrato dos dois está declarado em `valeria-flow-types.ts` (`PainelFluxoProps`,
 * `PainelCanaisProps`) e é montado abaixo, em `propsFluxo`/`propsCanais`. Os dados, a
 * gravação e a faixa de erro são desta casca; os painéis escolhem o que editar e
 * desenham. `ValeriaFlowChannels` é a exceção declarada: os canais não vêm no `GET` do
 * fluxo, então ele busca os próprios (`GET /api/valeria-flow/channels`) e daqui recebe
 * só o `flow_id`.
 *
 * ── Por que o painel de Fluxo fica MONTADO e só escondido ───────────────────────
 * O que o operador digitou e ainda não gravou mora no estado LOCAL do editor
 * (`rascunhos`, em `valeria-flow-editor.tsx` — é dele que sai o "· não salvo" na lista
 * de telas). Enquanto a casca renderizava um painel por vez, trocar de aba desmontava o
 * editor e apagava esse rascunho EM SILÊNCIO: digitar o corpo de uma tela, ir conferir
 * em "Onde está ativo" qual número atende, voltar — e o texto não estava mais lá. São 17
 * telas; o operador tropeça nisso em minutos.
 *
 * Então o painel de Fluxo é renderizado SEMPRE e apenas escondido com o atributo
 * `hidden` (o preflight do Tailwind o resolve com `display:none!important`): o React
 * preserva o estado de um componente que continua montado, e não há rascunho a perder.
 * A outra saída possível — avisar antes de sair da aba — custaria um diálogo novo e um
 * passo a mais numa troca que o operador faz o tempo todo, para proteger um dado que
 * simplesmente não precisa ser descartado. `window.confirm` não serviria: neste ambiente
 * ele não faz nada.
 *
 * O painel de canais continua montando SÓ com a aba aberta, de propósito: ele busca os
 * próprios dados no `useEffect` de montagem, e montá-lo escondido dispararia um
 * `GET /api/valeria-flow/channels` que ninguém pediu. Ele também não tem o que proteger
 * — ali não se digita rascunho, cada clique grava na hora.
 *
 * `hidden` tira o elemento da árvore de acessibilidade, então continua havendo UM
 * `tabpanel` por vez para o leitor de tela. Duas consequências ficam amarradas abaixo:
 * `aria-controls` só aponta para painel que está no DOM (`doisPaineis`), e o laço de
 * foco ignora o que está dentro de `[hidden]`.
 *
 * ── O seletor de versão (v1 · v2 vitrine) ───────────────────────────────────────
 * O mesmo router serve as duas versões (contrato C7 do plano
 * `2026-10-08-valeria-botoes-v2-vitrine.md`): toda rota aceita `?flow_id=`. A v1 é o
 * default e continua batendo nas URLs de SEMPRE, sem query — é o que deixa a v1 igual
 * a antes do seletor. A v2 manda `?flow_id=valeria_botoes_v2` no `GET`, no `PUT`, no
 * `DELETE` e na aba de canais, e `flow_id` no corpo da ativação.
 *
 * Trocar de versão segue a mesma regra de trocar de aba: NÃO apaga rascunho. Cada
 * versão carregada nesta abertura guarda os seus dados e o seu editor, montado e
 * escondido com `hidden` quando a outra está à vista — o `GET` de uma versão é feito
 * uma vez por abertura, como antes. A estrutura do JSX abaixo é estável de propósito
 * (o contêiner dos editores fica sempre na mesma posição, só os atributos mudam): é
 * isso que faz o React PRESERVAR o estado dos editores enquanto a outra versão carrega.
 *
 * A resposta cujo `flow_id` não é o pedido vira erro na faixa, e não editor. Não é a
 * corrida de "resposta velha depois da troca de versão" — essa já está fechada pelo
 * `AbortController` e pelo `pedido` capturado no efeito, que arquiva cada resposta na
 * versão que a pediu. É o deploy: frontend e API sobem em containers separados, e na
 * janela em que o frontend novo fala com a API velha, ela IGNORA `?flow_id=` no `GET` e
 * no `PUT`. Sem esta trava a tela mostraria a v1 com o rótulo "v2", e cada "Salvar"
 * gravaria em cima do texto da v1 que está em produção. Mesma coisa se um proxy voltar
 * a perder a query (era o estado das rotas do Next antes deste seletor).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CardFluxo,
  ConteudoUpdate,
  FlowIdValeria,
  FluxoResposta,
  ItemFluxo,
  ItemGravado,
  PainelCanaisProps,
  PainelFluxoProps,
} from "./valeria-flow-types";
import { FLOW_V1, VERSOES, mensagemDeErro, queryDoFluxo } from "./valeria-flow-shared";
import { ValeriaFlowChannels } from "./valeria-flow-channels";
import { ValeriaFlowEditor } from "./valeria-flow-editor";

type Aba = "fluxo" | "canais";
const ABAS: { chave: Aba; rotulo: string; descricao: string }[] = [
  { chave: "fluxo", rotulo: "Fluxo", descricao: "Texto das telas e rótulos dos botões" },
  { chave: "canais", rotulo: "Onde está ativo", descricao: "Qual número atende por este fluxo" },
];

/**
 * Recoloca no lugar o item que o `PUT`/`DELETE` devolveu.
 *
 * O backend responde com `_item_json` — o item já mesclado —, então a tela substitui
 * em vez de remontar o que acha que gravou: o `rotulos` é MERGE no servidor, e um
 * otimismo local perderia os rótulos dos outros botões do mesmo nó.
 *
 * O casamento é por `id`, que os três serializadores emitem (os reservados emitem
 * `chave` E `id`, com o mesmo valor).
 */
export function aplicarItem(dados: FluxoResposta, item: ItemFluxo): FluxoResposta {
  if (item.tipo === "no") {
    return { ...dados, nos: dados.nos.map((no) => (no.id === item.id ? item : no)) };
  }
  if (item.tipo === "terminal") {
    return {
      ...dados,
      terminais: dados.terminais.map((t) => (t.id === item.id ? item : t)),
    };
  }
  if (item.id === dados.nudge?.id) return { ...dados, nudge: item };
  if (item.id === dados.rotulo_lista?.id) return { ...dados, rotulo_lista: item };
  return dados;
}

/**
 * Recoloca no lugar o que um `PUT`/`DELETE` de `nodeId` devolveu — inclusive o que só a
 * v2 tem (contrato C7):
 *
 *   • `card:<nó>:<id>` (a chave canônica, a que o editor manda) ou o atalho
 *     `card:<id>`: o card daquela vitrine — ou, no atalho, de toda vitrine com aquele
 *     id. Quando a resposta é o `_card_json` (`tipo: "card"`), ela substitui o card
 *     inteiro, com o `editado` do servidor.
 *   • uma chave de `textos`: o texto daquela chave.
 *
 * Fora o `_card_json`, daqui se lê só `corpo`, `corpo_default` e `editado`, com o
 * `patch` enviado (ou o default, num `DELETE`) como reserva. O resto continua indo por
 * `aplicarItem`, inclusive quando a chave de `textos` é também o nudge ou o botão de
 * lista.
 */
export function aplicarGravacao(
  dados: FluxoResposta,
  nodeId: string,
  resposta: unknown,
  patch: ConteudoUpdate | null,
): FluxoResposta {
  const corpo = resposta as { corpo?: unknown; corpo_default?: unknown; tipo?: unknown; editado?: unknown } | null;
  const novo = <T extends { corpo: string; corpo_default: string; editado?: boolean }>(atual: T): T => {
    const padrao = typeof corpo?.corpo_default === "string" ? corpo.corpo_default : atual.corpo_default;
    const texto = typeof corpo?.corpo === "string" ? corpo.corpo : patch?.corpo ?? padrao;
    const editado = typeof corpo?.editado === "boolean" ? corpo.editado : texto !== padrao;
    return { ...atual, corpo: texto, corpo_default: padrao, editado };
  };

  if (nodeId.startsWith("card:")) {
    // `card:VA:classico` → nó VA, card classico; `card:classico` → qualquer nó.
    const resto = nodeId.slice("card:".length);
    const corte = resto.lastIndexOf(":");
    const noId = corte >= 0 ? resto.slice(0, corte) : null;
    const cardId = corte >= 0 ? resto.slice(corte + 1) : resto;
    const doServidor = corpo?.tipo === "card" ? (corpo as unknown as CardFluxo) : null;
    const trocar = (card: CardFluxo) => (card.id !== cardId ? card : doServidor ? { ...card, ...doServidor } : novo(card));
    return {
      ...dados,
      nos: dados.nos.map((no) =>
        (noId === null || no.id === noId) && no.cards?.some((card) => card.id === cardId)
          ? { ...no, cards: no.cards.map(trocar) }
          : no,
      ),
    };
  }

  let base = dados;
  if (dados.textos?.some((texto) => texto.chave === nodeId)) {
    base = { ...dados, textos: dados.textos.map((texto) => (texto.chave === nodeId ? novo(texto) : texto)) };
  }
  if (corpo && typeof corpo.tipo === "string") return aplicarItem(base, corpo as unknown as ItemFluxo);
  return base;
}

type Gravacao = { item: ItemGravado; erro: null } | { item: null; erro: string };

/**
 * `PUT /api/valeria-flow/{node_id}` — a ÚNICA gravação de conteúdo da tela.
 *
 * Nunca rejeita: devolve `{item}` ou `{erro}`. Um painel que esquecesse o `catch`
 * derrubaria o modal inteiro em cima do operador, e o 503 da migration pendente é um
 * caminho esperado, não excepcional.
 *
 * Os status que o router produz, todos com texto próprio: 400 (rótulo passou do
 * limite da Meta, corpo vazio, rótulo em item sem botões), 404 (nó fora do registry),
 * 503 (não conseguiu LER `rotulos_antigos` antes de gravar — fail-CLOSED de
 * propósito) e 403 (a rota inteira é `require_role(["admin"])`).
 */
export async function gravarConteudo(nodeId: string, patch: ConteudoUpdate, flowId: FlowIdValeria = FLOW_V1): Promise<Gravacao> {
  return enviar(urlDoItem(nodeId, flowId), "PUT", patch, "Não foi possível salvar este texto.");
}

/** `DELETE /api/valeria-flow/{node_id}` — volta ao default do registry. */
export async function restaurarConteudo(nodeId: string, flowId: FlowIdValeria = FLOW_V1): Promise<Gravacao> {
  return enviar(urlDoItem(nodeId, flowId), "DELETE", null, "Não foi possível restaurar este texto.");
}

/** `card:classico` e `faq:atacado:frete` levam `:` — `encodeURIComponent` os protege. */
function urlDoItem(nodeId: string, flowId: FlowIdValeria): string {
  return `/api/valeria-flow/${encodeURIComponent(nodeId)}${queryDoFluxo(flowId)}`;
}

async function enviar(url: string, method: string, corpo: ConteudoUpdate | null, padrao: string): Promise<Gravacao> {
  let resposta: Response;
  try {
    resposta = await fetch(url, {
      method,
      headers: corpo ? { "Content-Type": "application/json" } : undefined,
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
  } catch {
    return { item: null, erro: padrao };
  }
  const json = await resposta.json().catch(() => ({}));
  if (!resposta.ok) return { item: null, erro: mensagemDeErro(json, padrao) };
  return { item: json as ItemGravado, erro: null };
}

export function ValeriaFlowModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [aba, setAba] = useState<Aba>("fluxo"); const [carregando, setCarregando] = useState(true);
  // A versão à vista e os dados de CADA versão já carregada nesta abertura (cabeçalho:
  // trocar de versão não pode apagar o rascunho da outra).
  const [flowId, setFlowId] = useState<FlowIdValeria>(FLOW_V1); const [porFluxo, setPorFluxo] = useState<Partial<Record<FlowIdValeria, FluxoResposta>>>({}); const [erro, setErro] = useState<string | null>(null); const [salvando, setSalvando] = useState<string | null>(null);
  const dialog = useRef<HTMLElement>(null); const fechar = useRef<HTMLButtonElement>(null); const abridor = useRef<HTMLElement | null>(null);

  const dados = porFluxo[flowId] ?? null;
  const jaCarregado = Boolean(dados);

  // Fechar esquece o que foi carregado: o `GET` é por ABERTURA, e quem reabre vê o que
  // está no banco agora, não o que viu da última vez.
  useEffect(() => {
    if (open) return;
    setPorFluxo((atual) => (Object.keys(atual).length ? {} : atual));
    // Reabrir começa carregando, e não no "Nada a editar" de um quadro antes do `GET`.
    setCarregando(true);
  }, [open]);

  // O `GET` uma vez por abertura E por versão. `AbortController` porque o operador pode
  // fechar o modal (ou trocar de versão) antes da resposta, e um `setState` depois disso
  // escreveria a resposta de uma versão em cima da outra.
  useEffect(() => {
    if (!open || jaCarregado) return;
    const controller = new AbortController();
    const pedido = flowId;
    setCarregando(true); setErro(null);
    fetch(`/api/valeria-flow${queryDoFluxo(pedido)}`, { signal: controller.signal, cache: "no-store" })
      .then(async (r) => { const json = await r.json().catch(() => ({})); if (!r.ok) throw new Error(mensagemDeErro(json, "Não foi possível carregar o fluxo de botões.")); return json as FluxoResposta; })
      .then((json) => {
        // A API ignorou `?flow_id=` (deploy pela metade, proxy sem a query): editar isto
        // como v2 gravaria em cima da v1 de produção. Cabeçalho do módulo.
        if (pedido !== FLOW_V1 && json.flow_id !== pedido) throw new Error(`O backend respondeu o fluxo ${json.flow_id ?? "(sem flow_id)"} quando foi pedido ${pedido}: ele ainda não serve esta versão.`);
        setPorFluxo((atual) => ({ ...atual, [pedido]: json })); setErro(null); setCarregando(false);
      })
      .catch((motivo: unknown) => { if (motivo instanceof Error && motivo.name === "AbortError") return; setCarregando(false); setErro(motivo instanceof Error ? motivo.message : "Não foi possível carregar o fluxo de botões."); });
    return () => controller.abort();
  }, [open, flowId, jaCarregado]);

  // Escape fecha, Tab circula dentro do diálogo, e o foco volta a quem abriu.
  useEffect(() => {
    if (!open) return;
    abridor.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    fechar.current?.focus();
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") { evento.preventDefault(); onClose(); return; }
      if (evento.key !== "Tab" || !dialog.current) return;
      // Fora o que está dentro de `[hidden]`: o painel de Fluxo continua montado com a
      // outra aba aberta, e o navegador não dá foco a `display:none`. Se um desses
      // elementos fosse o primeiro ou o último da lista, a volta do laço compararia
      // `activeElement` com algo que nunca pode estar focado — e o Tab escaparia do
      // diálogo.
      const focaveis = [...dialog.current.querySelectorAll<HTMLElement>("button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]")].filter(
        (alvo) => !alvo.closest("[hidden]"),
      );
      if (!focaveis.length) return;
      if (evento.shiftKey && document.activeElement === focaveis[0]) { evento.preventDefault(); focaveis.at(-1)?.focus(); }
      else if (!evento.shiftKey && document.activeElement === focaveis.at(-1)) { evento.preventDefault(); focaveis[0].focus(); }
    };
    document.addEventListener("keydown", aoTeclar);
    return () => { document.removeEventListener("keydown", aoTeclar); abridor.current?.focus(); };
  }, [open, onClose]);

  // UMA gravação para as duas versões: a versão vai na URL e o resultado volta para os
  // dados DAQUELA versão — a que estava à vista quando o operador clicou, não a de agora.
  const gravar = useCallback(async (alvo: FlowIdValeria, nodeId: string, patch: ConteudoUpdate | null): Promise<ItemGravado | null> => {
    setSalvando(nodeId); setErro(null);
    try {
      const { item, erro: recusa } = patch ? await gravarConteudo(nodeId, patch, alvo) : await restaurarConteudo(nodeId, alvo);
      if (!item) { setErro(recusa); return null; }
      setPorFluxo((atual) => { const dadosAlvo = atual[alvo]; return dadosAlvo ? { ...atual, [alvo]: aplicarGravacao(dadosAlvo, nodeId, item, patch) } : atual; });
      return item;
    } finally { setSalvando(null); }
  }, []);

  // Memoizadas por versão porque descem por props: um painel que memoize por referência
  // re-renderizaria a cada teclada do operador sem isto.
  const acoes = useMemo(
    () => Object.fromEntries(VERSOES.map(({ id }) => [id, {
      salvar: ((nodeId, patch) => gravar(id, nodeId, patch)) as PainelFluxoProps["salvar"],
      restaurar: ((nodeId) => gravar(id, nodeId, null)) as PainelFluxoProps["restaurar"],
    }])) as Record<FlowIdValeria, Pick<PainelFluxoProps, "salvar" | "restaurar">>,
    [gravar],
  );

  if (!open) return null;

  const propsFluxo = (alvo: FlowIdValeria): PainelFluxoProps | null => { const d = porFluxo[alvo]; return d ? { dados: d, ...acoes[alvo], salvando, erro } : null; };
  const propsCanais: PainelCanaisProps | null = dados ? { flowId } : null;

  const trocarVersao = (alvo: FlowIdValeria) => { if (alvo === flowId || salvando) return; setErro(null); setFlowId(alvo); };

  // Com dados na mão existem DOIS `tabpanel` no DOM (o de Fluxo escondido quando a outra
  // aba está aberta), e aí cada aba pode declarar o `aria-controls` dela. Carregando ou
  // sem dados existe UM só, o da aba aberta — e apontar `aria-controls` para um id
  // ausente é referência morta para o leitor de tela (defeito que um review já fechou).
  // `carregando` não entra: um `GET` da v2 abortado pela volta à v1 o deixa ligado, e
  // com os dados da versão à vista os dois painéis existem de qualquer jeito.
  const doisPaineis = Boolean(dados);

  const trocarAba = (evento: React.KeyboardEvent) => {
    const passo = evento.key === "ArrowRight" ? 1 : evento.key === "ArrowLeft" ? -1 : 0;
    if (!passo) return;
    evento.preventDefault();
    const indice = ABAS.findIndex((a) => a.chave === aba);
    const proxima = ABAS[(indice + passo + ABAS.length) % ABAS.length];
    setAba(proxima.chave);
    dialog.current?.querySelector<HTMLElement>(`#aba-${proxima.chave}`)?.focus();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#111111]/30 p-3 sm:p-4" onClick={() => !salvando && onClose()}>
      <section
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="valeria-flow-titulo"
        className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[8px] border border-[#dedbd6] bg-white shadow-[0_12px_40px_-12px_rgba(17,17,17,0.25)]"
        onClick={(evento) => evento.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-[#dedbd6] px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 id="valeria-flow-titulo" className="text-[16px] font-semibold tracking-tight text-[#111111]">
              ValerIA de Botões
            </h2>
            <p className="mt-0.5 text-[12px] text-[#7b7b78]">
              O texto que o lead lê em cada tela. Quem existe e para onde cada botão leva é código.
            </p>
          </div>
          <button
            ref={fechar}
            type="button"
            onClick={onClose}
            disabled={Boolean(salvando)}
            aria-label="Fechar ValerIA de Botões"
            className="-mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] text-[18px] leading-none text-[#7b7b78] transition-colors hover:bg-[#faf9f6] hover:text-[#111111] disabled:opacity-40"
          >
            ×
          </button>
        </header>

        <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 border-b border-[#dedbd6] bg-[#faf9f6] px-4 sm:px-5">
        <div role="tablist" aria-label="Seções da ValerIA de Botões" onKeyDown={trocarAba} className="flex gap-1">
          {ABAS.map(({ chave, rotulo, descricao }) => (
            <button
              key={chave}
              id={`aba-${chave}`}
              type="button"
              role="tab"
              aria-selected={aba === chave}
              aria-controls={doisPaineis || aba === chave ? `painel-${chave}` : undefined}
              tabIndex={aba === chave ? 0 : -1}
              title={descricao}
              onClick={() => setAba(chave)}
              className={`-mb-px border-b-2 px-2 py-2.5 text-[13px] transition-colors ${aba === chave ? "border-[#111111] text-[#111111]" : "border-transparent text-[#7b7b78] hover:text-[#111111]"}`}
            >
              {rotulo}
            </button>
          ))}
        </div>

        {/* A versão. Fora do `tablist` de propósito: as setas de lá trocam ABA, e um
            grupo de rádio dentro de uma lista de abas é árvore inválida para o leitor
            de tela. Travado durante a gravação: o resultado volta para a versão que
            estava à vista no clique. */}
        <div role="radiogroup" aria-label="Versão do fluxo" className="flex items-center gap-1.5 py-1.5 text-[12px]">
          <span aria-hidden="true" className="text-[#7b7b78]">Versão:</span>
          <div className="flex rounded-[6px] border border-[#dedbd6] bg-white p-0.5">
            {VERSOES.map(({ id, rotulo, descricao }) => (
              <button
                key={id}
                type="button"
                role="radio"
                aria-checked={flowId === id}
                title={descricao}
                disabled={Boolean(salvando)}
                onClick={() => trocarVersao(id)}
                className={`rounded-[4px] px-2 py-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${flowId === id ? "bg-[#111111] text-white" : "text-[#7b7b78] hover:text-[#111111]"}`}
              >
                {rotulo}
              </button>
            ))}
          </div>
        </div>
        </div>

        {/* Uma faixa de erro para os dois painéis, com a mensagem do backend literal. */}
        {erro && (
          <p role="alert" className="shrink-0 border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-2.5 text-[13px] text-[#a4261b] sm:px-5">
            {erro}
          </p>
        )}

        {/* A rolagem é do contêiner; o painel escondido sai do fluxo de layout. */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {/* Sem os dados da versão à vista: o esqueleto (carregando) ou o vazio (a faixa
              acima já diz por quê). */}
          {!dados && (carregando ? (
            <div id={`painel-${aba}`} role="tabpanel" aria-labelledby={`aba-${aba}`} className="space-y-2 px-4 py-4 sm:px-5" aria-busy="true">
              <p className="text-[13px] text-[#7b7b78]">Carregando o fluxo…</p>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-[6px] bg-[#dedbd6]/30" />
              ))}
            </div>
          ) : (
            <p id={`painel-${aba}`} role="tabpanel" aria-labelledby={`aba-${aba}`} className="px-5 py-12 text-center text-[13px] text-[#7b7b78]">
              Nada a editar por enquanto.
            </p>
          ))}

          {/* Montado sempre e só escondido: é aqui que vive o rascunho do operador
              (cabeçalho do módulo) — de CADA versão já carregada. O contêiner fica nesta
              posição mesmo sem dados à vista (só perde `id`/`role`, para não duplicar o
              `tabpanel` do esqueleto): é isso que mantém os editores montados enquanto a
              outra versão carrega. Sem classe de `display` para que o
              `display:none!important` do `hidden` não dispute com nada. */}
          <div
            id={dados ? "painel-fluxo" : undefined}
            role={dados ? "tabpanel" : undefined}
            aria-labelledby={dados ? "aba-fluxo" : undefined}
            hidden={!dados || aba !== "fluxo"}
          >
            {VERSOES.map(({ id }) => {
              const props = propsFluxo(id);
              return props ? (
                <div key={id} hidden={id !== flowId}>
                  <ValeriaFlowEditor {...props} />
                </div>
              ) : null;
            })}
          </div>

          {/* O contrário: o painel de canais só entra com a aba aberta, porque montá-lo
              escondido dispararia o `GET /channels` que ninguém pediu. O `tabpanel` fica,
              vazio, para o `aria-controls` da aba ter destino. `key` pela versão: trocar
              de versão é outra lista (quem atende por ESTA versão), buscada de novo. */}
          {propsCanais && (
            <div id="painel-canais" role="tabpanel" aria-labelledby="aba-canais" hidden={aba !== "canais"}>
              {aba === "canais" && <ValeriaFlowChannels key={flowId} {...propsCanais} />}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

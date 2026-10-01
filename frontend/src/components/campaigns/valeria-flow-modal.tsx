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
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ConteudoUpdate,
  FluxoResposta,
  ItemFluxo,
  PainelCanaisProps,
  PainelFluxoProps,
} from "./valeria-flow-types";
import { mensagemDeErro } from "./valeria-flow-shared";
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
  if (item.id === dados.nudge.id) return { ...dados, nudge: item };
  if (item.id === dados.rotulo_lista.id) return { ...dados, rotulo_lista: item };
  return dados;
}

type Gravacao = { item: ItemFluxo; erro: null } | { item: null; erro: string };

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
export async function gravarConteudo(nodeId: string, patch: ConteudoUpdate): Promise<Gravacao> {
  return enviar(`/api/valeria-flow/${encodeURIComponent(nodeId)}`, "PUT", patch, "Não foi possível salvar este texto.");
}

/** `DELETE /api/valeria-flow/{node_id}` — volta ao default do registry. */
export async function restaurarConteudo(nodeId: string): Promise<Gravacao> {
  return enviar(`/api/valeria-flow/${encodeURIComponent(nodeId)}`, "DELETE", null, "Não foi possível restaurar este texto.");
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
  return { item: json as ItemFluxo, erro: null };
}

export function ValeriaFlowModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [aba, setAba] = useState<Aba>("fluxo"); const [dados, setDados] = useState<FluxoResposta | null>(null); const [carregando, setCarregando] = useState(true); const [erro, setErro] = useState<string | null>(null); const [salvando, setSalvando] = useState<string | null>(null);
  const dialog = useRef<HTMLElement>(null); const fechar = useRef<HTMLButtonElement>(null); const abridor = useRef<HTMLElement | null>(null);

  // O `GET` uma vez por abertura. `AbortController` porque o operador pode fechar o
  // modal antes da resposta, e um `setDados` depois disso avisa em cima de um
  // componente desmontado.
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setCarregando(true); setErro(null);
    fetch("/api/valeria-flow", { signal: controller.signal, cache: "no-store" })
      .then(async (r) => { const json = await r.json().catch(() => ({})); if (!r.ok) throw new Error(mensagemDeErro(json, "Não foi possível carregar o fluxo de botões.")); return json as FluxoResposta; })
      .then((json) => { setDados(json); setErro(null); setCarregando(false); })
      .catch((motivo: unknown) => { if (motivo instanceof Error && motivo.name === "AbortError") return; setCarregando(false); setErro(motivo instanceof Error ? motivo.message : "Não foi possível carregar o fluxo de botões."); });
    return () => controller.abort();
  }, [open]);

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

  // `useCallback` porque estas duas descem por props: um painel que memoize por
  // referência re-renderizaria a cada teclada do operador sem isto.
  const salvar = useCallback<PainelFluxoProps["salvar"]>(async (nodeId, patch) => {
    setSalvando(nodeId); setErro(null);
    try {
      const { item, erro: recusa } = await gravarConteudo(nodeId, patch);
      if (!item) { setErro(recusa); return null; }
      setDados((atual) => (atual ? aplicarItem(atual, item) : atual));
      return item;
    } finally { setSalvando(null); }
  }, []);

  const restaurar = useCallback<PainelFluxoProps["restaurar"]>(async (nodeId) => {
    setSalvando(nodeId); setErro(null);
    try {
      const { item, erro: recusa } = await restaurarConteudo(nodeId);
      if (!item) { setErro(recusa); return null; }
      setDados((atual) => (atual ? aplicarItem(atual, item) : atual));
      return item;
    } finally { setSalvando(null); }
  }, []);

  if (!open) return null;

  const propsFluxo: PainelFluxoProps | null = dados ? { dados, salvar, restaurar, salvando, erro } : null;
  const propsCanais: PainelCanaisProps | null = dados ? { flowId: dados.flow_id } : null;

  // Com dados na mão existem DOIS `tabpanel` no DOM (o de Fluxo escondido quando a outra
  // aba está aberta), e aí cada aba pode declarar o `aria-controls` dela. Carregando ou
  // sem dados existe UM só, o da aba aberta — e apontar `aria-controls` para um id
  // ausente é referência morta para o leitor de tela (defeito que um review já fechou).
  const doisPaineis = !carregando && Boolean(propsFluxo && propsCanais);

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

        <div role="tablist" aria-label="Seções da ValerIA de Botões" onKeyDown={trocarAba} className="flex shrink-0 gap-1 border-b border-[#dedbd6] bg-[#faf9f6] px-4 sm:px-5">
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

        {/* Uma faixa de erro para os dois painéis, com a mensagem do backend literal. */}
        {erro && (
          <p role="alert" className="shrink-0 border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-2.5 text-[13px] text-[#a4261b] sm:px-5">
            {erro}
          </p>
        )}

        {/* A rolagem é do contêiner; o painel escondido sai do fluxo de layout. */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {carregando ? (
            <div id={`painel-${aba}`} role="tabpanel" aria-labelledby={`aba-${aba}`} className="space-y-2 px-4 py-4 sm:px-5" aria-busy="true">
              <p className="text-[13px] text-[#7b7b78]">Carregando o fluxo…</p>
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-[6px] bg-[#dedbd6]/30" />
              ))}
            </div>
          ) : !propsFluxo || !propsCanais ? (
            // Sem dados e sem carregar: a faixa acima já diz por quê.
            <p id={`painel-${aba}`} role="tabpanel" aria-labelledby={`aba-${aba}`} className="px-5 py-12 text-center text-[13px] text-[#7b7b78]">
              Nada a editar por enquanto.
            </p>
          ) : (
            <>
              {/* Montado sempre e só escondido: é aqui que vive o rascunho do operador
                  (cabeçalho do módulo). Sem classe de `display` para que o
                  `display:none!important` do `hidden` não dispute com nada. */}
              <div id="painel-fluxo" role="tabpanel" aria-labelledby="aba-fluxo" hidden={aba !== "fluxo"}>
                <ValeriaFlowEditor {...propsFluxo} />
              </div>
              {/* O contrário: o painel de canais só entra com a aba aberta, porque
                  montá-lo escondido dispararia o `GET /channels` que ninguém pediu. O
                  `tabpanel` fica, vazio, para o `aria-controls` da aba ter destino. */}
              <div id="painel-canais" role="tabpanel" aria-labelledby="aba-canais" hidden={aba !== "canais"}>
                {aba === "canais" && <ValeriaFlowChannels {...propsCanais} />}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

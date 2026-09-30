"use client";

/**
 * O painel da aba "Onde está ativo" do modal ValerIA de Botões.
 *
 * É a ação mais consequente da feature inteira: "Ativar" repõe um número de
 * WhatsApp VIVO da ValerIA com LLM para um roteiro de botões. Nada aqui é decorativo
 * — cada bloco de texto existe porque sem ele o operador toma uma decisão errada com
 * a informação certa escondida.
 *
 * ── Os dois fatos que esta tela existe para tornar visíveis ─────────────────────
 *
 * 1. PERFIL COMPARTILHADO. Verificado em produção em 09/09 e registrado no
 *    cabeçalho de `backend/app/button_flow/runner.py`: o canal do João (`a3a607b1`)
 *    já aponta para o MESMO `agent_profile_id` do canal da ValerIA (`674beb13`).
 *    Virar o `kind` daquele perfil para `button_flow` transformaria o número pessoal
 *    do vendedor em robô no mesmo instante. Por isso o `POST /activate` do backend
 *    só INSERE — cria um perfil novo e reaponta só o canal escolhido, e nenhuma rota
 *    daquele módulo faz UPDATE em `agent_profiles`. Quem olha dois canais na tela
 *    não tem como saber que eles estão acoplados: o `perfil_compartilhado` do `GET`
 *    é a única pista, e o aviso abaixo é a única forma de ela chegar a uma pessoa.
 *
 * 2. KILL SWITCH DESLIGADO. `flow_config.enabled("valeria_botoes_v1")` lê
 *    `VALERIA_BOTOES_ENABLED` do env a cada chamada, com default OFF, e a variável
 *    não está no `.env`. Então o estado normal HOJE é: ativar funciona, o canal passa
 *    a apontar para o fluxo, e nada acontece. Um operador que ative e não veja nada
 *    concluir que a feature está quebrada é o desfecho previsível — daí o `ligado:
 *    false` virar uma placa no topo do painel, e não uma nota de rodapé.
 *
 * ── Por que a confirmação é no painel, e não `window.confirm` ───────────────────
 * Diálogos nativos não funcionam neste ambiente, e mesmo onde funcionam um
 * `window.confirm` cabe uma frase — enquanto o que precisa ser lido antes do clique
 * são três: qual número, que a ValerIA com IA para de atender ali, e que os canais
 * irmãos NÃO são afetados. A confirmação troca o botão no lugar, na mesma coluna
 * visual do canal a que se refere.
 *
 * ── Por que relê a lista depois de ativar ──────────────────────────────────────
 * A ativação muda o agrupamento dos OUTROS canais: o canal ativado sai do perfil
 * compartilhado, e quem ficasse sozinho lá deixa de estar acoplado. Só o servidor
 * sabe o novo `perfil_compartilhado` de cada linha — deduzir localmente apagaria o
 * aviso de um canal que continua em risco, ou o manteria num que já saiu dele.
 *
 * ── Por que `mensagemDeErro` vem da casca ──────────────────────────────────────
 * O cabeçalho de `valeria-flow-modal.tsx` diz por quê: "Duas telas com dois `fetch`
 * próprios divergiriam na leitura do erro, e o erro é o único conteúdo acionável que
 * o backend devolve". Os textos que este painel pode receber são escritos para o
 * operador — "canal {id} não encontrado" (404), "informe o canal que vai atender pelo
 * fluxo de botões" (400) e o 503 que nomeia a migration `20260929_valeria_botoes.sql`,
 * que é o estado real do banco hoje. Todos aparecem VERBATIM.
 * A casca ainda não importa este painel, então hoje não há ciclo; quando ela importar,
 * o ciclo é benigno — `mensagemDeErro` é uma `function` declaration (hoisted) e este
 * módulo não a chama em tempo de avaliação, só dentro dos handlers.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PainelCanaisProps } from "./valeria-flow-types";
import { mensagemDeErro } from "./valeria-flow-modal";

// ═══════════════════════════════════════════════════════════════════════════════
// O contrato de GET /api/valeria-flow/channels
// ═══════════════════════════════════════════════════════════════════════════════
// Escrito lendo `api_get_canais` em `backend/app/button_flow/valeria_flow_router.py`,
// não a especificação. O router monta cada campo com `canal.get(...)` sobre uma linha
// de `channels` com o embed `agent_profiles(*)`, e as colunas `name`/`phone`/`mode`
// aceitam NULL no banco — então os opcionais abaixo são `| null` de propósito. Um tipo
// que prometesse `string` faria `canal.name.trim()` estourar em runtime na primeira
// linha sem nome, e o painel inteiro cairia em cima do operador.

/** O perfil de agente que o canal aponta hoje. `null` quando não aponta nenhum. */
export interface PerfilDoCanal {
  id: string | null;
  name: string | null;
  /** `perfil.get("kind") or "llm"` no router: nunca vazio. */
  kind: string;
  flow_id: string | null;
}

export interface CanalDoFluxo {
  id: string;
  name: string | null;
  phone: string | null;
  mode: string | null;
  is_active: boolean | null;
  agent_profile_id: string | null;
  perfil: PerfilDoCanal | null;
  /** True quando outro canal aponta para o MESMO `agent_profile_id`. */
  perfil_compartilhado: boolean;
  /** Nomes dos outros canais naquele perfil. Podem vir NULL — o router não filtra. */
  compartilhado_com: (string | null)[];
  atende_este_fluxo: boolean;
}

export interface CanaisResposta {
  flow_id: string;
  /** O kill switch DESTE fluxo (`VALERIA_BOTOES_ENABLED`), lido do env a cada `GET`. */
  ligado: boolean;
  canais: CanalDoFluxo[];
}

const PADRAO_CARREGAR = "Não foi possível carregar os canais.";
const PADRAO_ATIVAR = "Não foi possível ativar o fluxo de botões neste canal.";

// ═══════════════════════════════════════════════════════════════════════════════
// Texto
// ═══════════════════════════════════════════════════════════════════════════════

/** Um rótulo legível quando a coluna do banco vem NULL ou só com espaços. */
function nomeOu(valor: string | null | undefined, padrao: string): string {
  return (valor ?? "").trim() || padrao;
}

/**
 * Os nomes dos canais irmãos, sem os nulos.
 *
 * `perfil_compartilhado` é `bool(irmaos)` no router, e `irmaos` é uma lista de
 * `outro.get("name")` — um canal irmão sem nome entra na lista como `None` e acende o
 * aviso sem ter nome para citar. Nesse caso o aviso cai no plural genérico em vez de
 * escrever "compartilhado com " e parar no vazio.
 */
export function nomesIrmaos(canal: CanalDoFluxo): string[] {
  return (canal.compartilhado_com ?? [])
    .map((nome) => (typeof nome === "string" ? nome.trim() : ""))
    .filter((nome) => nome.length > 0);
}

/** "A", "A e B", "A, B e C" — a lista que o aviso de perfil compartilhado cita. */
export function listarNomes(nomes: string[]): string {
  if (nomes.length === 0) return "";
  if (nomes.length === 1) return nomes[0];
  return `${nomes.slice(0, -1).join(", ")} e ${nomes[nomes.length - 1]}`;
}

/** Como os irmãos são chamados na frase: os nomes, ou o genérico se vierem nulos. */
function citarIrmaos(nomes: string[], quantos: number): string {
  if (nomes.length > 0) return listarNomes(nomes);
  return quantos > 1 ? `outros ${quantos} canais` : "outro canal";
}

// ═══════════════════════════════════════════════════════════════════════════════
// Painel
// ═══════════════════════════════════════════════════════════════════════════════

export function ValeriaFlowChannels({ flowId }: PainelCanaisProps) {
  const [dados, setDados] = useState<CanaisResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  /** O canal cuja confirmação está aberta. Uma por vez. */
  const [confirmando, setConfirmando] = useState<string | null>(null);
  /** O canal com o `POST` em voo. Trava TODOS os botões, não só o dele. */
  const [ativando, setAtivando] = useState<string | null>(null);

  const carregar = useCallback(async (signal?: AbortSignal): Promise<CanaisResposta | null> => {
    setCarregando(true);
    try {
      const resposta = await fetch("/api/valeria-flow/channels", { signal, cache: "no-store" });
      const json = await resposta.json().catch(() => ({}));
      if (!resposta.ok) {
        setErro(mensagemDeErro(json, PADRAO_CARREGAR));
        return null;
      }
      const corpo = json as CanaisResposta;
      setDados(corpo);
      setErro(null);
      return corpo;
    } catch (motivo: unknown) {
      // Fechar o modal aborta o `GET`; não é erro do operador e não vira faixa.
      if ((motivo as Error | null)?.name === "AbortError") return null;
      setErro(PADRAO_CARREGAR);
      return null;
    } finally {
      if (!signal?.aborted) setCarregando(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void carregar(controller.signal);
    return () => controller.abort();
  }, [carregar]);

  async function ativar(canal: CanalDoFluxo) {
    const nome = nomeOu(canal.name, canal.id);
    setAtivando(canal.id);
    setErro(null);
    setSucesso(null);
    try {
      const resposta = await fetch("/api/valeria-flow/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: canal.id }),
      });
      const json = await resposta.json().catch(() => ({}));
      if (!resposta.ok) {
        // 400 / 404 / 503 (migration pendente) / 403 — todos com texto próprio,
        // escrito para quem vai agir. Verbatim.
        setErro(mensagemDeErro(json, PADRAO_ATIVAR));
        return;
      }
      setConfirmando(null);
      const atual = await carregar();
      const ligado = atual ? atual.ligado : Boolean((json as { ligado?: boolean }).ligado);
      setSucesso(
        ligado
          ? `${nome} passou a atender pela ValerIA de Botões. Um perfil de agente novo foi criado só para este canal; nenhum perfil existente foi alterado.`
          : `${nome} já aponta para o fluxo de botões, mas o fluxo continua DESLIGADO: nada será respondido por botões enquanto VALERIA_BOTOES_ENABLED não estiver ligada no ambiente do backend.`,
      );
    } catch {
      setErro(PADRAO_ATIVAR);
    } finally {
      setAtivando(null);
    }
  }

  const emVoo = ativando !== null;
  const canais = dados?.canais ?? [];
  const desligado = dados !== null && !dados.ligado;

  return (
    <div className="px-4 py-4 sm:px-5">
      {/* ── O kill switch. Placa, não nota de rodapé: é o estado do banco hoje. ── */}
      {desligado && (
        <section
          role="status"
          className="mb-4 rounded-[6px] border border-[#e8c65a] bg-[#fff8e0] px-3 py-3 sm:px-4"
        >
          <p className="text-[13px] font-semibold text-[#7a5a00]">
            O fluxo de botões está DESLIGADO
          </p>
          <p className="mt-1 text-[12px] leading-[1.5] text-[#7a5a00]">
            Ativar aponta o canal para este fluxo, mas nenhuma mensagem será respondida por
            botões enquanto{" "}
            <code className="rounded-[4px] bg-[#7a5a00]/10 px-1 py-0.5 font-medium">
              VALERIA_BOTOES_ENABLED
            </code>{" "}
            não estiver ligada no ambiente do backend. A variável não está no{" "}
            <code className="rounded-[4px] bg-[#7a5a00]/10 px-1 py-0.5 font-medium">.env</code> e o
            padrão é desligado — ativar aqui e não ver nada acontecer é o estado esperado, não um
            defeito. Defina{" "}
            <code className="rounded-[4px] bg-[#7a5a00]/10 px-1 py-0.5 font-medium">
              VALERIA_BOTOES_ENABLED=true
            </code>{" "}
            e reinicie o container da API.
          </p>
        </section>
      )}

      {/* ── Cabeçalho: qual fluxo, quantos canais, e o estado da chave. ── */}
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]">
          Canais de WhatsApp
        </h3>
        <p className="shrink-0 text-[11px] text-[#7b7b78]">
          Fluxo{" "}
          <code className="rounded-[4px] bg-[#faf9f6] px-1 py-0.5 text-[#111111]">
            {dados?.flow_id ?? flowId}
          </code>
          {dados && (
            <>
              {" · chave "}
              <span className={dados.ligado ? "font-medium text-[#1a7a3a]" : "font-medium text-[#7a5a00]"}>
                {dados.ligado ? "ligada" : "desligada"}
              </span>
            </>
          )}
          {carregando && dados && <span className="ml-2 text-[#b0aca6]">atualizando…</span>}
        </p>
      </div>

      {erro && (
        <p
          role="alert"
          className="mb-3 rounded-[6px] border border-[#f0c8c4] bg-[#fef0f0] px-3 py-2 text-[13px] leading-[1.5] text-[#a4261b]"
        >
          {erro}
        </p>
      )}

      {sucesso && (
        <p
          role="status"
          className="mb-3 rounded-[6px] border border-[#dedbd6] bg-[#faf9f6] px-3 py-2 text-[13px] leading-[1.5] text-[#111111]"
        >
          {sucesso}
        </p>
      )}

      {carregando && !dados ? (
        <div className="space-y-2" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-[6px] bg-[#dedbd6]/30" />
          ))}
        </div>
      ) : canais.length === 0 ? (
        !erro && (
          <p className="py-10 text-center text-[13px] text-[#7b7b78]">
            Nenhum canal de WhatsApp cadastrado.
          </p>
        )
      ) : (
        <ul className="space-y-2">
          {canais.map((canal) => (
            <LinhaCanal
              key={canal.id}
              canal={canal}
              confirmando={confirmando === canal.id}
              ativandoEste={ativando === canal.id}
              emVoo={emVoo}
              onPedirConfirmacao={() => {
                setConfirmando(canal.id);
                setSucesso(null);
                setErro(null);
              }}
              onCancelar={() => setConfirmando(null)}
              onConfirmar={() => void ativar(canal)}
            />
          ))}
        </ul>
      )}

      <p className="mt-4 border-t border-[#dedbd6] pt-3 text-[12px] leading-[1.5] text-[#7b7b78]">
        Ativar nunca edita um perfil de agente que já existe: cria um perfil novo e reaponta só o
        canal escolhido. É o que impede que um número compartilhando perfil com outro vire robô de
        carona.
      </p>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Uma linha de canal
// ═══════════════════════════════════════════════════════════════════════════════

interface LinhaProps {
  canal: CanalDoFluxo;
  confirmando: boolean;
  ativandoEste: boolean;
  emVoo: boolean;
  onPedirConfirmacao: () => void;
  onCancelar: () => void;
  onConfirmar: () => void;
}

function LinhaCanal({
  canal,
  confirmando,
  ativandoEste,
  emVoo,
  onPedirConfirmacao,
  onCancelar,
  onConfirmar,
}: LinhaProps) {
  const nome = nomeOu(canal.name, canal.id);
  const irmaos = nomesIrmaos(canal);
  const quantosIrmaos = (canal.compartilhado_com ?? []).length;
  const citados = citarIrmaos(irmaos, quantosIrmaos);
  // A concordância segue o que a frase CITA, não quantos irmãos existem: com
  // `["João", null]` o texto cita um nome só, e "João continuam" é erro na tela.
  const plural = (irmaos.length > 0 ? irmaos.length : quantosIrmaos) > 1;
  const compartilhado = Boolean(canal.perfil_compartilhado);
  // Abrir a confirmação DESMONTA o botão "Ativar", que é quem tinha o foco. Sem
  // reconduzir, o foco cai no `<body>` e o Tab-trap da casca joga quem usa teclado
  // para o topo do modal, longe do canal que ele acabou de escolher. O foco vai para
  // CANCELAR, não para "Confirmar ativação": um Enter perdido não pode repontar um
  // número de WhatsApp.
  const refCancelar = useRef<HTMLButtonElement>(null);
  const refAtivar = useRef<HTMLButtonElement>(null);
  const abriuAntes = useRef(false);
  useEffect(() => {
    if (confirmando) {
      abriuAntes.current = true;
      refCancelar.current?.focus();
    } else if (abriuAntes.current) {
      abriuAntes.current = false;
      // Ausente depois de uma ativação bem-sucedida (o canal já atende ao fluxo e não
      // tem mais botão): `?.` cobre esse caso, e a faixa `role="status"` anuncia.
      refAtivar.current?.focus();
    }
  }, [confirmando]);
  const perfilNome = canal.perfil ? nomeOu(canal.perfil.name, canal.perfil.id ?? "sem nome") : null;
  // Perfil de botões que NÃO é este fluxo: o `flow_id` cru, sem reimplementar a regra
  // de default de `runner._fluxo_de` (o `atende_este_fluxo` do router já é a resposta
  // para ESTE fluxo, e uma segunda cópia da regra é a divergência que o projeto evita).
  const outroFluxoDeBotoes =
    canal.perfil?.kind === "button_flow" && !canal.atende_este_fluxo;

  // A borda esquerda carrega o estado: tinta = já atende por este fluxo, âmbar =
  // perfil acoplado a outro canal, transparente = nada a notar.
  const borda = canal.atende_este_fluxo
    ? "border-l-[#111111]"
    : compartilhado
      ? "border-l-[#e8c65a]"
      : "border-l-transparent";

  return (
    <li
      className={`rounded-[6px] border border-[#dedbd6] border-l-2 bg-white px-3 py-2.5 ${borda}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <p className="text-[13px] font-medium text-[#111111]">{nome}</p>
        <p className="text-[12px] tabular-nums text-[#7b7b78]">
          {nomeOu(canal.phone, "sem número")}
        </p>
        {canal.atende_este_fluxo && (
          <span className="rounded-[4px] bg-[#111111] px-1.5 py-0.5 text-[11px] font-medium text-white">
            Atende por este fluxo
          </span>
        )}
        {canal.is_active === false && (
          <span className="rounded-[4px] bg-[#f0ede8] px-1.5 py-0.5 text-[11px] text-[#7b7b78]">
            Canal inativo
          </span>
        )}
        {canal.mode && (
          <span className="rounded-[4px] bg-[#faf9f6] px-1.5 py-0.5 text-[11px] text-[#7b7b78]">
            modo {canal.mode}
          </span>
        )}
      </div>

      <p className="mt-1 text-[12px] text-[#7b7b78]">
        {perfilNome ? (
          <>
            Agente atual: <span className="text-[#111111]">{perfilNome}</span>{" "}
            <code className="rounded-[4px] bg-[#faf9f6] px-1 py-0.5">{canal.perfil?.kind}</code>
          </>
        ) : (
          "Sem perfil de agente — este canal não é atendido por nenhum agente hoje."
        )}
      </p>

      {outroFluxoDeBotoes && (
        <p className="mt-1 text-[12px] text-[#7a5a00]">
          Já atende por OUTRO fluxo de botões (
          <code className="rounded-[4px] bg-[#fff8e0] px-1 py-0.5">
            flow_id: {canal.perfil?.flow_id ?? "nulo"}
          </code>
          ). Ativar aqui troca o roteiro que este número segue.
        </p>
      )}

      {/* ── O aviso de perfil compartilhado ── */}
      {compartilhado && (
        <div className="mt-2 rounded-[4px] border border-[#e8c65a] bg-[#fff8e0] px-2.5 py-2">
          <p className="text-[12px] font-semibold text-[#7a5a00]">
            Perfil compartilhado com {citados}
          </p>
          <p className="mt-0.5 text-[12px] leading-[1.5] text-[#7a5a00]">
            Este canal e {citados} apontam para o MESMO perfil de agente
            {perfilNome ? ` (${perfilNome})` : ""}. Editar esse perfil trocaria o agente de todos
            eles de uma vez. É por isso que Ativar não edita o perfil compartilhado: a ativação cria
            um perfil NOVO e reaponta só {nome} — {citados} {plural ? "continuam" : "continua"} no
            perfil atual, sem mudança nenhuma.
          </p>
        </div>
      )}

      {/* ── A ação ── */}
      <div className="mt-2">
        {confirmando ? (
          <div
            role="group"
            aria-label={`Confirmar ativação em ${nome}`}
            className="rounded-[4px] border border-[#111111] bg-[#faf9f6] px-2.5 py-2"
          >
            <p className="text-[12px] font-semibold text-[#111111]">
              Ativar a ValerIA de Botões em {nome} ({nomeOu(canal.phone, "sem número")})?
            </p>
            <p className="mt-0.5 text-[12px] leading-[1.5] text-[#7b7b78]">
              Este número passa a responder por um roteiro de botões, e a ValerIA com IA deixa de
              atender neste canal. Um perfil de agente novo é criado e só este canal passa a apontar
              para ele
              {compartilhado ? `; ${citados} ${plural ? "seguem" : "segue"} no perfil de hoje` : ""}.
            </p>
            {/* `mode='human'` não protege o número, e é contraintuitivo o bastante
                para precisar ser dito no momento do clique: o gate dos fluxos de
                botões roda ANTES do gate de canal humano em `buffer/processor.py`, de
                propósito — está escrito lá que é para o bot funcionar no número do
                João justamente por ele ser `mode='human'`. Quem lê "modo human" e
                supõe que o roteiro não vai falar ali supõe o contrário do código. */}
            {canal.mode === "human" && (
              <p className="mt-1 text-[12px] leading-[1.5] text-[#7a5a00]">
                Este canal está em modo <strong className="font-semibold">human</strong>, e isso NÃO
                impede o roteiro de responder: o fluxo de botões é avaliado antes do bloqueio de
                canal humano. Com a chave ligada, o robô fala neste número — que é o número pessoal
                de um vendedor.
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onConfirmar}
                disabled={emVoo}
                className="rounded-[4px] bg-[#111111] px-3 py-1.5 text-[12px] text-white transition-colors hover:bg-[#333333] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {ativandoEste ? "Ativando…" : "Confirmar ativação"}
              </button>
              <button
                type="button"
                ref={refCancelar}
                onClick={onCancelar}
                disabled={emVoo}
                className="rounded-[4px] border border-[#dedbd6] bg-white px-3 py-1.5 text-[12px] text-[#111111] transition-colors hover:bg-[#f0ede8] disabled:cursor-not-allowed disabled:opacity-40"
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : canal.atende_este_fluxo ? (
          <p className="text-[12px] text-[#7b7b78]">
            Já aponta para este fluxo. Para voltar à ValerIA com IA, troque o perfil do canal em
            /canais.
          </p>
        ) : (
          <button
            type="button"
            ref={refAtivar}
            onClick={onPedirConfirmacao}
            disabled={emVoo}
            className="rounded-[4px] border border-[#111111] bg-white px-3 py-1.5 text-[12px] text-[#111111] transition-colors hover:bg-[#111111] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            Ativar
          </button>
        )}
      </div>
    </li>
  );
}

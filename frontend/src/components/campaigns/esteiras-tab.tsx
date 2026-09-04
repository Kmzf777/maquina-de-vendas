// frontend/src/components/campaigns/esteiras-tab.tsx
"use client";

/**
 * Aba "Esteiras" de /campanhas.
 *
 * NÃO é um builder — é um formulário. Já existe um editor de grafo em
 * /campanhas/cadencias/{id} que faz tudo isto e mais; é justamente o que o vendedor não
 * usa. Aqui cada esteira é um cartão com quatro decisões (canal, funil, etapa, prazo) e
 * uma linha do tempo que se lê em voz alta. Tudo que não é decisão do vendedor — a forma
 * do fluxo, a ação final — aparece como TEXTO, não como campo.
 *
 * Spec: docs/superpowers/specs/2026-09-04-esteiras-vendedor-design.md §8
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Channel, MessageTemplate, Pipeline, PipelineStage } from "@/lib/types";

// ─── Contrato da API ───────────────────────────────────────────────────────────

interface Toque {
  ordem: number;
  dias: number;
  template_name: string | null;
}

/** Config do nó de gatilho. Opcional: só existe depois que o seed rodou. */
interface Gatilho {
  stage_days?: number | null;
  silence_days?: number | null;
  last_speaker?: string | null;
  stage_key?: string | null;
}

interface Esteira {
  key: string;
  campaign_id: string | null;
  nome: string;
  descricao: string;
  ativa: boolean;
  canal_id: string | null;
  funil_id: string | null;
  etapa_id: string | null;
  etapa_key: string | null;
  /**
   * Qual campo do gatilho é o prazo do primeiro toque. Vem do backend porque lá ele é
   * derivado do SEED — o mesmo número significa "3 dias parado na etapa Proposta Enviada"
   * numa esteira e "3 dias sem conversa" em outra, e a tela não pode chutar qual.
   */
  relogio: "stage_days" | "silence_days" | string | null;
  gatilho: Gatilho | null;
  toques: Toque[];
  acao_final: string | null;
  /**
   * Etapa de Perdido resolvida pela API a partir do funil (só na esteira de reposição).
   * `null` com `acao_final = mark_deal_lost` significa que a esteira vai rodar os três
   * toques e terminar SEM mover o card — precisa aparecer na tela.
   */
  stage_id_perdido: string | null;
}

/** Feedback de uma gravação. Três naturezas diferentes, três tratamentos. */
type Retorno =
  /** 400 e falha de rede: não gravou. */
  | { tipo: "erro"; texto: string }
  /** 200 com ressalva: gravou, mas a esteira vai rodar capenga. */
  | { tipo: "aviso"; texto: string }
  /** 409: a esteira nem existe no banco — problema de instalação, não de configuração. */
  | { tipo: "bloqueio"; texto: string };

/** Usado só se o backend não mandar `detail` — a mensagem dele é melhor que esta. */
const BLOQUEIO_PADRAO =
  "Esta esteira ainda não existe no banco. O seed roda quando a API sobe: confira se a " +
  "migration 20260904_esteiras_vendedor.sql foi aplicada no Supabase e reinicie a API.";

// ─── Vocabulário fixo ──────────────────────────────────────────────────────────

/**
 * A ação final é TEXTO, nunca campo. Duas razões: ela é decisão da ata (a esteira de
 * proposta nunca move o card sozinha; a de reposição sempre termina em Perdido), e o
 * `stage_id` de Perdido é resolvido pela API a partir do funil — não há nada que o
 * vendedor pudesse digitar aqui que não fosse um jeito de errar.
 */
const ACAO_FINAL: Record<string, string> = {
  mark_deal_lost: "move para Perdido",
  alert_seller: "avisa o vendedor",
};

const acaoFinalTexto = (acao: string | null): string =>
  (acao && ACAO_FINAL[acao]) || "encerra sem fazer mais nada";

/**
 * Etapas identificadas por `key` (e não por id) valem em TODO funil — é assim que a
 * esteira de proposta funciona sem que ninguém precise apontá-la funil a funil. Os rótulos
 * espelham `DEFAULT_STAGES` em app/api/pipelines/route.ts.
 */
const ETAPA_POR_KEY: Record<string, string> = {
  proposta_enviada: "Proposta Enviada",
  fechado_ganho: "Fechado Ganho",
  fechado_perdido: "Perdido",
  perdido: "Perdido",
};

/** Quem precisa ter falado por último para a esteira entrar. */
const FALANTE: Record<string, string> = {
  lead: "só quando a última mensagem foi do cliente",
  nos: "só quando a última mensagem foi nossa",
  qualquer: "não importa quem falou por último",
};

/**
 * Agrupamento da tela, na ordem em que o funil acontece. As duas esteiras de "Novo"
 * moram no mesmo cartão-grupo porque são a mesma etapa vista dos dois lados: o cliente
 * perguntou e ninguém respondeu, ou nós respondemos e ele sumiu.
 */
const GRUPOS: { titulo: string; resumo: string; keys: string[] }[] = [
  {
    titulo: "Etapa Novo",
    resumo: "O primeiro contato que ficou parado — dos dois lados.",
    keys: ["novo_sem_resposta", "novo_reengajamento"],
  },
  {
    titulo: "Reposição",
    resumo: "Quem já comprou ou já foi atendido e sumiu do radar.",
    keys: ["reposicao"],
  },
  {
    titulo: "Proposta enviada",
    resumo: "Orçamento na mão do cliente e nenhuma resposta.",
    keys: ["proposta"],
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────

/** Toda API deste projeto devolve array cru ou `{ chave: [] }`. Normaliza os dois. */
function comoLista<T>(payload: unknown, chave: string): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === "object") {
    const v = (payload as Record<string, unknown>)[chave];
    if (Array.isArray(v)) return v as T[];
  }
  return [];
}

/**
 * O payload realmente veio como lista?
 *
 * `comoLista` achata erro e vazio no mesmo `[]`, e para os templates essa diferença
 * decide se o interruptor trava: "nenhum template aprovado" tem de travar, "não deu para
 * saber" não pode. Sem esta distinção, um 500 do Supabase deixaria a tela inteira sem
 * saída — o mesmo fail-open que o PUT aplica em `_nao_aprovados`.
 */
function ehLista(payload: unknown, chave: string): boolean {
  if (Array.isArray(payload)) return true;
  return Boolean(
    payload &&
      typeof payload === "object" &&
      Array.isArray((payload as Record<string, unknown>)[chave])
  );
}

/**
 * Só template APROVADO pela Meta entra no select.
 * Template em análise não dispara: configurar a esteira com ele é montar uma automação
 * que falha em silêncio, e o silêncio aqui custa o lead. Dedupe por nome porque os canais
 * compartilham a mesma WABA e cada template aparece uma vez por canal.
 */
function templatesAprovados(templates: MessageTemplate[]): string[] {
  const nomes = new Set<string>();
  for (const t of templates) {
    if ((t.status ?? "").toLowerCase() === "approved" && t.name) nomes.add(t.name);
  }
  return [...nomes].sort((a, b) => a.localeCompare(b));
}

/**
 * Corpo de cada template, por nome. `esteira_reposicao_v1` não diz nada a ninguém: sem o
 * texto ao lado, escolher template vira loteria e o vendedor não tem como saber o que o
 * cliente vai ler. `/api/templates` já devolve `body` parseado.
 */
function corposDeTemplate(templates: MessageTemplate[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const t of templates) {
    if (t.name && t.body && !out[t.name]) out[t.name] = t.body;
  }
  return out;
}

/** Uma esteira sem etapa vale para QUALQUER etapa de QUALQUER funil — ver §6.8 da spec. */
const temEtapa = (e: Esteira): boolean => Boolean(e.etapa_id || e.etapa_key);

/**
 * O que ainda falta para a esteira poder ser LIGADA. Lista vazia = pode ligar.
 *
 * As três condições são as mesmas que o PUT recusa com 400 — a tela existe para o clique
 * nem ser oferecido. Cada texto diz o que fazer primeiro e só depois por quê: "escolha o
 * canal" é acionável; "canal ausente" faz o vendedor adivinhar.
 *
 * O CANAL não pode ser deduzido em silêncio. Sem ele duas proteções caem juntas:
 * `_conversation_followup_disabled(lead, None)` devolve `false` de cara — a marcação
 * "Finalizar Conversa" que o vendedor faz em /conversas passa a ser ignorada — e o envio
 * cai em `get_channel_for_lead`, que escolhe a conversa ativa mais recente: um template
 * assinado "Aqui é o João" sairia do número da Valéria.
 *
 * O TEMPLATE é a mais cara das três, porque falha em silêncio: template não aprovado não
 * impede a INSCRIÇÃO, só o envio. A esteira inscreve o lead, não manda nada e mesmo assim
 * caminha até a ação final — na reposição isso marca o card como Perdido sem uma única
 * mensagem ter saído, registrando "não teve resposta" para quem nunca foi contatado.
 *
 * `aprovados = null` significa "ainda não sei" (carregando, ou a API não devolveu lista):
 * aí a checagem de template não roda. Mesmo fail-open do backend — travar tudo por um
 * Supabase oscilando é pior do que o risco.
 *
 * `curto` é a mesma exigência dita numa frase de rodapé, onde já há contexto.
 */
const PENDENCIAS: {
  falta: (e: Esteira, aprovados: string[] | null) => boolean;
  curto: string;
  texto: string;
}[] = [
  {
    falta: (e) => !temEtapa(e),
    curto: "a etapa do novo funil",
    texto:
      "Escolha o funil e a etapa antes de ligar — sem etapa, a esteira valeria para todo " +
      "card aberto de todos os funis.",
  },
  {
    falta: (e) => !e.canal_id,
    curto: "o canal",
    texto:
      "Escolha o canal antes de ligar — é o número de onde a mensagem sai. Sem ele a " +
      "esteira envia pelo número da conversa mais recente do cliente, que pode ser o da " +
      "Valéria, e passa por cima das conversas que você já finalizou à mão.",
  },
  {
    falta: (e, aprovados) =>
      aprovados !== null &&
      e.toques.some((t) => !t.template_name || !aprovados.includes(t.template_name)),
    curto: "um template aprovado para cada toque",
    texto:
      "Espere a aprovação dos templates na Meta antes de ligar — template em análise não " +
      "impede a inscrição, só o envio. A esteira inscreveria o cliente, não mandaria nada " +
      "e mesmo assim seguiria até o fim, marcando como sem resposta quem nunca foi " +
      "contatado.",
  },
];

const pendenciasDe = (e: Esteira, aprovados: string[] | null) =>
  PENDENCIAS.filter((p) => p.falta(e, aprovados));

/** "a" | "a e b" | "a, b e c" — as três pendências podem faltar ao mesmo tempo. */
const emLista = (itens: string[]): string =>
  itens.length < 2 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens.at(-1)}`;

// ─── Peças ─────────────────────────────────────────────────────────────────────

function Interruptor({
  ligada,
  desabilitado,
  titulo,
  onClick,
}: {
  ligada: boolean;
  desabilitado: boolean;
  titulo: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={ligada}
      aria-label={titulo}
      title={titulo}
      disabled={desabilitado}
      onClick={onClick}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        ligada ? "bg-[#0bdf50]" : "bg-[#dedbd6]"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
          ligada ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
    </button>
  );
}

function Campo({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
        {rotulo}
      </span>
      {children}
    </label>
  );
}

const SELECT_CLS =
  "w-full bg-white border border-[#dedbd6] rounded-[6px] px-2.5 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none disabled:bg-[#faf9f6] disabled:text-[#7b7b78]";

function SelectTemplate({
  valor,
  aprovados,
  corpos,
  onChange,
}: {
  valor: string | null;
  aprovados: string[];
  corpos: Record<string, string>;
  onChange: (v: string) => void;
}) {
  // O template configurado hoje pode não estar aprovado (ainda em análise, ou recusado).
  // Escondê-lo faria o select mentir sobre o que a esteira vai enviar; então ele aparece,
  // marcado e desabilitado, para ser visto e trocado.
  const foraDaLista = Boolean(valor && !aprovados.includes(valor));
  return (
    <div>
      <select
        aria-label="Template da mensagem"
        value={valor ?? ""}
        onChange={(ev) => onChange(ev.target.value)}
        className={SELECT_CLS}
      >
        {!valor && <option value="">— escolher template —</option>}
        {foraDaLista && (
          <option value={valor as string} disabled>
            {valor} · não aprovado
          </option>
        )}
        {aprovados.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
      {foraDaLista && (
        <p className="text-[11px] text-[#c2590a] mt-1">
          Este template não está aprovado na Meta — enquanto isso, a esteira não envia nada.
        </p>
      )}
      {!foraDaLista && aprovados.length === 0 && (
        <p className="text-[11px] text-[#7b7b78] mt-1">Nenhum template aprovado ainda.</p>
      )}
      {valor && corpos[valor] && (
        <p className="text-[11px] text-[#7b7b78] mt-1 leading-snug border-l-2 border-[#e6e2dc] pl-2">
          {corpos[valor]}
        </p>
      )}
    </div>
  );
}

// ─── Cartão de uma esteira ─────────────────────────────────────────────────────

function CartaoEsteira({
  esteira,
  canais,
  funis,
  etapas,
  etapasCarregadas,
  aprovados,
  corpos,
  sujo,
  salvando,
  retorno,
  onCampo,
  onToque,
  onSalvar,
  onAlternar,
}: {
  esteira: Esteira;
  canais: Channel[];
  funis: Pipeline[];
  etapas: PipelineStage[];
  etapasCarregadas: boolean;
  /** `null` = ainda não sei quais estão aprovados; ver PENDENCIAS. */
  aprovados: string[] | null;
  corpos: Record<string, string>;
  sujo: boolean;
  salvando: boolean;
  retorno: Retorno | null;
  onCampo: (campo: "canal_id" | "funil_id" | "etapa_id", valor: string) => void;
  onToque: (indice: number, patch: Partial<Toque>) => void;
  onSalvar: () => void;
  onAlternar: () => void;
}) {
  const faltando = pendenciasDe(esteira, aprovados);
  const pronta = faltando.length === 0;
  // Os selects não distinguem "não sei" de "nenhum": ali as duas situações mostram a
  // mesma lista vazia. Só a decisão de TRAVAR o interruptor precisa da diferença.
  const listaAprovados = aprovados ?? [];
  const presaPorKey = Boolean(esteira.etapa_key);
  const gatilho = esteira.gatilho ?? null;
  // O relógio é do backend (derivado do seed). Cair em `stage_days > 0` só quando ele
  // não vier: gravar `dias: 0` zeraria o campo e trocaria o rótulo em silêncio.
  const relogioDeEtapa =
    esteira.relogio === "stage_days" ||
    (esteira.relogio !== "silence_days" && (gatilho?.stage_days ?? 0) > 0);
  const falante = gatilho?.last_speaker ? FALANTE[gatilho.last_speaker] : null;
  // A reposição termina em "move para Perdido", mas o motor vira no-op sem `stage_id`:
  // faria os três toques e deixaria o card exatamente onde estava.
  const semEtapaDePerda =
    esteira.acao_final === "mark_deal_lost" && !esteira.stage_id_perdido;
  // Salvar manda `ativa` junto. Numa esteira LIGADA cuja etapa acabou de ser limpa (troca
  // de funil) ou cujo canal foi apagado, o backend recusa com 400 — corretamente. A tela
  // não deve chegar lá.
  const faltaParaSalvar = esteira.ativa && !pronta;

  return (
    <article
      className={`relative bg-white border rounded-[8px] overflow-hidden transition-colors ${
        esteira.ativa ? "border-[#c4e9cf]" : "border-[#dedbd6]"
      }`}
    >
      {/* Trilho de estado — a metáfora do disjuntor: dá para ver o que está armado
          antes de ler qualquer palavra. */}
      <span
        aria-hidden
        className={`absolute left-0 top-0 bottom-0 w-[3px] ${
          esteira.ativa ? "bg-[#0bdf50]" : "bg-[#e6e2dc]"
        }`}
      />

      <header className="flex items-start gap-3 px-5 pt-4 pb-3">
        <div className="pt-0.5">
          <Interruptor
            ligada={esteira.ativa}
            desabilitado={!esteira.ativa && !pronta}
            titulo={esteira.ativa ? `Desligar ${esteira.nome}` : `Ligar ${esteira.nome}`}
            onClick={onAlternar}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-[15px] font-medium text-[#111111] leading-tight">
              {esteira.nome}
            </h4>
            <span
              className={`text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] ${
                esteira.ativa
                  ? "bg-[#0bdf50]/10 text-[#177a37]"
                  : "bg-[#f0ede8] text-[#7b7b78]"
              }`}
            >
              {esteira.ativa ? "Ligada" : "Desligada"}
            </span>
          </div>
          <p className="text-[12px] text-[#7b7b78] mt-1 leading-snug">{esteira.descricao}</p>
          {falante && (
            <p className="text-[12px] text-[#626260] mt-1 leading-snug">
              Entra {falante}.
            </p>
          )}
          {/* O interruptor está travado; aqui fica o motivo, um por linha. Ele é o único
              controle desabilitado do cartão, então a explicação mora ao lado dele — não
              num tooltip que só aparece se o vendedor souber procurar. */}
          {!esteira.ativa && faltando.length > 0 && (
            <ul className="mt-1.5 space-y-1">
              {faltando.map((p) => (
                <li key={p.curto} className="text-[12px] text-[#c2590a] leading-snug">
                  {p.texto}
                </li>
              ))}
            </ul>
          )}
        </div>
      </header>

      {/* Onde a esteira olha */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 px-5 pb-4">
        <Campo rotulo="Canal">
          <select
            aria-label="Canal"
            value={esteira.canal_id ?? ""}
            onChange={(ev) => onCampo("canal_id", ev.target.value)}
            className={SELECT_CLS}
          >
            <option value="">— escolher —</option>
            {canais.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Campo>
        <Campo rotulo="Funil">
          <select
            aria-label="Funil"
            value={esteira.funil_id ?? ""}
            onChange={(ev) => onCampo("funil_id", ev.target.value)}
            className={SELECT_CLS}
          >
            <option value="">— escolher —</option>
            {funis.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </Campo>
        <Campo rotulo="Etapa">
          {presaPorKey ? (
            // A esteira de proposta nasce presa a `proposta_enviada` — a mesma etapa que
            // /orcamento cria. Deixar isso editável seria oferecer um jeito de desligá-la
            // sem perceber.
            <p className="text-[13px] text-[#111111] border border-dashed border-[#dedbd6] rounded-[6px] px-2.5 py-2 bg-[#faf9f6]">
              {ETAPA_POR_KEY[esteira.etapa_key as string] ?? esteira.etapa_key}
              <span className="block text-[11px] text-[#7b7b78]">fixa em todos os funis</span>
            </p>
          ) : (
            <select
              aria-label="Etapa"
              value={esteira.etapa_id ?? ""}
              onChange={(ev) => onCampo("etapa_id", ev.target.value)}
              disabled={!esteira.funil_id}
              className={SELECT_CLS}
            >
              <option value="">{esteira.funil_id ? "— escolher —" : "escolha o funil"}</option>
              {etapas.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
              {/* O select precisa de uma opção com o value atual, senão o campo aparece
                  vazio e dá a impressão de que a esteira não está apontada para lugar
                  nenhum. Antes das etapas chegarem, dizemos que estamos carregando; depois
                  delas, a ausência é real e vale o alerta. */}
              {esteira.etapa_id && !etapas.some((s) => s.id === esteira.etapa_id) && (
                <option value={esteira.etapa_id}>
                  {etapasCarregadas ? "Etapa configurada (fora deste funil)" : "Carregando etapas..."}
                </option>
              )}
            </select>
          )}
        </Campo>
      </div>

      {/* Linha do tempo — o que a esteira faz, na ordem, em português. */}
      <div className="border-t border-[#f0ede8] bg-[#fcfbf9] px-5 py-4">
        <p className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
          O que ela faz
        </p>
        {/* O trilho vertical mora FORA do <ol>: lista ordenada só pode ter <li> como
            filho, e um <span> solto ali é HTML inválido. */}
        <div className="relative pl-6">
          <span
            aria-hidden
            className="absolute left-[9px] top-2 bottom-4 w-px bg-[#e6e2dc]"
          />
          <ol className="space-y-3">
            {esteira.toques.map((t, i) => (
              <li key={t.ordem} className="relative flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="absolute -left-6 top-0.5 h-[18px] w-[18px] rounded-full bg-white border border-[#dedbd6] text-[10px] text-[#7b7b78] flex items-center justify-center">
                  {i + 1}
                </span>
                <span className="text-[13px] text-[#111111]">{i === 0 ? "Após" : "Mais"}</span>
                <input
                  type="number"
                  // O toque 1 grava no GATILHO, não numa espera: com 0 ali o gatilho fica
                  // sem filtro de tempo nenhum e a esteira pega todo card que estiver na
                  // etapa — inclusive a proposta enviada há cinco minutos. Da espera 2 em
                  // diante, 0 só quer dizer "no mesmo ciclo" e é legítimo.
                  min={i === 0 ? 1 : 0}
                  max={365}
                  aria-label={`Dias do toque ${i + 1}`}
                  value={String(t.dias ?? 0)}
                  onChange={(ev) => onToque(i, { dias: Number(ev.target.value) })}
                  className="w-14 bg-white border border-[#dedbd6] rounded-[6px] px-2 py-1 text-[13px] text-[#111111] text-center focus:border-[#111111] focus:outline-none"
                />
                <span className="text-[13px] text-[#111111]">
                  {i === 0
                    ? relogioDeEtapa
                      ? "dias parado nesta etapa, envia"
                      : "dias sem nenhuma conversa, envia"
                    : "dias sem resposta, envia"}
                </span>
                <div className="flex-1 min-w-[200px]">
                  <SelectTemplate
                    valor={t.template_name}
                    aprovados={listaAprovados}
                    corpos={corpos}
                    onChange={(v) => onToque(i, { template_name: v })}
                  />
                </div>
              </li>
            ))}
            <li className="relative flex flex-col gap-0.5">
              <span
                aria-hidden
                className="absolute -left-6 top-0.5 h-[18px] w-[18px] rounded-[4px] bg-[#f0ede8] border border-[#dedbd6]"
              />
              <span className="text-[13px] text-[#626260]">
                No fim, {acaoFinalTexto(esteira.acao_final)}.
              </span>
              {semEtapaDePerda && (
                <span className="text-[11px] text-[#c2590a] leading-snug">
                  O funil escolhido não tem coluna de Perdido, então ela vai enviar os
                  toques e deixar o card onde está.
                </span>
              )}
            </li>
          </ol>
        </div>
      </div>

      {/* Retorno da última gravação. `aviso` NÃO é erro: gravou, e a esteira funciona —
          só não inteira. Vermelho aqui treinaria o vendedor a ignorar vermelho. */}
      {retorno && (
        <div
          className={`px-5 py-2.5 text-[12px] leading-snug border-t ${
            retorno.tipo === "erro"
              ? "bg-[#fef0f0] border-[#f3d0d0] text-[#c41c1c]"
              : "bg-[#fff8e0] border-[#eadfb4] text-[#7a5a00]"
          }`}
        >
          <strong className="font-medium">
            {retorno.tipo === "erro"
              ? "Não salvou. "
              : retorno.tipo === "bloqueio"
                ? "Esteira indisponível. "
                : "Salvo, com uma ressalva. "}
          </strong>
          {retorno.texto}
        </div>
      )}

      <footer className="flex items-center justify-between gap-3 px-5 py-3 border-t border-[#f0ede8]">
        <div className="text-[12px] min-h-[18px]">
          {faltaParaSalvar ? (
            <span className="text-[#c2590a]">
              Esta esteira está ligada: escolha {emLista(faltando.map((p) => p.curto))} para
              poder salvar.
            </span>
          ) : sujo ? (
            <span className="text-[#7b7b78]">Alterações não salvas</span>
          ) : (
            esteira.campaign_id && (
              <a
                href={`/campanhas/cadencias/${esteira.campaign_id}`}
                className="text-[#7b7b78] hover:text-[#111111] underline underline-offset-2 transition-colors"
              >
                abrir no builder →
              </a>
            )
          )}
        </div>
        <button
          type="button"
          onClick={onSalvar}
          disabled={!sujo || salvando || faltaParaSalvar}
          className="bg-[#111111] text-white px-[14px] py-1.5 rounded-[4px] text-[13px] transition-transform hover:scale-105 active:scale-[0.9] disabled:opacity-30 disabled:hover:scale-100 disabled:cursor-not-allowed"
        >
          {salvando ? "Salvando..." : "Salvar"}
        </button>
      </footer>
    </article>
  );
}

// ─── Confirmação de ligar ──────────────────────────────────────────────────────

interface Confirmacao {
  key: string;
  nome: string;
  elegiveis: number | null;
  truncado: boolean;
  motivo: string | null;
  carregando: boolean;
}

// Mesmo diagnóstico do 409 do PUT (BLOQUEIO_PADRAO), dito onde o usuário está: prévia e
// gravação falham pela mesma causa, e duas explicações diferentes para um problema só
// mandariam ele procurar em dois lugares.
const MOTIVO_TEXTO: Record<string, string> = {
  sem_campanha:
    "A esteira ainda não existe no banco — o seed roda quando a API sobe. Confira se a " +
    "migration 20260904_esteiras_vendedor.sql foi aplicada e reinicie a API.",
  sem_gatilho: "A campanha existe, mas está sem nó de gatilho. Abra no builder para ver.",
  sem_etapa: "Sem etapa configurada não dá para contar — e nem para ligar.",
  rpc_indisponivel:
    "A função get_deals_stage_stagnant ainda não existe no banco. Aplique a migration 20260904_esteiras_vendedor.sql.",
};

function DialogoLigar({
  confirmacao,
  onCancelar,
  onConfirmar,
}: {
  confirmacao: Confirmacao;
  onCancelar: () => void;
  onConfirmar: () => void;
}) {
  const { elegiveis, truncado, motivo, carregando, nome } = confirmacao;

  // Prévia que não respondeu é BLOQUEIO, não ressalva. As causas possíveis (migration não
  // aplicada, campanha sem seed, gatilho ausente) têm todas o mesmo efeito se a esteira
  // for ligada assim: `campaigns.status` vira 'active', nada nunca dispara, e a tela
  // passa a mostrar "Ligada" para algo que não roda. Ligada e muda é o pior estado
  // possível aqui, porque parece o estado bom. Sem número, tiramos o clique — não basta
  // desencorajá-lo.
  const naoDeuParaContar = !carregando && elegiveis === null;
  const nenhumElegivel = !carregando && elegiveis === 0;

  // Esc fecha. Este diálogo é o último ponto em que dá para desistir sem consequência —
  // fechá-lo tem de ser mais fácil do que confirmá-lo.
  useEffect(() => {
    const aoTeclar = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onCancelar();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onCancelar]);

  return (
    <div
      className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
      onClick={onCancelar}
    >
      <div
        onClick={(ev) => ev.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Ligar ${nome}`}
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-md p-6 animate-in fade-in-0 zoom-in-95"
      >
        <h3 className="text-[16px] font-medium text-[#111111]">Ligar {nome}?</h3>

        <div className="mt-4 border border-[#dedbd6] rounded-[6px] bg-[#faf9f6] px-4 py-3">
          {carregando ? (
            <p className="text-[13px] text-[#7b7b78]">Contando cards elegíveis...</p>
          ) : elegiveis === null ? (
            <p className="text-[13px] text-[#c2590a]">
              Não foi possível contar agora.{" "}
              {motivo ? MOTIVO_TEXTO[motivo] ?? motivo : ""}
            </p>
          ) : (
            <div className="flex items-baseline gap-2">
              <strong
                style={{ letterSpacing: "-1px" }}
                className="text-[32px] font-normal text-[#111111] leading-none"
              >
                {truncado ? `${elegiveis}+` : elegiveis}
              </strong>
              <span className="text-[13px] text-[#626260]">
                {elegiveis === 1 ? "card entra agora" : "cards entram agora"}
              </span>
            </div>
          )}
        </div>

        {naoDeuParaContar ? (
          <p className="text-[13px] text-[#626260] mt-3 leading-relaxed">
            Sem essa contagem não dá para ligar. Ligar agora gravaria a esteira como ativa
            contra uma automação que não roda — ela apareceria como &quot;Ligada&quot; na
            tela e não mandaria nada, para sempre. Resolva o item acima e tente de novo.
          </p>
        ) : nenhumElegivel ? (
          // Zero não é defeito e não pode PARECER defeito: quem liga e vê o funil parado
          // no dia seguinte precisa saber que já era assim antes do clique.
          <p className="text-[13px] text-[#626260] mt-3 leading-relaxed">
            Nenhum card se qualifica agora — a esteira não vai mandar nada hoje. Isso não é
            erro: ela fica ligada, esperando, e pega o primeiro card que atingir o prazo.
          </p>
        ) : (
          /* O aviso da §5.1 da spec: entered_stage_at foi preenchida com a última
             movimentação de cada card, então o primeiro dia carrega todo o histórico. */
          <p className="text-[13px] text-[#626260] mt-3 leading-relaxed">
            Ao ligar, todos os cards que já estão parados há esse tempo ficam elegíveis de
            uma vez. A esteira processa no máximo 20 por ciclo e nunca manda mais de uma
            mensagem por dia para o mesmo lead — mas o volume acumulado sai inteiro, aos
            poucos.
          </p>
        )}

        <div className="flex justify-end gap-2 mt-5 pt-4 border-t border-[#dedbd6]">
          {/* Sem contagem o diálogo vira um beco: uma saída só, e ela é fechar. Deixar
              "Cancelar" ao lado de nada sugeriria que havia uma alternativa. */}
          <button
            type="button"
            onClick={onCancelar}
            className={
              naoDeuParaContar
                ? "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-105 active:scale-[0.9]"
                : "bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-105 active:scale-[0.9]"
            }
          >
            {naoDeuParaContar ? "Fechar" : "Cancelar"}
          </button>
          {!naoDeuParaContar && (
            <button
              type="button"
              onClick={onConfirmar}
              disabled={carregando}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-105 active:scale-[0.9] disabled:opacity-30 disabled:hover:scale-100 disabled:cursor-not-allowed"
            >
              Ligar esteira
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Componente principal ──────────────────────────────────────────────────────

export function EsteirasTab() {
  const [esteiras, setEsteiras] = useState<Esteira[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [falhaCarga, setFalhaCarga] = useState<string | null>(null);

  const [canais, setCanais] = useState<Channel[]>([]);
  const [funis, setFunis] = useState<Pipeline[]>([]);
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  // Se já sabemos QUAIS templates existem. Distinto de `templates.length === 0`: enquanto
  // isto for false, a guarda de template não roda e o interruptor fica livre.
  const [templatesConhecidos, setTemplatesConhecidos] = useState(false);
  const [etapasPorFunil, setEtapasPorFunil] = useState<Record<string, PipelineStage[]>>({});

  const [sujas, setSujas] = useState<Record<string, boolean>>({});
  const [salvando, setSalvando] = useState<Record<string, boolean>>({});
  const [retornos, setRetornos] = useState<Record<string, Retorno | null>>({});
  const [confirmacao, setConfirmacao] = useState<Confirmacao | null>(null);

  // ── Carga inicial ────────────────────────────────────────────────────────────
  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const res = await fetch("/api/automation/esteiras");
        const data = await res.json();
        if (!vivo) return;
        if (!res.ok) {
          setFalhaCarga(data?.error || "Não foi possível carregar as esteiras.");
        } else {
          setEsteiras(comoLista<Esteira>(data, "esteiras"));
        }
      } catch {
        if (vivo) setFalhaCarga("Não foi possível carregar as esteiras.");
      } finally {
        if (vivo) setCarregando(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  useEffect(() => {
    let vivo = true;
    (async () => {
      const [c, p, t] = await Promise.all([
        fetch("/api/channels").then((r) => r.json()).catch(() => []),
        fetch("/api/pipelines").then((r) => r.json()).catch(() => []),
        // `null` (e não `[]`) de propósito: falha de rede é "não sei quais existem".
        // `[]` significaria "nenhum aprovado" e travaria todos os interruptores.
        fetch("/api/templates").then((r) => r.json()).catch(() => null),
      ]);
      if (!vivo) return;
      setCanais(comoLista<Channel>(c, "channels").filter((x) => x.is_active !== false));
      setFunis(comoLista<Pipeline>(p, "pipelines"));
      setTemplates(comoLista<MessageTemplate>(t, "templates"));
      // Só marca como conhecido se a resposta REALMENTE veio como lista. Um 500 devolve
      // `{error}` e `comoLista` o achata em `[]` — tratar isso como "nenhum aprovado"
      // travaria todos os interruptores sem que ninguém pudesse destravá-los.
      setTemplatesConhecidos(ehLista(t, "templates"));
    })();
    return () => {
      vivo = false;
    };
  }, []);

  // Etapas: só dos funis que alguma esteira está usando. Carrega uma vez por funil.
  const funisEmUso = useMemo(
    () => [...new Set(esteiras.map((e) => e.funil_id).filter(Boolean) as string[])].sort(),
    [esteiras]
  );
  const chaveFunis = funisEmUso.join(",");

  useEffect(() => {
    let vivo = true;
    const ids = chaveFunis ? chaveFunis.split(",") : [];
    (async () => {
      for (const id of ids) {
        const lista = await fetch(`/api/pipelines/${id}/stages`)
          .then((r) => r.json())
          .catch(() => []);
        if (!vivo) return;
        setEtapasPorFunil((prev) =>
          prev[id] ? prev : { ...prev, [id]: comoLista<PipelineStage>(lista, "stages") }
        );
      }
    })();
    return () => {
      vivo = false;
    };
  }, [chaveFunis]);

  // `null` enquanto não se sabe: antes de `/api/templates` responder, e quando ela não
  // devolve lista. Ver PENDENCIAS — é a diferença entre travar e não travar o interruptor.
  const aprovados = useMemo(
    () => (templatesConhecidos ? templatesAprovados(templates) : null),
    [templates, templatesConhecidos]
  );
  const corpos = useMemo(() => corposDeTemplate(templates), [templates]);

  // ── Edição local ─────────────────────────────────────────────────────────────
  const alterar = useCallback((key: string, patch: Partial<Esteira>) => {
    setEsteiras((prev) => prev.map((e) => (e.key === key ? { ...e, ...patch } : e)));
    setSujas((prev) => ({ ...prev, [key]: true }));
    setRetornos((prev) => ({ ...prev, [key]: null }));
  }, []);

  const alterarCampo = useCallback(
    (key: string, campo: "canal_id" | "funil_id" | "etapa_id", valor: string) => {
      // Trocar de funil invalida a etapa: etapa pertence a um funil, e manter o id antigo
      // deixaria a esteira apontando para uma coluna de outro quadro.
      const patch: Partial<Esteira> =
        campo === "funil_id"
          ? { funil_id: valor || null, etapa_id: null }
          : { [campo]: valor || null };
      alterar(key, patch);
    },
    [alterar]
  );

  const alterarToque = useCallback(
    (key: string, indice: number, patch: Partial<Toque>) => {
      setEsteiras((prev) =>
        prev.map((e) =>
          e.key === key
            ? { ...e, toques: e.toques.map((t, i) => (i === indice ? { ...t, ...patch } : t)) }
            : e
        )
      );
      setSujas((prev) => ({ ...prev, [key]: true }));
      setRetornos((prev) => ({ ...prev, [key]: null }));
    },
    []
  );

  // ── Gravação ─────────────────────────────────────────────────────────────────
  /**
   * Um PUT com o estado inteiro do cartão. Ligar/desligar grava junto o que está na tela
   * de propósito: confirmar "ligar" com parâmetros não salvos ligaria a esteira com a
   * configuração ANTIGA — exatamente a surpresa que esta tela existe para evitar.
   */
  const gravar = useCallback(
    async (key: string, ativa: boolean): Promise<boolean> => {
      const e = esteiras.find((x) => x.key === key);
      if (!e) return false;
      setSalvando((prev) => ({ ...prev, [key]: true }));
      setRetornos((prev) => ({ ...prev, [key]: null }));
      try {
        const res = await fetch(`/api/automation/esteiras/${key}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ativa,
            canal_id: e.canal_id,
            funil_id: e.funil_id,
            etapa_id: e.etapa_id,
            toques: e.toques.map((t) => ({
              ordem: t.ordem,
              dias: t.dias,
              template_name: t.template_name,
            })),
          }),
        });
        const corpo = await res.json().catch(() => ({}));
        if (!res.ok) {
          // 409 nao e erro de configuracao: a esteira nao existe no banco. Mandar o
          // usuario "tentar de novo" o faria repetir para sempre — a saida e aplicar a
          // migration e reiniciar a API, e o backend ja escreve isso em `detail`.
          const bloqueio = res.status === 409;
          setRetornos((prev) => ({
            ...prev,
            [key]: {
              tipo: bloqueio ? "bloqueio" : "erro",
              texto:
                corpo?.detail ||
                corpo?.error ||
                (bloqueio ? BLOQUEIO_PADRAO : "Não foi possível salvar."),
            },
          }));
          return false;
        }
        setEsteiras((prev) =>
          prev.map((x) =>
            x.key === key
              ? {
                  ...x,
                  ativa,
                  // Tres retornos possiveis do backend, tres leituras: id resolvido vence
                  // sempre; null COM aviso quer dizer "nao ha etapa de perda neste funil";
                  // null SEM aviso quer dizer "nao havia o que decidir" — mantem o atual.
                  stage_id_perdido:
                    corpo?.stage_id_perdido ?? (corpo?.aviso ? null : x.stage_id_perdido),
                }
              : x
          )
        );
        setRetornos((prev) => ({
          ...prev,
          [key]: corpo?.aviso ? { tipo: "aviso", texto: String(corpo.aviso) } : null,
        }));
        setSujas((prev) => ({ ...prev, [key]: false }));
        return true;
      } catch {
        setRetornos((prev) => ({
          ...prev,
          [key]: { tipo: "erro", texto: "Erro de rede ao salvar." },
        }));
        return false;
      } finally {
        setSalvando((prev) => ({ ...prev, [key]: false }));
      }
    },
    [esteiras]
  );

  // ── Liga/desliga ─────────────────────────────────────────────────────────────
  const alternar = useCallback(
    async (e: Esteira) => {
      // Desligar é a direção segura: não pede confirmação nem conta nada.
      if (e.ativa) {
        await gravar(e.key, false);
        return;
      }
      // Mesma lista que trava o interruptor. Repetida aqui porque o clique pode chegar por
      // teclado antes do re-render, e ligar sem canal/etapa é justamente o que não pode.
      if (pendenciasDe(e, aprovados).length > 0) return;

      setConfirmacao({
        key: e.key,
        nome: e.nome,
        elegiveis: null,
        truncado: false,
        motivo: null,
        carregando: true,
      });
      try {
        const res = await fetch("/api/automation/esteiras/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            campaign_id: e.campaign_id ?? null,
            canal_id: e.canal_id,
            funil_id: e.funil_id,
            etapa_id: e.etapa_id,
            dias: e.toques[0]?.dias ?? null,
            // Sem isto a prévia contaria o relógio errado na esteira de proposta: 3 dias
            // parado na etapa e 3 dias de silêncio dão conjuntos de cards diferentes.
            relogio: e.relogio ?? null,
          }),
        });
        const data = await res.json().catch(() => ({}));
        setConfirmacao((prev) =>
          prev && prev.key === e.key
            ? {
                ...prev,
                carregando: false,
                elegiveis: typeof data?.elegiveis === "number" ? data.elegiveis : null,
                truncado: Boolean(data?.truncado),
                motivo: data?.motivo ?? null,
              }
            : prev
        );
      } catch {
        setConfirmacao((prev) =>
          prev && prev.key === e.key
            ? { ...prev, carregando: false, elegiveis: null, motivo: "rpc_indisponivel" }
            : prev
        );
      }
    },
    [gravar, aprovados]
  );

  const confirmarLigar = useCallback(async () => {
    if (!confirmacao) return;
    const key = confirmacao.key;
    setConfirmacao(null);
    await gravar(key, true);
  }, [confirmacao, gravar]);

  // ── Render ───────────────────────────────────────────────────────────────────
  const porKey = useMemo(() => new Map(esteiras.map((e) => [e.key, e])), [esteiras]);
  const conhecidas = new Set(GRUPOS.flatMap((g) => g.keys));
  const grupos = [
    ...GRUPOS.map((g) => ({ ...g, itens: g.keys.map((k) => porKey.get(k)).filter(Boolean) as Esteira[] })),
    {
      titulo: "Outras",
      resumo: "Esteiras que o backend devolveu e esta tela ainda não conhece.",
      keys: [],
      itens: esteiras.filter((e) => !conhecidas.has(e.key)),
    },
  ].filter((g) => g.itens.length > 0);

  if (carregando) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-40 bg-[#f0ede8] rounded-[8px] animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header className="max-w-2xl">
        <h2 style={{ letterSpacing: "-0.3px" }} className="text-[20px] font-normal text-[#111111]">
          Esteiras
        </h2>
        <p className="text-[13px] text-[#7b7b78] mt-1 leading-relaxed">
          Rotinas que trabalham o funil quando ninguém trabalha. Você escolhe o prazo e a
          mensagem; o resto é fixo de propósito. Elas nascem desligadas — configure primeiro,
          ligue depois, uma de cada vez.
        </p>
      </header>

      {falhaCarga && (
        <div className="bg-[#fef0f0] border border-[#f3d0d0] rounded-[8px] px-4 py-3 text-[13px] text-[#c41c1c]">
          {falhaCarga}
        </div>
      )}

      {!falhaCarga && esteiras.length === 0 && (
        <div className="bg-white border border-[#dedbd6] rounded-[8px] py-12 text-center">
          <p className="text-[14px] text-[#7b7b78]">
            Nenhuma esteira encontrada. Elas são criadas quando o backend sobe.
          </p>
        </div>
      )}

      {grupos.map((g) => (
        <section key={g.titulo} className="space-y-3">
          <div className="flex items-baseline gap-3">
            <h3 className="text-[11px] uppercase tracking-[0.8px] text-[#111111] font-medium">
              {g.titulo}
            </h3>
            <span className="text-[12px] text-[#7b7b78]">{g.resumo}</span>
            <span aria-hidden className="flex-1 h-px bg-[#e6e2dc]" />
          </div>
          <div className="space-y-3">
            {g.itens.map((e) => (
              <CartaoEsteira
                key={e.key}
                esteira={e}
                canais={canais}
                funis={funis}
                etapas={(e.funil_id && etapasPorFunil[e.funil_id]) || []}
                etapasCarregadas={Boolean(e.funil_id && etapasPorFunil[e.funil_id])}
                aprovados={aprovados}
                corpos={corpos}
                sujo={Boolean(sujas[e.key])}
                salvando={Boolean(salvando[e.key])}
                retorno={retornos[e.key] ?? null}
                onCampo={(campo, valor) => alterarCampo(e.key, campo, valor)}
                onToque={(i, patch) => alterarToque(e.key, i, patch)}
                onSalvar={() => gravar(e.key, e.ativa)}
                onAlternar={() => alternar(e)}
              />
            ))}
          </div>
        </section>
      ))}

      {confirmacao && (
        <DialogoLigar
          confirmacao={confirmacao}
          onCancelar={() => setConfirmacao(null)}
          onConfirmar={confirmarLigar}
        />
      )}
    </div>
  );
}

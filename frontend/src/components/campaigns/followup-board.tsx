"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { objectiveLabel, touchStateLabel } from "@/lib/cadence-display";
import {
  BOARD_STATUSES,
  type BoardJob,
  type BoardStatus,
  STATUS_FILTER_LABELS,
  displayInstant,
  formatBRT,
  isCancellable,
  offsetLabel,
  touchTypeLabel,
} from "@/lib/followup-board";

type DefinitionTouch = {
  sequence: number;
  offset_hours: number;
  jitter_minutes: number[] | null;
  objective: string;
};

/** Um toque do João, já RESOLVIDO (banco sobreposto ao código) pelo backend.
 *
 * `*_codigo` vem junto de propósito: é o que deixa a tela mostrar "padrão 45" ao lado
 * do 60 gravado. Sem isso ninguém descobre o que a configuração mudou nem como voltar.
 */
type JoaoTouch = {
  sequence: number;
  dias: number;
  dias_codigo: number;
  template_name: string | null;
  template_name_codigo: string | null;
  aceita_adiamento: boolean;
};

/** Uma cadência DENTRO de um funil — fusão do que antes era `JoaoCadencia` (topo:
 * gatilho, `ativa`, `pode_ligar`) com o que antes era `JoaoLinha` (`toques`,
 * `toques_sem_template`), menos `pipeline_id`, que sobe para `JoaoFunil` (spec
 * 2026-09-21 §8). Cadência deixa de ser navegável sozinha — vive sempre dentro de um
 * funil. */
type JoaoCadenciaDoFunil = {
  codigo: string;
  rotulo: string;
  job_type: string;
  gatilho_stage_key: string;
  /** Rótulo hardcoded em `cadence_joao.py` (decisão 2 da spec) — NUNCA lido do banco. */
  gatilho_stage_rotulo: string;
  gatilho_dias: number;
  gatilho_dias_codigo: number;
  ativa: boolean;
  repete_ultimo: boolean;
  /** Só a metade que não depende da Meta: "todo toque tem NOME de template". */
  pode_ligar: boolean;
  toques: JoaoTouch[];
  toques_sem_template: number[];
};

/** Um dos cinco funis do João. `cadencias: []` para "João - Recuperação" — espaço
 * reservado de propósito (spec §1), não um erro de carregamento. */
type JoaoFunil = {
  codigo: string;
  rotulo: string;
  pipeline_id: string;
  cadencias: JoaoCadenciaDoFunil[];
};

/**
 * O payload de `GET /api/cadence/definition`.
 *
 * As quatro chaves do TOPO são a cadência da ValerIA e estão em produção — este
 * componente é o único consumidor delas. `valeria` é o MESMO dicionário espelhado
 * para o seletor, e `joao` é a chave nova. `joao` é OPCIONAL porque o CRM e o FastAPI
 * sobem separados: um frontend novo contra um backend antigo tem de mostrar a esteira
 * da ValerIA normalmente, sem o seletor.
 */
type CadenceDefinition = {
  touches: DefinitionTouch[];
  outbound_nudge: DefinitionTouch;
  min_gap_hours: number;
  business_window: { start: string; end: string; days: string; timezone: string };
  joao?: { funis: JoaoFunil[] } | null;
};

/** Um motivo de recusa do PUT — `funil`/`sequence` dizem QUAL toque é o culpado.
 *
 * Campo `funil` (antes `linha`): cada PUT agora é sempre um funil só (spec
 * 2026-09-21), então o problema aponta o funil do próprio pedido. */
type Problema = {
  codigo: string;
  mensagem: string;
  cadencia?: string | null;
  funil?: string | null;
  sequence?: number | null;
};

/** O que o operador mudou e ainda não salvou, de UM par (funil, cadência).
 *
 * Guardar só o que MUDOU é o que faz o PUT ser MERGE de verdade: o backend trata
 * campo ausente como "não mexe" e `null` como "volta a valer o código". Mandar o
 * objeto inteiro transformaria cada gravação num replace, e um `dias` reenviado por
 * inércia viraria sobreposição permanente de um valor que ninguém escolheu.
 */
type ToqueEditado = { dias?: number | null; template_name?: string | null };
type Rascunho = {
  gatilho_dias?: number | null;
  ativa?: boolean;
  /** sequence → campos editados — já é de UMA cadência de UM funil só, sem
   * aninhamento por linha. */
  toques: Record<number, ToqueEditado>;
};

const RASCUNHO_VAZIO: Rascunho = { toques: {} };

/** A chave composta do estado de rascunho — evita um segundo nível de `Record`
 * só para separar cadência de funil (spec §8). */
function chaveRascunho(funilCodigo: string, cadenciaCodigo: string): string {
  return `${funilCodigo}:${cadenciaCodigo}`;
}

type Summary = {
  pending: number;
  awaiting_reopen: number;
  sent_today: number;
  sent_week: number;
};

type BoardRow = BoardJob & { conversation_id: string | null };

const STATUS_BADGE_STYLES: Record<string, string> = {
  pending: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  awaiting_reopen: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  sent: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
  cancelled: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
};

function KpiCard({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}</p>
      <p className="text-[28px] font-normal text-[#111111] mt-1" style={{ letterSpacing: "-0.5px" }}>
        {value ?? "—"}
      </p>
    </div>
  );
}

/** A esteira da ValerIA — SÓ LEITURA, e é uma decisão do spec §6.
 *
 * O que definiria cada toque dela é o `objective_prompt`, texto de LLM: editá-lo por
 * uma caixinha de tela seria mover prompt de produção para fora da revisão de código.
 * Os dias dela também não entram aqui: a cadência da ValerIA roda dentro da janela de
 * 24h da Meta, onde o espaçamento é parte do desenho do prompt, não configuração.
 */
function ValeriaStrip({ definition }: { definition: CadenceDefinition }) {
  const steps = definition.touches.map((t) => ({
    title: `T${t.sequence}`,
    offset: offsetLabel(t.offset_hours, t.jitter_minutes),
    objective: objectiveLabel(t.objective),
  }));
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <h3 style={{ letterSpacing: "-0.3px" }} className="text-[18px] font-medium text-[#111111]">
          Esteira da cadência (motor da Valéria)
        </h3>
        <span className="text-[12px] text-[#7b7b78]">
          janela comercial {definition.business_window.start}–{definition.business_window.end} ({definition.business_window.days}) · gap mínimo {definition.min_gap_hours}h
        </span>
      </div>
      <div className="flex flex-wrap items-stretch gap-2">
        {steps.map((s, i) => (
          <div key={s.title} className="flex items-center gap-2">
            <div className="border border-[#dedbd6] rounded-[6px] px-3 py-2 bg-[#faf9f6] min-w-[130px]">
              <p className="text-[12px] font-medium text-[#111111]">
                {s.title} <span className="text-[#7b7b78] font-normal">· {s.offset}</span>
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-0.5">{s.objective}</p>
            </div>
            {i < steps.length - 1 && <span className="text-[#dedbd6]">→</span>}
          </div>
        ))}
      </div>
      <p className="text-[12px] text-[#7b7b78] mt-3">
        Lead outbound "sim-e-sumiu": T1 é substituído pelo nudge (+
        {definition.outbound_nudge.offset_hours}h, dentro da janela de 24h da Meta). Toque
        que vence com a janela fechada vira template de reabertura e os seguintes se
        dobram nele (aguardando reabertura). O objetivo de cada toque é prompt de LLM e
        vive no código — por isso esta esteira é só leitura.
      </p>
    </>
  );
}

/** `message_templates.status`: o sync local grava minúsculo, a Meta manda 'APPROVED'. */
function aprovado(status: string | null | undefined): boolean {
  return (status ?? "").toLowerCase() === "approved";
}

/** Vazio vira `null` de propósito: no backend, `null` explícito é "apaga a
 *  sobreposição e volta a valer o código" — é o botão de desfazer desta tela. */
function numeroOuNulo(valor: string): number | null {
  const limpo = valor.trim();
  if (!limpo) return null;
  const n = Number(limpo);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

/**
 * A recusa do backend, transformada em algo que uma pessoa lê.
 *
 * O formato real é `400 {"detail": {"problemas": [...]}}` (FastAPI embrulha o `detail`).
 * Tolerar também `{"problemas": [...]}` na raiz é barato e cobre proxy que desembrulhe.
 * E o último recurso NUNCA é silêncio: sem lista, mostra o texto do erro ou o status —
 * "a tela ficou muda" é exatamente a falha de 16/09/2026 que esta função existe para
 * impedir.
 */
function extrairProblemas(corpo: unknown, status: number): Problema[] {
  const raiz = (corpo ?? {}) as Record<string, unknown>;
  const detail = raiz.detail;
  const candidatas = [
    (detail as Record<string, unknown> | undefined)?.problemas,
    raiz.problemas,
  ];
  for (const lista of candidatas) {
    if (Array.isArray(lista) && lista.length > 0) return lista as Problema[];
  }
  const texto =
    typeof detail === "string"
      ? detail
      : typeof raiz.error === "string"
        ? raiz.error
        : null;
  return [
    {
      codigo: "recusado",
      mensagem: texto ?? `O backend respondeu ${status} e não disse por quê.`,
    },
  ];
}

function rotuloDoFunil(funis: JoaoFunil[], funil: string | null | undefined): string {
  if (!funil) return "";
  return funis.find((f) => f.codigo === funil)?.rotulo ?? funil;
}

const CAMPO =
  "border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[13px] text-[#111111] bg-white";
const ROTULO_CAMPO = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]";

/**
 * O editor das cadências do João, navegado por FUNIL primeiro (spec 2026-09-21).
 *
 * Nível 1: os cinco funis (`funil.rotulo` — nome completo, ex. "João - Reposição
 * Atacado"). Nível 2, dentro do funil selecionado: as cadências dele (no máximo 2).
 * Recuperação (`cadencias: []`) é espaço reservado de propósito — mostra um estado
 * vazio em vez de tentar renderizar um editor sem nada para editar.
 *
 * Dentro de uma cadência: dias de cada toque, template de cada toque, prazo do
 * gatilho, liga/desliga. NÃO existe "adicionar toque" — mudar a forma da cadência é
 * mudança de código, e é isso que impede esta tela de virar um builder de novo. O
 * backend recusa `sequence` fora do que o código declara, então um botão aqui só
 * produziria uma recusa.
 */
function JoaoEditor({ funis: iniciais }: { funis: JoaoFunil[] }) {
  const [funis, setFunis] = useState<JoaoFunil[]>(iniciais);
  const [funilCodigo, setFunilCodigo] = useState<string>(iniciais[0]?.codigo ?? "");
  const [cadenciaCodigo, setCadenciaCodigo] = useState<string>(
    iniciais[0]?.cadencias[0]?.codigo ?? "",
  );
  const [rascunhos, setRascunhos] = useState<Record<string, Rascunho>>({});
  const [templates, setTemplates] = useState<{ name: string; status: string }[] | null>(null);
  const [problemas, setProblemas] = useState<Problema[] | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => setFunis(iniciais), [iniciais]);

  // A MESMA fonte de templates do builder de campanhas (`/api/templates`, que lê
  // `message_templates` e já colapsa a linha-espelho por canal). Uma segunda fonte
  // divergiria da primeira no primeiro sync.
  useEffect(() => {
    let vivo = true;
    fetch("/api/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (vivo) setTemplates(Array.isArray(d) ? d : []);
      })
      .catch(() => {
        if (vivo) setTemplates([]);
      });
    return () => {
      vivo = false;
    };
  }, []);

  const aprovados = useMemo(() => {
    const nomes = new Set<string>();
    for (const t of templates ?? []) if (aprovado(t.status)) nomes.add(t.name);
    return Array.from(nomes).sort();
  }, [templates]);

  const funil = funis.find((f) => f.codigo === funilCodigo) ?? funis[0];
  const cadencia =
    funil?.cadencias.find((c) => c.codigo === cadenciaCodigo) ?? funil?.cadencias[0] ?? null;
  const chave = chaveRascunho(funil?.codigo ?? "", cadencia?.codigo ?? "");
  const rascunho = rascunhos[chave] ?? RASCUNHO_VAZIO;

  const editado = (sequence: number): ToqueEditado => rascunho.toques[sequence] ?? {};
  const diasEfetivo = (t: JoaoTouch): number | null => {
    const e = editado(t.sequence);
    return "dias" in e ? (e.dias ?? null) : t.dias;
  };
  const templateEfetivo = (t: JoaoTouch): string | null => {
    const e = editado(t.sequence);
    return "template_name" in e ? (e.template_name ?? null) : t.template_name;
  };
  const gatilhoEfetivo =
    "gatilho_dias" in rascunho ? (rascunho.gatilho_dias ?? null) : (cadencia?.gatilho_dias ?? null);
  const ativaEfetiva = "ativa" in rascunho ? !!rascunho.ativa : !!cadencia?.ativa;

  const limparAvisos = () => {
    setProblemas(null);
    setSucesso(null);
  };

  const selecionarFunil = (codigo: string) => {
    setFunilCodigo(codigo);
    const alvo = funis.find((f) => f.codigo === codigo);
    setCadenciaCodigo(alvo?.cadencias[0]?.codigo ?? "");
    limparAvisos();
  };

  const selecionarCadencia = (codigo: string) => {
    setCadenciaCodigo(codigo);
    limparAvisos();
  };

  const editarToque = (sequence: number, campos: ToqueEditado) => {
    limparAvisos();
    setRascunhos((prev) => {
      const atual = prev[chave] ?? RASCUNHO_VAZIO;
      const novosToques = { ...atual.toques, [sequence]: { ...(atual.toques[sequence] ?? {}), ...campos } };
      return { ...prev, [chave]: { ...atual, toques: novosToques } };
    });
  };

  const editarCadencia = (campos: Partial<Rascunho>) => {
    limparAvisos();
    setRascunhos((prev) => {
      const atual = prev[chave] ?? RASCUNHO_VAZIO;
      return { ...prev, [chave]: { ...atual, ...campos } };
    });
  };

  const salvar = async () => {
    limparAvisos();
    if (!funil || !cadencia) return;

    // SEMPRE 1 PUT por rascunho: já não existe "aplicar nas duas linhas" (Atacado e
    // Private Label deixaram de estar acoplados, spec §2 decisão 1) — cada par
    // (funil, cadência) é uma entidade só sua.
    const corpo: Record<string, unknown> = { funil: funil.codigo, cadencia: cadencia.codigo };
    let temAlgo = false;
    if (Object.keys(rascunho.toques).length > 0) {
      corpo.toques = rascunho.toques;
      temAlgo = true;
    }
    if ("gatilho_dias" in rascunho) {
      corpo.gatilho_dias = rascunho.gatilho_dias;
      temAlgo = true;
    }
    if ("ativa" in rascunho) {
      corpo.ativa = rascunho.ativa;
      temAlgo = true;
    }

    if (!temAlgo) {
      setSucesso("Nada mudou para salvar.");
      return;
    }

    setSalvando(true);
    try {
      const res = await fetch("/api/cadence/joao", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
      });
      const body = await res.json().catch(() => null);
      // A recusa TEM que aparecer. Seguir em frente aqui — ou tratar 400 como
      // sucesso — é literalmente o bug de 16/09/2026 no builder de campanhas: o
      // backend recusava certo e a interface ficava muda.
      if (!res.ok) {
        setProblemas(extrairProblemas(body, res.status));
        return;
      }
      if (body && typeof body === "object" && "codigo" in (body as object)) {
        const atualizada = body as JoaoCadenciaDoFunil;
        const funilAlvo = funil;
        setFunis((prev) =>
          prev.map((f) =>
            f.codigo === funilAlvo.codigo
              ? {
                  ...f,
                  cadencias: f.cadencias.map((c) =>
                    c.codigo === atualizada.codigo ? atualizada : c,
                  ),
                }
              : f,
          ),
        );
      }
      setRascunhos((prev) => {
        const copia = { ...prev };
        delete copia[chave];
        return copia;
      });
      setSucesso("Configuração salva.");
    } catch (e) {
      setProblemas([
        { codigo: "rede", mensagem: `Não deu para falar com o servidor: ${e}` },
      ]);
    } finally {
      setSalvando(false);
    }
  };

  return (
    <>
      <div className="flex flex-wrap gap-2 mb-4">
        {funis.map((f) => (
          <button
            key={f.codigo}
            onClick={() => selecionarFunil(f.codigo)}
            aria-pressed={f.codigo === funil?.codigo}
            className={`px-3 py-1.5 rounded-[4px] text-[13px] border transition-colors ${
              f.codigo === funil?.codigo
                ? "bg-[#111111] text-white border-[#111111]"
                : "bg-transparent text-[#7b7b78] border-[#dedbd6] hover:text-[#111111]"
            }`}
          >
            {f.rotulo}
          </button>
        ))}
      </div>

      {funil && funil.cadencias.length === 0 && (
        <p className="text-[13px] text-[#7b7b78]">
          Nenhuma cadência configurada ainda para este funil.
        </p>
      )}

      {funil && cadencia && (
        <>
          <div className="flex flex-wrap gap-2 mb-4">
            {funil.cadencias.map((c) => (
              <button
                key={c.codigo}
                onClick={() => selecionarCadencia(c.codigo)}
                aria-pressed={c.codigo === cadencia.codigo}
                className={`px-3 py-1.5 rounded-[4px] text-[13px] border transition-colors ${
                  c.codigo === cadencia.codigo
                    ? "bg-[#111111] text-white border-[#111111]"
                    : "bg-transparent text-[#7b7b78] border-[#dedbd6] hover:text-[#111111]"
                }`}
              >
                {c.rotulo}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="text-[15px] font-medium text-[#111111]">{cadencia.rotulo}</h4>
              <p className="text-[12px] text-[#7b7b78] mt-0.5">
                Dispara com o card parado {gatilhoEfetivo ?? cadencia.gatilho_dias_codigo} dia(s)
                na etapa {cadencia.gatilho_stage_rotulo}
                {cadencia.repete_ultimo && " · o último toque se repete até o lead pedir para parar"}
              </p>
            </div>
            <label className="flex items-center gap-2 text-[13px] text-[#111111]">
              <input
                type="checkbox"
                aria-label="Ligar cadência"
                checked={ativaEfetiva}
                onChange={(e) => editarCadencia({ ativa: e.target.checked })}
              />
              <span>{ativaEfetiva ? "Ativa" : "Desligada"}</span>
            </label>
          </div>

          <div className="flex items-center gap-2 mt-3">
            <span className={ROTULO_CAMPO}>Prazo do gatilho (dias)</span>
            <input
              type="number"
              min={1}
              aria-label="Prazo do gatilho (dias)"
              value={gatilhoEfetivo ?? ""}
              placeholder={String(cadencia.gatilho_dias_codigo)}
              onChange={(e) => editarCadencia({ gatilho_dias: numeroOuNulo(e.target.value) })}
              className={`${CAMPO} w-[84px]`}
            />
            <span className="text-[11px] text-[#7b7b78]">
              padrão {cadencia.gatilho_dias_codigo} · vazio volta ao padrão
            </span>
          </div>

          <div className="border-t border-[#f0ede8] mt-4 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[13px] font-medium text-[#111111]">Toques</p>
              {cadencia.toques_sem_template.length > 0 && (
                <span className="text-[11px] text-[#c41c1c]">
                  {cadencia.toques_sem_template.length} toque(s) sem template — não dá para ligar
                </span>
              )}
            </div>
            <div className="mt-2 space-y-2">
              {cadencia.toques.map((t) => {
                const dias = diasEfetivo(t);
                const template = templateEfetivo(t);
                return (
                  <div key={t.sequence} className="flex flex-wrap items-center gap-2">
                    <span className="text-[12px] font-medium text-[#111111] w-[28px]">
                      T{t.sequence}
                    </span>
                    <input
                      type="number"
                      min={0}
                      aria-label={`Dias do toque ${t.sequence}`}
                      value={dias ?? ""}
                      placeholder={String(t.dias_codigo)}
                      onChange={(e) =>
                        editarToque(t.sequence, { dias: numeroOuNulo(e.target.value) })
                      }
                      className={`${CAMPO} w-[74px]`}
                    />
                    <span className="text-[11px] text-[#7b7b78]">dias · padrão {t.dias_codigo}</span>
                    {templates === null ? (
                      <span className="text-[12px] text-[#7b7b78]">carregando templates…</span>
                    ) : (
                      <select
                        aria-label={`Template do toque ${t.sequence}`}
                        value={template ?? ""}
                        onChange={(e) =>
                          editarToque(t.sequence, {
                            template_name: e.target.value || null,
                          })
                        }
                        className={`${CAMPO} min-w-[230px]`}
                      >
                        <option value="">— sem template —</option>
                        {/* O que está gravado, mas não está entre os aprovados, continua
                            visível: esconder trocaria o valor do banco por um vazio no
                            primeiro clique em Salvar, sem ninguém pedir. */}
                        {template && !aprovados.includes(template) && (
                          <option value={template}>{template} (fora dos aprovados)</option>
                        )}
                        {aprovados.map((nome) => (
                          <option key={nome} value={nome}>
                            {nome}
                          </option>
                        ))}
                      </select>
                    )}
                    {t.aceita_adiamento && (
                      <span
                        title={
                          'O template deste toque traz o botão "Ainda tenho estoque": a ' +
                          "resposta adia 60 dias sem recomeçar a cadência. É config do " +
                          "código, não da tela."
                        }
                        className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] px-1.5 py-0.5"
                      >
                        Aceita adiamento
                      </span>
                    )}
                    {!template && (
                      <span className="text-[11px] text-[#c41c1c]">sem template</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {problemas && problemas.length > 0 && (
            <div
              role="alert"
              className="mt-4 border border-[#c41c1c]/30 bg-[#c41c1c]/5 rounded-[6px] p-3"
            >
              <p className="text-[13px] font-medium text-[#c41c1c]">
                O backend recusou — nada foi gravado:
              </p>
              <ul className="mt-2 space-y-1.5">
                {problemas.map((p, i) => (
                  <li key={`${p.codigo}-${i}`} className="text-[12px] text-[#111111]">
                    {p.sequence != null ? (
                      <strong className="font-medium">
                        Toque {p.sequence}
                        {p.funil ? ` · ${rotuloDoFunil(funis, p.funil)}` : ""} —{" "}
                      </strong>
                    ) : null}
                    {p.mensagem}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3 mt-4">
            <button
              onClick={salvar}
              disabled={salvando}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] disabled:opacity-50"
            >
              {salvando ? "Salvando..." : "Salvar"}
            </button>
            {sucesso && <span className="text-[13px] text-[#0f9d43]">{sucesso}</span>}
            {!cadencia.pode_ligar && (
              <span className="text-[12px] text-[#7b7b78]">
                Ligar exige template aprovado em todo toque desta cadência.
              </span>
            )}
          </div>
        </>
      )}
    </>
  );
}

/**
 * A faixa da definição — agora com DOIS motores.
 *
 * O seletor só aparece quando o backend manda o bloco `joao`: CRM e FastAPI sobem
 * separados, e um frontend novo contra um backend antigo tem de continuar mostrando a
 * esteira da ValerIA, que é o único follow-up que roda em produção hoje.
 */
export function DefinitionStrip({ definition }: { definition: CadenceDefinition | null }) {
  const [motor, setMotor] = useState<"valeria" | "joao">("valeria");

  if (!definition) {
    return (
      <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
        <p className="text-[13px] text-[#7b7b78]">Definição da cadência indisponível</p>
      </div>
    );
  }

  const funisJoao = definition.joao?.funis ?? [];
  const temJoao = funisJoao.length > 0;
  const noJoao = temJoao && motor === "joao";

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      {temJoao && (
        <div className="flex gap-2 mb-4" role="group" aria-label="Motor de follow-up">
          {(["valeria", "joao"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMotor(m)}
              aria-pressed={motor === m}
              className={`px-3 py-1.5 rounded-[4px] text-[13px] border transition-colors ${
                motor === m
                  ? "bg-[#111111] text-white border-[#111111]"
                  : "bg-transparent text-[#7b7b78] border-[#dedbd6] hover:text-[#111111]"
              }`}
            >
              {m === "valeria" ? "Valéria" : "João"}
            </button>
          ))}
        </div>
      )}
      {noJoao ? (
        <JoaoEditor funis={funisJoao} />
      ) : (
        <ValeriaStrip definition={definition} />
      )}
    </div>
  );
}

export function FollowupBoard() {
  const router = useRouter();
  const [definition, setDefinition] = useState<CadenceDefinition | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [statusFilter, setStatusFilter] = useState<BoardStatus>("pending");
  const [jobs, setJobs] = useState<BoardRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<BoardRow | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const loadSummary = useCallback(() => {
    fetch("/api/followups/summary")
      .then((r) => r.json())
      .then((d) => setSummary(d.error ? null : d))
      .catch(() => setSummary(null));
  }, []);

  const loadJobs = useCallback((status: BoardStatus) => {
    setJobs(null);
    setLoadError(null);
    fetch(`/api/followups?status=${status}&limit=100`)
      .then((r) => r.json())
      .then((d) => {
        if (Array.isArray(d)) setJobs(d);
        else setLoadError(d.error ?? "Resposta inesperada");
      })
      .catch((e) => setLoadError(String(e)));
  }, []);

  useEffect(() => {
    fetch("/api/cadence/definition")
      .then((r) => r.json())
      .then((d) => setDefinition(d.error ? null : d))
      .catch(() => setDefinition(null));
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadJobs(statusFilter);
  }, [statusFilter, loadJobs]);

  const confirmCancel = async () => {
    if (!cancelTarget) return;
    setCancelling(true);
    try {
      const res = await fetch(`/api/followups/${cancelTarget.id}/cancel`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) {
        setToast(`Não foi possível cancelar: ${body.error ?? res.statusText}`);
      } else {
        setToast("Toque cancelado");
        loadJobs(statusFilter);
        loadSummary();
      }
    } catch (e) {
      setToast(`Erro de rede: ${e}`);
    } finally {
      setCancelling(false);
      setCancelTarget(null);
      setTimeout(() => setToast(null), 6000);
    }
  };

  return (
    <div className="space-y-6">
      <DefinitionStrip definition={definition} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        <KpiCard label="Pendentes" value={summary?.pending ?? null} />
        <KpiCard label="Aguardando reabertura" value={summary?.awaiting_reopen ?? null} />
        <KpiCard label="Enviados hoje" value={summary?.sent_today ?? null} />
        <KpiCard label="Enviados (7 dias)" value={summary?.sent_week ?? null} />
      </div>

      <div className="bg-white border border-[#dedbd6] rounded-[8px]">
        <div className="p-4 border-b border-[#dedbd6] flex flex-wrap items-center gap-2">
          {BOARD_STATUSES.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-[4px] text-[13px] border transition-colors ${
                statusFilter === s
                  ? "bg-[#111111] text-white border-[#111111]"
                  : "bg-transparent text-[#7b7b78] border-[#dedbd6] hover:text-[#111111]"
              }`}
            >
              {STATUS_FILTER_LABELS[s]}
            </button>
          ))}
        </div>

        {loadError && (
          <p className="text-[14px] text-[#c41c1c] p-6">Erro ao carregar: {loadError}</p>
        )}
        {!loadError && jobs === null && (
          <div className="p-6 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-10 rounded-[4px] animate-pulse bg-[#f0ede8]" />
            ))}
          </div>
        )}
        {!loadError && jobs !== null && jobs.length === 0 && (
          <p className="text-[14px] text-[#7b7b78] p-6 text-center">
            Nenhum toque {STATUS_FILTER_LABELS[statusFilter].toLowerCase()}
          </p>
        )}
        {!loadError && jobs !== null && jobs.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] border-b border-[#dedbd6]">
                  <th className="px-4 py-3 font-medium">Lead</th>
                  <th className="px-4 py-3 font-medium">Toque</th>
                  <th className="px-4 py-3 font-medium">Objetivo</th>
                  <th className="px-4 py-3 font-medium">Situação</th>
                  <th className="px-4 py-3 font-medium">Quando (BRT)</th>
                  <th className="px-4 py-3 font-medium text-right">Ação</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6]">
                    <td className="px-4 py-3">
                      <button
                        onClick={() => j.lead_id && router.push(`/conversas?lead_id=${j.lead_id}`)}
                        className="text-[14px] text-[#111111] hover:underline text-left"
                        title="Abrir conversa"
                      >
                        {j.lead_name || j.lead_phone || "—"}
                      </button>
                      {j.lead_name && j.lead_phone && (
                        <p className="text-[12px] text-[#7b7b78]">{j.lead_phone}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[14px] text-[#111111]">{touchTypeLabel(j)}</td>
                    <td className="px-4 py-3 text-[13px] text-[#7b7b78]">{objectiveLabel(j.objetivo)}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${STATUS_BADGE_STYLES[j.status] ?? STATUS_BADGE_STYLES.cancelled}`}
                      >
                        {touchStateLabel(j)}
                      </span>
                      {j.status === "cancelled" && j.cancel_reason && (
                        <p className="text-[11px] text-[#7b7b78] mt-1">{j.cancel_reason}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[13px] text-[#7b7b78]">{formatBRT(displayInstant(j))}</td>
                    <td className="px-4 py-3 text-right">
                      {isCancellable(j) && (
                        <button
                          onClick={() => setCancelTarget(j)}
                          className="text-[13px] text-[#c41c1c] border border-[#c41c1c]/30 px-3 py-1 rounded-[4px] hover:bg-[#c41c1c]/5 transition-colors"
                        >
                          Cancelar
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {cancelTarget && (
        <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-md p-6">
            <h2 className="text-[16px] font-medium text-[#111111] mb-2">Cancelar toque?</h2>
            <p className="text-[14px] text-[#7b7b78] mb-4">
              {touchTypeLabel(cancelTarget)} de{" "}
              <span className="text-[#111111]">
                {cancelTarget.lead_name || cancelTarget.lead_phone || "lead"}
              </span>{" "}
              agendado para {formatBRT(displayInstant(cancelTarget))} não será enviado. Essa
              ação não pode ser desfeita.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setCancelTarget(null)}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px]"
              >
                Voltar
              </button>
              <button
                onClick={confirmCancel}
                disabled={cancelling}
                className="bg-[#c41c1c] text-white px-[14px] py-2 rounded-[4px] text-[14px] disabled:opacity-50"
              >
                {cancelling ? "Cancelando..." : "Cancelar toque"}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#111111] text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg flex items-center gap-3">
          <span>{toast}</span>
          <button onClick={() => setToast(null)} className="text-white/60 hover:text-white leading-none text-lg">
            &times;
          </button>
        </div>
      )}
    </div>
  );
}

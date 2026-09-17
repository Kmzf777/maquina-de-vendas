"use client";

import { useState, useEffect } from "react";
import type { CampaignNodeType } from "@/lib/types";
import type { InspectorProps, FlowTemplate } from "./types";
import { NODE_META, TRIGGER_LABELS, ACTION_LABELS, CONDITION_LABELS } from "./constants";
import { describeNode } from "./describe-node";
import { renderTemplateBody } from "./render-template-body";
import { useNodeSchema, findNodeType, fixedValues, type NodeSchemaField } from "@/lib/node-schema";

/**
 * O painel de configuração do nó, DERIVADO do contrato
 * (`backend/app/campaigns/node_registry.py`, servido em
 * `GET /api/campaigns/node-schema`).
 *
 * A regra que faz este arquivo existir: **o controle é escolhido pelo `vocab` do
 * campo, nunca pelo nome do subtipo.** Enquanto era pelo subtipo, `stage_filter`
 * tinha um único <select> servindo dois vocabulários incompatíveis — as colunas do
 * Kanban, gravando o RÓTULO ("Em conversa") — enquanto o motor comparava com
 * `leads.stage` (segmento do lead) em quatro gatilhos e com `pipeline_stages.key` num
 * quinto. Cinco dos doze gatilhos nunca casavam, sem um único log.
 *
 * A consequência prática: vocabulário novo no registro ganha um renderizador AQUI, e
 * todo campo que o declare herda o comportamento certo — inclusive campo que ainda
 * não foi escrito.
 */

// ─── Funis ──────────────────────────────────────────────────────────────────────
//
// `FlowBuilderData` traz as COLUNAS (`allStages`), não os funis, e o vocabulário
// `funil_id` precisa do uuid do pipeline — é ele que decide onde `create_deal` cria o
// card (sem ele o motor cai no "primeiro pipeline do banco", em silêncio). Cache de
// módulo: a lista é a mesma para todos os nós da tela.
type Funil = { id: string; name: string };
let funisCache: Funil[] | null = null;
let funisInflight: Promise<Funil[]> | null = null;

function useFunis(): Funil[] {
  const [funis, setFunis] = useState<Funil[]>(() => funisCache ?? []);
  useEffect(() => {
    if (funisCache) { setFunis(funisCache); return; }
    let vivo = true;
    if (!funisInflight) {
      funisInflight = fetch("/api/pipelines")
        .then(r => (r.ok ? r.json() : []))
        .then((rows: unknown) => {
          funisCache = Array.isArray(rows) ? (rows as Funil[]) : [];
          return funisCache;
        })
        .catch(() => [] as Funil[])
        .finally(() => { funisInflight = null; });
    }
    void funisInflight.then(rows => { if (vivo) setFunis(rows); });
    return () => { vivo = false; };
  }, []);
  return funis;
}

// ─── mapa_botoes ────────────────────────────────────────────────────────────────
//
// `on_reply_por_botao` é `{rótulo do botão → política de saída}` e tem vocabulário
// PRÓPRIO, separado do `mapa` de `template_variables`. Os dois guardam um dicionário e
// é só o que têm em comum: `mapa` é indexado pelos PARÂMETROS do template escolhido — e
// o controle dele, corretamente, começa pedindo um template —, enquanto este é indexado
// pelo RÓTULO que o lead vê no botão, existe em nó `send_text` (que não tem template
// nenhum) e o valor de cada chave é vocabulário fechado (`politica_resposta`).
//
// Enquanto os dois eram `mapa`, este campo renderizava "Escolha um template para
// configurar as variáveis" no texto livre e input de parâmetro no template: declarado no
// contrato e inutilizável na tela. A cura NÃO é `if (campo.chave === "on_reply_por_botao")`
// — acoplar renderizador a NOME de campo é a forma exata do bug original, onde um único
// <select> decidia a lista pelo subtipo do gatilho em vez de pelo vocabulário.

type ParDeBotao = { rotulo: string; politica: string };

function paresDoMapa(valor: unknown): ParDeBotao[] {
  if (!valor || typeof valor !== "object" || Array.isArray(valor)) return [];
  return Object.entries(valor as Record<string, unknown>).map(([rotulo, politica]) => ({
    rotulo,
    politica: typeof politica === "string" ? politica : "",
  }));
}

/**
 * Linha pela metade não vira regra: rótulo vazio casaria com resposta vazia e política
 * vazia cairia no `politica or None` do motor — nos dois casos, config que parece
 * configurada e não faz nada.
 *
 * Mapa sem nenhuma linha válida grava `null`, não `{}`: no registro `default=None`
 * significa "ausente tem sentido próprio", e `_politica_do_botao` trata ausente e vazio
 * do mesmo jeito.
 */
function mapaDosPares(pares: ParDeBotao[]): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const { rotulo, politica } of pares) {
    const chave = rotulo.trim();
    if (!chave || !politica) continue;
    out[chave] = politica;
  }
  return Object.keys(out).length > 0 ? out : null;
}

/**
 * O controle do vocabulário `mapa_botoes`.
 *
 * As linhas vivem em estado LOCAL, e não derivadas do dicionário a cada tecla: enquanto
 * o operador digita "Parar atendimento" o rótulo passa por "P", "Pa"… — e um dicionário
 * reconstruído a cada letra colapsaria duas linhas assim que uma ficasse vazia ou
 * repetida. O dicionário é o que sai daqui (`onChange`), não o que governa a edição.
 * A remontagem por nó é garantida pelo `key` de quem renderiza.
 */
function ControleMapaBotoes({
  politicas, valor, onChange, estilos,
}: {
  politicas: { value: string; label: string }[];
  valor: unknown;
  onChange: (mapa: Record<string, string> | null) => void;
  estilos: { input: React.CSSProperties; select: React.CSSProperties; hint: React.CSSProperties };
}) {
  const [pares, setPares] = useState<ParDeBotao[]>(() => paresDoMapa(valor));

  const aplicar = (proximos: ParDeBotao[]) => {
    setPares(proximos);
    onChange(mapaDosPares(proximos));
  };
  const trocar = (i: number, patch: Partial<ParDeBotao>) =>
    aplicar(pares.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));

  const botaoLeve: React.CSSProperties = {
    border: "1px solid #e0dbd4", background: "#fff", borderRadius: 6,
    fontFamily: "'Outfit', sans-serif", fontSize: 12, color: "#555", cursor: "pointer",
  };

  return (
    <div
      data-controle="mapa_botoes"
      style={{ padding: "10px 12px", background: "#fafaf7", borderRadius: 6, border: "1px solid #e8e4df" }}
    >
      {pares.length === 0 && (
        <p style={{ ...estilos.hint, marginTop: 0, marginBottom: 8 }}>
          Nenhum botão declarado — toda resposta cai na política do nó e, sem ela, na do gatilho.
        </p>
      )}

      {pares.map((par, i) => (
        <div key={i} data-botao-linha={i} style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              type="text"
              aria-label={`Rótulo do botão ${i + 1}`}
              style={{ ...estilos.input, padding: "6px 8px" } as React.CSSProperties}
              value={par.rotulo}
              onChange={e => trocar(i, { rotulo: e.target.value })}
              placeholder="Ex.: Parar atendimento"
            />
            <button
              type="button"
              aria-label={`Remover botão ${i + 1}`}
              title="Remover este botão"
              onClick={() => aplicar(pares.filter((_, idx) => idx !== i))}
              style={{ ...botaoLeve, width: 30, flexShrink: 0, color: "#b0a8a0" }}
            >
              ✕
            </button>
          </div>
          <select
            aria-label={`Política do botão ${i + 1}`}
            style={{ ...estilos.select, marginTop: 4, padding: "6px 8px" } as React.CSSProperties}
            value={par.politica}
            onChange={e => trocar(i, { politica: e.target.value })}
          >
            <option value="">— O que fazer quando clicarem —</option>
            {politicas.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      ))}

      <button
        type="button"
        onClick={() => aplicar([...pares, { rotulo: "", politica: "" }])}
        style={{ ...botaoLeve, padding: "5px 10px" }}
      >
        + Adicionar botão
      </button>

      <p style={{ ...estilos.hint, marginTop: 8 }}>
        Pausar, cancelar e voltar ao primeiro toque mexem só nesta esteira;{" "}
        <strong>Descadastrar</strong> registra a saída de verdade — grava o opt-out no lead,
        move os cards para a Blacklist e cancela os follow-ups —, então nenhuma outra esteira
        reinscreve esse lead depois. O rótulo casa por igualdade, ignorando acento, caixa e
        pontuação: <em>Parar Atendimento</em> e <em>parar atendimento</em> são o mesmo botão.
      </p>
    </div>
  );
}

/** A chave de config que guarda o subtipo do nó. Não é campo do registro. */
const DISCRIMINADOR: Partial<Record<CampaignNodeType, { chave: string; rotulo: string }>> = {
  trigger:   { chave: "trigger_type",   rotulo: "Tipo de gatilho" },
  condition: { chave: "condition_type", rotulo: "Condição" },
  action:    { chave: "action_type",    rotulo: "Tipo de ação" },
};

const aprovado = (t: FlowTemplate) => t.status === "approved" || t.status === "APPROVED";

export function Inspector({ node, saving, data, onSave, onDelete, onClose }: InspectorProps) {
  const { templates, allStages, tags, users, channels } = data;
  const [draft, setDraft] = useState<Record<string, unknown>>(node.config as Record<string, unknown>);
  const meta = NODE_META[node.type];
  const schema = useNodeSchema();
  const funis = useFunis();

  useEffect(() => {
    setDraft(node.config as Record<string, unknown>);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  const set = (key: string, value: unknown) => setDraft(prev => ({ ...prev, [key]: value }));
  const c = draft;

  const disc = DISCRIMINADOR[node.type];
  const subtipo = disc ? ((c[disc.chave] as string) ?? "") : "";
  const tipoSchema = findNodeType(schema, node.type, subtipo || null);
  const campos = tipoSchema?.campos ?? [];

  const input: React.CSSProperties = {
    width: "100%", padding: "8px 11px",
    border: "1px solid #e0dbd4", borderRadius: 7,
    fontFamily: "'Outfit', sans-serif", fontSize: 13, color: "#111",
    background: "#faf9f6", outline: "none",
  };
  const select = { ...input, appearance: "none" } as React.CSSProperties;
  const label: React.CSSProperties = {
    display: "block", fontSize: 10, fontWeight: 700, letterSpacing: ".5px",
    textTransform: "uppercase", color: "#b0a8a0", marginBottom: 5,
  };
  const field: React.CSSProperties = { marginBottom: 14 };
  const hint: React.CSSProperties = { fontSize: 11, color: "#9b9590", marginTop: 4, lineHeight: 1.45 };

  // ─── Escrita ──────────────────────────────────────────────────────────────────
  //
  // Vazio vira `null`, não `""`. No registro, `default=None` significa "ausente tem
  // sentido próprio": é assim que `on_reply` do nó de envio herda a política do
  // gatilho e a janela do `wait` herda a da campanha. Gravar string vazia faria o nó
  // "opinar" com um valor que o motor não sabe ler.
  const escrever = (campo: NodeSchemaField, valor: unknown) => {
    if (valor === "" && campo.default !== "") return set(campo.chave, null);
    set(campo.chave, valor);
  };

  // ─── Listas por vocabulário ───────────────────────────────────────────────────
  //
  // Um `switch` no VOCABULÁRIO, não no subtipo. `etapa_key` e `segmento_lead` chegam
  // aqui com a mesma chave (`stage_filter`) e saem com listas diferentes.
  const opcoesDoVocab = (vocab: string): { value: string; label: string }[] | null => {
    switch (vocab) {
      case "segmento_lead":
      case "operador":
      case "politica_resposta":
      case "severidade":
      case "falante":
        // Vocabulário FECHADO: sai de `VALORES_FIXOS`, no backend. A tela não tem
        // cópia — foi a cópia que fez o <select> oferecer coluna de Kanban onde o
        // motor lia segmento de lead.
        return fixedValues(schema, vocab).map(([value, rotulo]) => ({ value, label: rotulo }));
      case "etapa_key": {
        // `pipeline_stages.key`, nunca o rótulo (o dono do funil pode renomear a
        // coluna a qualquer momento). A mesma key existe em vários funis e casa em
        // todos eles, então aparece UMA vez.
        const vistas = new Set<string>();
        const out: { value: string; label: string }[] = [];
        for (const s of allStages) {
          if (!s.key || vistas.has(s.key)) continue;
          vistas.add(s.key);
          out.push({ value: s.key, label: `${s.label} (${s.key})` });
        }
        return out;
      }
      case "etapa_id":
        // uuid de UMA coluna de UM funil. O motor não tem fallback por key nas ações
        // de deal: mandar key aqui não move card nenhum.
        return allStages.map(s => ({ value: s.id, label: `${s.pipeline_name} › ${s.label}` }));
      case "funil_id":
        return funis.map(f => ({ value: f.id, label: f.name }));
      case "canal_id":
        return channels.map(ch => ({ value: ch.id, label: ch.name }));
      case "tag":
        return tags.map(t => ({ value: t.name, label: t.name }));
      case "usuario_id":
        return users.map(u => ({ value: u.id, label: u.name || u.email }));
      default:
        return null;
    }
  };

  // ─── Controles ────────────────────────────────────────────────────────────────

  const templateSelecionado = templates.find(t => t.name === (c.template_name as string));

  const controleTemplate = (campo: NodeSchemaField) => {
    const pendentes = templates.filter(t => !aprovado(t));
    return (
      <>
        <select
          style={select}
          aria-label={campo.rotulo}
          value={(c[campo.chave] as string) ?? ""}
          onChange={e => {
            escrever(campo, e.target.value);
            // Variáveis do template anterior não valem para o novo.
            set("template_variables", null);
            const picked = templates.find(t => t.name === e.target.value);
            if (picked) set("template_language", picked.language);
          }}
        >
          <option value="">— Selecione um template —</option>
          {templates.filter(aprovado).map(t => (
            <option key={t.id} value={t.name}>{t.name} ({t.language})</option>
          ))}
          {pendentes.length > 0 && (
            // SELECIONÁVEL de propósito. Até 16/09/2026 estas opções vinham
            // `disabled`, o que impedia montar a esteira enquanto a Meta não
            // aprovasse — e as esteiras nascem em rascunho, sem template, justamente
            // porque montar antes é o fluxo normal. A trava mudou de lugar: quem
            // recusa template não aprovado é a ATIVAÇÃO da campanha, no backend.
            <optgroup label="Aguardando aprovação na Meta">
              {pendentes.map(t => (
                <option key={t.id} value={t.name}>{t.name} ({t.status})</option>
              ))}
            </optgroup>
          )}
        </select>
        {templates.length === 0 && <p style={hint}>Nenhum template cadastrado</p>}
        {templateSelecionado && !aprovado(templateSelecionado) && (
          <div style={{
            marginTop: 6, padding: "6px 9px", borderRadius: 6,
            background: "#fef9ed", border: "1px solid #fde68a",
            fontSize: 11, color: "#92400e", lineHeight: 1.45,
          }}>
            ⏳ Template <strong>aguardando aprovação</strong> na Meta ({templateSelecionado.status}).
            Dá para deixar o rascunho pronto; a ativação da campanha vai recusar até a Meta aprovar.
          </div>
        )}
      </>
    );
  };

  const controleMapa = (campo: NodeSchemaField) => {
    const tpl = templateSelecionado;
    if (!tpl) return <p style={hint}>Escolha um template para configurar as variáveis.</p>;

    const params = tpl.params ?? [];
    const paramsType = tpl.paramsType ?? "none";
    const vars = (c[campo.chave] as Record<string, string>) ?? {};
    if (params.length === 0) {
      return (
        <div style={{ padding: "8px 10px", background: "#f0fdf4", borderRadius: 6, border: "1px solid #bbf7d0" }}>
          <p style={{ fontSize: 11, color: "#166534" }}>✓ Template sem variáveis</p>
        </div>
      );
    }
    const setVar = (paramName: string, valor: string) => {
      const next: Record<string, string> = { ...vars, [paramName]: valor };
      // `__params_type__` diz ao worker se os parâmetros são posicionais ou nomeados
      // (`broadcast/worker._build_template_components`).
      if (paramsType !== "none") next["__params_type__"] = paramsType;
      set(campo.chave, next);
    };
    return (
      <div style={{ padding: "10px 12px", background: "#fafaf7", borderRadius: 6, border: "1px solid #e8e4df" }}>
        {params.map(p => {
          const key = paramsType === "named" ? p.paramName : String(p.index);
          return (
            <div key={key} style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 10, color: "#7b7b78", display: "block", marginBottom: 3 }}>
                {paramsType === "named" ? `{{${p.paramName}}}` : `{{${p.index}}}`}
                {p.example && <span style={{ color: "#bdb7b0", marginLeft: 6 }}>ex: {p.example}</span>}
              </label>
              <input
                type="text"
                aria-label={`${campo.rotulo} ${key}`}
                style={{ ...input, padding: "6px 8px", fontSize: 13 } as React.CSSProperties}
                value={vars[key] ?? ""}
                onChange={e => setVar(key, e.target.value)}
                placeholder={p.example || "Valor ou {{nome}}"}
              />
            </div>
          );
        })}
        <p style={{ ...hint, marginTop: 6 }}>
          Texto fixo ou tokens: <code>{`{{nome}}`}</code>, <code>{`{{empresa}}`}</code>, <code>{`{{produto}}`}</code>
        </p>
      </div>
    );
  };

  const controleListaDeUsuarios = (campo: NodeSchemaField) => {
    const escolhidos = (c[campo.chave] as string[]) ?? [];
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {users.map(u => {
          const selecionado = escolhidos.includes(u.id);
          return (
            <button
              key={u.id}
              type="button"
              aria-pressed={selecionado}
              onClick={() => {
                const arr = escolhidos.slice();
                const idx = arr.indexOf(u.id);
                if (idx >= 0) arr.splice(idx, 1); else arr.push(u.id);
                set(campo.chave, arr);
              }}
              style={{
                padding: "5px 10px", borderRadius: 6,
                border: `1px solid ${selecionado ? "#E85D26" : "#e0dbd4"}`,
                background: selecionado ? "rgba(232,93,38,.08)" : "#fff",
                color: selecionado ? "#E85D26" : "#555",
                fontSize: 12, cursor: "pointer",
              }}
            >
              {u.name || u.email}
            </button>
          );
        })}
        {users.length === 0 && <p style={hint}>Nenhum usuário disponível</p>}
      </div>
    );
  };

  const controle = (campo: NodeSchemaField) => {
    const valor = c[campo.chave];

    switch (campo.vocab) {
      case "template":
        return controleTemplate(campo);
      case "mapa":
        return controleMapa(campo);
      case "mapa_botoes":
        // `key` por NÓ: o estado local das linhas tem de recomeçar do config do nó novo
        // quando o inspector troca de nó sem desmontar.
        return (
          <ControleMapaBotoes
            key={`${node.id}:${campo.chave}`}
            valor={valor}
            politicas={fixedValues(schema, "politica_resposta").map(([value, rotulo]) => ({ value, label: rotulo }))}
            onChange={mapa => set(campo.chave, mapa)}
            estilos={{ input, select, hint }}
          />
        );
      case "lista_usuario_id":
        return controleListaDeUsuarios(campo);
      case "lista_texto":
        return (
          <input
            type="text"
            style={input}
            aria-label={campo.rotulo}
            value={((valor as string[]) ?? []).join(", ")}
            onChange={e => set(campo.chave, e.target.value.split(",").map(s => s.trim()).filter(Boolean))}
            placeholder="Ex: preço, valor, quanto custa"
          />
        );
      case "booleano": {
        // Três estados quando o registro declara `default=None`: o vazio HERDA da
        // campanha, e é diferente de um "não" explícito gravado no nó.
        const herda = campo.default === null || campo.default === undefined;
        const atual = valor === true ? "true" : valor === false ? "false" : "";
        return (
          <select
            style={select}
            aria-label={campo.rotulo}
            value={atual}
            onChange={e => set(campo.chave, e.target.value === "" ? null : e.target.value === "true")}
          >
            {herda && <option value="">— Herda da campanha —</option>}
            <option value="true">Sim</option>
            <option value="false">Não</option>
          </select>
        );
      }
      case "numero":
        return (
          <input
            type="number"
            style={input}
            aria-label={campo.rotulo}
            value={valor === null || valor === undefined ? "" : String(valor)}
            onChange={e => set(campo.chave, e.target.value === "" ? null : Number(e.target.value))}
            min={0}
          />
        );
      case "texto_longo":
        return (
          <textarea
            style={{ ...input, minHeight: 74, resize: "vertical" } as React.CSSProperties}
            aria-label={campo.rotulo}
            value={(valor as string) ?? ""}
            onChange={e => escrever(campo, e.target.value)}
            placeholder="Aceita {{nome}}, {{empresa}}, {{produto}}"
          />
        );
      default: {
        const opcoes = opcoesDoVocab(campo.vocab);
        if (opcoes) {
          // Só há opção vazia onde o registro diz que ausente tem sentido. Campo com
          // default declarado sempre tem valor — oferecer "vazio" ali seria oferecer
          // um estado que o motor não reconhece.
          const aceitaVazio = campo.default === null || campo.default === undefined;
          return (
            <select
              style={select}
              aria-label={campo.rotulo}
              value={(valor as string) ?? ""}
              onChange={e => escrever(campo, e.target.value)}
            >
              {aceitaVazio && <option value="">{campo.obrigatorio ? "— Selecione —" : "— Vazio —"}</option>}
              {opcoes.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          );
        }
        return (
          <input
            type="text"
            style={input}
            aria-label={campo.rotulo}
            value={(valor as string) ?? ""}
            onChange={e => escrever(campo, e.target.value)}
          />
        );
      }
    }
  };

  const renderCampo = (campo: NodeSchemaField) => (
    <div key={campo.chave} style={field} data-campo={campo.chave} data-vocab={campo.vocab}>
      <label style={label}>
        {campo.rotulo}
        {campo.obrigatorio && <span style={{ color: "#E85D26" }} title="Obrigatório para ativar"> *</span>}
      </label>
      {controle(campo)}
      {campo.ajuda && <p style={hint}>{campo.ajuda}</p>}
    </div>
  );

  // Opções do seletor de subtipo. Vem do schema INTEIRO (não só de `na_paleta`): um
  // nó salvo com tipo aposentado continua editável em vez de virar lixo na tela.
  const opcoesDeSubtipo: { value: string; label: string }[] = schema
    ? schema.tipos
        .filter(t => t.tipo === node.type && t.subtipo)
        .map(t => ({ value: t.subtipo as string, label: t.rotulo }))
    : Object.entries(
        node.type === "trigger" ? TRIGGER_LABELS
        : node.type === "action" ? ACTION_LABELS
        : CONDITION_LABELS,
      ).map(([value, rotulo]) => ({ value, label: rotulo }));

  // "Pelo menos um destes". Existe porque a RPC `get_deals_stage_stagnant` é
  // fail-closed com stage_id E stage_key nulos: devolve conjunto vazio, sem erro.
  const gruposEmFalta = (tipoSchema?.requer_um_de ?? []).filter(
    grupo => !grupo.some(k => c[k] !== null && c[k] !== undefined && c[k] !== ""),
  );

  return (
    <div style={{
      width: 256, flexShrink: 0,
      background: "#fff", borderLeft: "1px solid #e8e4df",
      display: "flex", flexDirection: "column",
      fontFamily: "'Outfit', sans-serif",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{ padding: "14px 16px 12px", borderBottom: "1px solid #ede9e3", display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ width: 30, height: 30, borderRadius: 7, background: meta.iconBg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15 }}>{meta.icon}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#111" }}>{tipoSchema?.rotulo ?? meta.label}</div>
          <div style={{ fontSize: 11, color: "#9b9590", marginTop: 1 }}>{meta.kicker}</div>
        </div>
        <button onClick={onClose} style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid #e0dbd4", background: "#faf9f6", cursor: "pointer", fontSize: 13, color: "#888" }}>✕</button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        {/* O que este nó faz — resumo em linguagem de operador, VIVO com o rascunho
            (atualiza enquanto edita, antes de salvar). */}
        <div style={{
          marginBottom: 16, padding: "10px 12px",
          background: meta.iconBg, borderLeft: `3px solid ${meta.color}`,
          borderRadius: 7,
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".5px", textTransform: "uppercase", color: meta.color, marginBottom: 4 }}>
            O que este nó faz
          </div>
          {/* Distinção INEQUÍVOCA Template × Texto Livre (regra da janela de 24h da Meta) */}
          {(node.type === "send" || node.type === "send_text") && (
            <span style={{
              display: "inline-block", marginBottom: 6, padding: "2px 8px",
              borderRadius: 4, fontSize: 9.5, fontWeight: 700, letterSpacing: ".4px",
              textTransform: "uppercase",
              background: node.type === "send" ? "rgba(232,93,38,.14)" : "rgba(15,118,110,.12)",
              color: node.type === "send" ? "#E85D26" : "#0F766E",
              border: `1px solid ${node.type === "send" ? "rgba(232,93,38,.35)" : "rgba(15,118,110,.3)"}`,
            }}>
              {node.type === "send"
                ? "Template aprovado · vale com janela fechada"
                : "Texto livre · exige janela de 24h aberta"}
            </span>
          )}
          <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "#3d3a36", whiteSpace: "pre-wrap" }}>
            {describeNode(node.type, c)}
          </div>
          {/* Texto REAL do template selecionado (body vindo de message_templates via
              /api/templates), com as variáveis configuradas já substituídas — o
              operador vê exatamente o que a Meta vai entregar. */}
          {node.type === "send" && c.template_name != null && c.template_name !== "" && (
            <div style={{ marginTop: 8, padding: "8px 10px", background: "#fff", border: "1px solid #e8e4df", borderRadius: 6 }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".4px", textTransform: "uppercase", color: "#9b9590", marginBottom: 4 }}>
                Texto real do template
              </div>
              {templateSelecionado?.body ? (
                <div style={{ fontSize: 12, lineHeight: 1.55, color: "#111", whiteSpace: "pre-wrap" }}>
                  {renderTemplateBody(templateSelecionado.body, c.template_variables as Record<string, string> | undefined)}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: "#9b9590" }}>
                  Corpo não sincronizado no catálogo local — confira na aba Templates.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Subtipo — a variante do nó. Governa quais campos aparecem abaixo. */}
        {disc && (
          <div style={field} data-campo={disc.chave}>
            <label style={label}>{disc.rotulo}</label>
            <select
              style={select}
              aria-label={disc.rotulo}
              value={subtipo}
              onChange={e => set(disc.chave, e.target.value)}
            >
              {opcoesDeSubtipo.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        )}

        {schema ? (
          <>
            {campos.map(renderCampo)}
            {gruposEmFalta.map((grupo, i) => (
              <div key={i} style={{
                marginBottom: 14, padding: "8px 10px", borderRadius: 6,
                background: "#fef9ed", border: "1px solid #fde68a",
                fontSize: 11, color: "#92400e", lineHeight: 1.45,
              }}>
                ⚠️ Preencha <strong>ao menos um</strong> destes:{" "}
                {grupo.map(k => tipoSchema?.campos.find(x => x.chave === k)?.rotulo ?? k).join(" ou ")}.
                Com os dois vazios a busca não devolve card nenhum.
              </div>
            ))}
            {campos.length === 0 && (
              <p style={hint}>Este nó não tem configuração — ele faz uma coisa só.</p>
            )}
          </>
        ) : (
          <p style={hint}>
            Carregando o contrato dos nós… os campos aparecem assim que
            <code> /api/campaigns/node-schema </code> responder.
          </p>
        )}

        {node.type === "send_text" && (
          <div style={{ ...field, padding: "8px 10px", background: "#fef9ed", borderRadius: 6, border: "1px solid #fde68a" }}>
            <p style={{ fontSize: 11, color: "#92400e", lineHeight: 1.5 }}>
              ⚠️ Texto livre — só sai dentro da janela de 24h desse canal. Fora dela o nó é
              reagendado e, no fim das tentativas, cancelado.
            </p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{ padding: "12px 16px", borderTop: "1px solid #ede9e3", display: "flex", gap: 6 }}>
        <button
          onClick={() => onSave(node.id, draft)}
          disabled={saving}
          style={{
            flex: 1, height: 34, borderRadius: 7, border: "none",
            background: saving ? "#ccc" : "#111", color: "#fff",
            fontFamily: "'Outfit', sans-serif", fontSize: 12, fontWeight: 500,
            cursor: saving ? "default" : "pointer",
          }}
        >
          {saving ? "Salvando..." : "Salvar"}
        </button>
        <button
          onClick={() => onDelete(node.id)}
          style={{
            height: 34, padding: "0 12px", borderRadius: 7,
            border: "1px solid #fecaca", background: "#fff5f5",
            color: "#dc2626", fontFamily: "'Outfit', sans-serif",
            fontSize: 12, cursor: "pointer",
          }}
        >
          Remover
        </button>
      </div>
    </div>
  );
}

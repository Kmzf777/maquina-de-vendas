"use client";

import { useState, useEffect } from "react";
import { AGENT_STAGES } from "@/lib/constants";
import type { InspectorProps } from "./types";
import { NODE_META, ACTION_LABELS } from "./constants";
import { describeNode } from "./describe-node";
import { renderTemplateBody } from "./render-template-body";

export function Inspector({ node, saving, data, onSave, onDelete, onClose }: InspectorProps) {
  const { templates, allStages, tags, users } = data;
  const [draft, setDraft] = useState<Record<string, unknown>>(node.config as Record<string, unknown>);
  const meta = NODE_META[node.type];

  useEffect(() => {
    setDraft(node.config as Record<string, unknown>);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  const set = (key: string, value: unknown) => setDraft(prev => ({ ...prev, [key]: value }));
  const c = draft;

  const input: React.CSSProperties = {
    width: "100%", padding: "8px 11px",
    border: "1px solid #e0dbd4", borderRadius: 7,
    fontFamily: "'Outfit', sans-serif", fontSize: 13, color: "#111",
    background: "#faf9f6", outline: "none",
  };
  const label: React.CSSProperties = {
    display: "block", fontSize: 10, fontWeight: 700, letterSpacing: ".5px",
    textTransform: "uppercase", color: "#b0a8a0", marginBottom: 5,
  };
  const field: React.CSSProperties = { marginBottom: 14 };

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
          <div style={{ fontSize: 13, fontWeight: 600, color: "#111" }}>{meta.label}</div>
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
          {node.type === "send" && (() => {
            const tpl = templates.find(t => t.name === (c.template_name as string));
            if (!c.template_name) return null;
            return (
              <div style={{ marginTop: 8, padding: "8px 10px", background: "#fff", border: "1px solid #e8e4df", borderRadius: 6 }}>
                <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".4px", textTransform: "uppercase", color: "#9b9590", marginBottom: 4 }}>
                  Texto real do template
                </div>
                {tpl?.body ? (
                  <div style={{ fontSize: 12, lineHeight: 1.55, color: "#111", whiteSpace: "pre-wrap" }}>
                    {renderTemplateBody(tpl.body, c.template_variables as Record<string, string> | undefined)}
                  </div>
                ) : (
                  <div style={{ fontSize: 11, color: "#9b9590" }}>
                    Corpo não sincronizado no catálogo local — confira na aba Templates.
                  </div>
                )}
              </div>
            );
          })()}
        </div>

        {node.type === "trigger" && (
          <>
            <div style={field}>
              <label style={label}>Tipo de gatilho</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.trigger_type as string) ?? ""} onChange={e => set("trigger_type", e.target.value)}>
                <option value="no_message">Sem mensagem</option>
                <option value="stage_stagnation">Estagnação de stage</option>
                <option value="stage_enter">Entrou em stage</option>
                <option value="post_broadcast">Pós-disparo</option>
                <option value="sale_created">Venda criada</option>
                <option value="repurchase_window">Janela de recompra</option>
                <option value="no_sale_in_stage">Sem venda no stage</option>
                <option value="tag_added">Tag adicionada</option>
                <option value="deal_stage_enter">Entrou em stage (deal)</option>
                <option value="deal_closed_lost">Deal perdido</option>
                <option value="keyword_received">Palavra-chave recebida</option>
              </select>
            </div>
            {(c.trigger_type === "no_message" || c.trigger_type === "stage_stagnation") && (
              <div style={field}><label style={label}>Dias</label><input type="number" style={input} value={(c.days as number) ?? 0} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {(c.trigger_type === "stage_stagnation" || c.trigger_type === "stage_enter") && (
              <div style={field}>
                <label style={label}>Filtro de stage</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)}>
                  <option value="">— Qualquer stage —</option>
                  {allStages.map(s => <option key={s.id} value={s.label}>{s.pipeline_name} › {s.label}</option>)}
                </select>
              </div>
            )}
            {c.trigger_type === "sale_created" && (
              <>
                <div style={field}><label style={label}>Valor mínimo (R$, opcional)</label>
                  <input type="number" style={input} value={(c.min_value as number) ?? ""} onChange={e => set("min_value", e.target.value ? Number(e.target.value) : null)} placeholder="Ex: 500" /></div>
                <div style={field}><label style={label}>Filtro de produto (opcional)</label>
                  <input type="text" style={input} value={(c.product_filter as string) ?? ""} onChange={e => set("product_filter", e.target.value || null)} placeholder="Ex: café" /></div>
              </>
            )}
            {(c.trigger_type === "repurchase_window" || c.trigger_type === "no_sale_in_stage") && (
              <div style={field}><label style={label}>Dias</label>
                <input type="number" style={input} value={(c.days as number) ?? 30} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {(c.trigger_type === "no_sale_in_stage" || c.trigger_type === "deal_stage_enter") && (
              <div style={field}>
                <label style={label}>Filtro de stage</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)}>
                  <option value="">— Qualquer stage —</option>
                  {allStages.map(s => <option key={s.id} value={s.label}>{s.pipeline_name} › {s.label}</option>)}
                </select>
              </div>
            )}
            {c.trigger_type === "tag_added" && (
              <div style={field}>
                <label style={label}>Tag</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)}>
                  <option value="">— Selecione uma tag —</option>
                  {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
                </select>
              </div>
            )}
            {c.trigger_type === "post_broadcast" && (
              <div style={field}>
                <label style={label}>Apenas quem respondeu?</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.replied_only as boolean) ? "true" : "false"} onChange={e => set("replied_only", e.target.value === "true")}>
                  <option value="false">Todos os leads do disparo</option>
                  <option value="true">Apenas quem respondeu</option>
                </select>
              </div>
            )}
            {(c.trigger_type as string) === "keyword_received" && (
              <div style={field}>
                <label style={label}>Palavras-chave (separadas por vírgula)</label>
                <input
                  style={input as React.CSSProperties}
                  type="text"
                  value={((c.keywords as string[]) ?? []).join(", ")}
                  onChange={e =>
                    set(
                      "keywords",
                      e.target.value
                        .split(",")
                        .map(s => s.trim())
                        .filter(Boolean)
                    )
                  }
                  placeholder="Ex: preço, valor, quanto custa"
                />
                <p style={{ fontSize: 11, color: "#9b9590", marginTop: 4 }}>
                  Quando o lead enviar uma mensagem contendo qualquer uma destas palavras (case-insensitive), a cadência será disparada.
                </p>
              </div>
            )}
          </>
        )}
        {node.type === "send" && (() => {
          const selectedTemplate = templates.find(t => t.name === (c.template_name as string));
          const params = selectedTemplate?.params ?? [];
          const paramsType = selectedTemplate?.paramsType ?? "none";
          const templateVars = (c.template_variables as Record<string, string>) ?? {};

          const setVar = (paramName: string, value: string) => {
            const next: Record<string, string> = { ...templateVars, [paramName]: value };
            if (paramsType !== "none") next["__params_type__"] = paramsType;
            set("template_variables", next);
          };

          // When template changes, reset template_variables to a fresh object
          // (the select onChange already calls set("template_name", ...); we don't reset vars here
          // — old vars are harmless if user re-picks the same template, and they get overwritten otherwise)

          return (
          <>
            <div style={field}>
              <label style={label}>Template</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.template_name as string) ?? ""} onChange={e => {
                set("template_name", e.target.value);
                // Reset variables when changing template to avoid stale params
                set("template_variables", {});
                // Also align language with the picked template
                const picked = templates.find(t => t.name === e.target.value);
                if (picked) set("template_language", picked.language);
              }}>
                <option value="">— Selecione um template —</option>
                {templates.filter(t => t.status === "approved" || t.status === "APPROVED").map(t => (
                  <option key={t.id} value={t.name}>{t.name} ({t.language})</option>
                ))}
                {templates.filter(t => t.status !== "approved" && t.status !== "APPROVED").length > 0 && (
                  <optgroup label="Aguardando aprovação">
                    {templates.filter(t => t.status !== "approved" && t.status !== "APPROVED").map(t => (
                      <option key={t.id} value={t.name} disabled>{t.name} ({t.status})</option>
                    ))}
                  </optgroup>
                )}
              </select>
              {templates.length === 0 && <p style={{ fontSize: 11, color: "#9b9590", marginTop: 4 }}>Nenhum template cadastrado</p>}
            </div>

            {selectedTemplate && params.length > 0 && (
              <div style={{ ...field, padding: "10px 12px", background: "#fafaf7", borderRadius: 6, border: "1px solid #e8e4df" }}>
                <label style={{ ...label, marginBottom: 8 }}>
                  Variáveis do template ({params.length})
                </label>
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
                        style={{ ...input, padding: "6px 8px", fontSize: 13 } as React.CSSProperties}
                        value={templateVars[key] ?? ""}
                        onChange={e => setVar(key, e.target.value)}
                        placeholder={p.example || "Valor ou {{nome}}"}
                      />
                    </div>
                  );
                })}
                <p style={{ fontSize: 10, color: "#9b9590", marginTop: 6, lineHeight: 1.4 }}>
                  Use texto fixo ou tokens dinâmicos: <code>{`{{nome}}`}</code>, <code>{`{{empresa}}`}</code>, <code>{`{{produto}}`}</code>
                </p>
              </div>
            )}

            {selectedTemplate && params.length === 0 && (
              <div style={{ ...field, padding: "8px 10px", background: "#f0fdf4", borderRadius: 6, border: "1px solid #bbf7d0" }}>
                <p style={{ fontSize: 11, color: "#166534" }}>✓ Template sem variáveis</p>
              </div>
            )}
            <div style={field}>
              <label style={label}>Ao responder</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
                <option value="pause">Pausar campanha</option>
                <option value="cancel">Cancelar campanha</option>
                <option value="continue">Continuar campanha</option>
              </select>
            </div>
            <div style={field}>
              <label style={label}>Canal (override)</label>
              <select
                style={{ ...input, appearance: "none" } as React.CSSProperties}
                value={(c.channel_id as string) ?? ""}
                onChange={e => set("channel_id", e.target.value || null)}
              >
                <option value="">— Usar padrão da cadência —</option>
                {data.channels.map(ch => <option key={ch.id} value={ch.id}>{ch.name}</option>)}
              </select>
            </div>
          </>
          );
        })()}
        {node.type === "send_text" && (
          <>
            <div style={field}>
              <label style={label}>Mensagem (vars: {"{{nome}}, {{empresa}}, {{produto}}"})</label>
              <textarea
                style={{ ...input, minHeight: 80, resize: "vertical" }}
                value={(c.message_text as string) ?? ""}
                onChange={e => set("message_text", e.target.value)}
                placeholder="Olá {{nome}}, tudo bem?"
              />
            </div>
            <div style={field}>
              <label style={label}>Ao responder</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
                <option value="pause">Pausar campanha</option>
                <option value="cancel">Cancelar campanha</option>
                <option value="continue">Continuar campanha</option>
              </select>
            </div>
            <div style={field}>
              <label style={label}>Canal (override)</label>
              <select
                style={{ ...input, appearance: "none" } as React.CSSProperties}
                value={(c.channel_id as string) ?? ""}
                onChange={e => set("channel_id", e.target.value || null)}
              >
                <option value="">— Usar padrão da cadência —</option>
                {data.channels.map(ch => <option key={ch.id} value={ch.id}>{ch.name}</option>)}
              </select>
            </div>
            <div style={{ ...field, padding: "8px 10px", background: "#fef9ed", borderRadius: 6, border: "1px solid #fde68a" }}>
              <p style={{ fontSize: 11, color: "#92400e", lineHeight: 1.5 }}>
                ⚠️ Texto livre — só enviado dentro da janela de 24h após o cliente responder. Se a janela estiver expirada, o nó é pulado automaticamente.
              </p>
            </div>
          </>
        )}
        {node.type === "wait" && (
          <div style={field}><label style={label}>Dias de espera</label><input type="number" style={input} value={(c.days as number) ?? 1} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
        )}
        {node.type === "condition" && (
          <>
            <div style={field}>
              <label style={label}>Condição</label>
              <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.condition_type as string) ?? ""} onChange={e => set("condition_type", e.target.value)}>
                <option value="replied_recently">Respondeu recentemente</option>
                <option value="in_stage">Está em stage</option>
                <option value="has_deal">Tem deal ativo</option>
                <option value="sale_count">Número de vendas</option>
                <option value="total_spend">Gasto total (R$)</option>
                <option value="last_sale_value">Valor da última venda</option>
                <option value="deal_value">Valor do deal</option>
                <option value="has_tag">Possui tag</option>
                <option value="repurchase_days">Dias desde última compra</option>
              </select>
            </div>
            {c.condition_type === "replied_recently" && (
              <div style={field}><label style={label}>Dias</label><input type="number" style={input} value={(c.days as number) ?? 5} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
            )}
            {c.condition_type === "in_stage" && (
              <div style={field}>
                <label style={label}>Stage</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage as string) ?? ""} onChange={e => set("stage", e.target.value)}>
                  <option value="">— Selecione um stage —</option>
                  {allStages.map(s => <option key={s.id} value={s.label}>{s.pipeline_name} › {s.label}</option>)}
                </select>
              </div>
            )}
            {["sale_count","total_spend","last_sale_value","deal_value","repurchase_days"].includes(c.condition_type as string) && (
              <>
                <div style={field}>
                  <label style={label}>Operador</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.operator as string) ?? "gte"} onChange={e => set("operator", e.target.value)}>
                    <option value="gte">≥ (maior ou igual)</option>
                    <option value="lte">≤ (menor ou igual)</option>
                    <option value="gt">&gt; (maior)</option>
                    <option value="lt">&lt; (menor)</option>
                    <option value="eq">= (igual)</option>
                  </select>
                </div>
                <div style={field}><label style={label}>Valor</label>
                  <input type="number" style={input} value={(c.value as number) ?? 0} onChange={e => set("value", Number(e.target.value))} min={0} /></div>
              </>
            )}
            {c.condition_type === "has_tag" && (
              <div style={field}>
                <label style={label}>Tag</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)}>
                  <option value="">— Selecione uma tag —</option>
                  {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
                </select>
              </div>
            )}
          </>
        )}
        {node.type === "action" && (() => {
          const at = c.action_type as string;
          return (
            <>
              <div style={field}>
                <label style={label}>Tipo de ação</label>
                <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={at ?? ""} onChange={e => set("action_type", e.target.value)}>
                  {Object.entries(ACTION_LABELS).map(([key, val]) => (
                    <option key={key} value={key}>{val}</option>
                  ))}
                </select>
              </div>

              {at === "move_stage" && (
                <div style={field}>
                  <label style={label}>Stage de destino (lead)</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage as string) ?? ""} onChange={e => set("stage", e.target.value)}>
                    <option value="">— selecione —</option>
                    {AGENT_STAGES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </div>
              )}

              {(at === "mark_deal_won" || at === "mark_deal_lost" || at === "move_deal_stage") && (
                <div style={field}>
                  <label style={label}>Estágio do deal (pipeline)</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.stage_id as string) ?? ""} onChange={e => set("stage_id", e.target.value)}>
                    <option value="">— selecione —</option>
                    {allStages.map(s => <option key={s.id} value={s.id}>{s.pipeline_name} › {s.label}</option>)}
                  </select>
                </div>
              )}

              {(at === "add_tag" || at === "remove_tag") && (
                <div style={field}>
                  <label style={label}>Nome da tag</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)}>
                    <option value="">— selecione —</option>
                    {tags.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
                  </select>
                </div>
              )}

              {at === "add_note" && (
                <div style={field}>
                  <label style={label}>Texto da nota (suporta {`{{nome}}`}, {`{{empresa}}`})</label>
                  <textarea
                    style={{ ...input, minHeight: 70, resize: "vertical" } as React.CSSProperties}
                    value={(c.note_template as string) ?? ""}
                    onChange={e => set("note_template", e.target.value)}
                    placeholder="Ex: Lead {{nome}} chegou no nó X"
                  />
                </div>
              )}

              {at === "create_deal" && (
                <div style={field}>
                  <label style={label}>Título do deal (suporta {`{{nome}}`})</label>
                  <input type="text" style={input} value={(c.title_template as string) ?? ""} onChange={e => set("title_template", e.target.value)} placeholder="Deal automático — {{empresa}}" />
                </div>
              )}

              {at === "assign_to" && (
                <div style={field}>
                  <label style={label}>Vendedor</label>
                  <select style={{ ...input, appearance: "none" } as React.CSSProperties} value={(c.user_id as string) ?? ""} onChange={e => set("user_id", e.target.value)}>
                    <option value="">— selecione —</option>
                    {users.map(u => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
                  </select>
                </div>
              )}

              {at === "assign_round_robin" && (
                <div style={field}>
                  <label style={label}>Vendedores no rodízio</label>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {users.map(u => {
                      const selected = ((c.user_ids as string[]) ?? []).includes(u.id);
                      return (
                        <button
                          key={u.id}
                          type="button"
                          onClick={() => {
                            const arr = ((c.user_ids as string[]) ?? []).slice();
                            const idx = arr.indexOf(u.id);
                            if (idx >= 0) arr.splice(idx, 1); else arr.push(u.id);
                            set("user_ids", arr);
                          }}
                          style={{
                            padding: "5px 10px",
                            borderRadius: 6,
                            border: `1px solid ${selected ? "#E85D26" : "#e0dbd4"}`,
                            background: selected ? "rgba(232,93,38,.08)" : "#fff",
                            color: selected ? "#E85D26" : "#555",
                            fontSize: 12,
                            cursor: "pointer",
                          }}
                        >
                          {u.name || u.email}
                        </button>
                      );
                    })}
                    {users.length === 0 && <p style={{ fontSize: 11, color: "#9b9590" }}>Nenhum usuário disponível</p>}
                  </div>
                </div>
              )}
            </>
          );
        })()}
        {node.type === "end" && (
          <div style={field}><label style={label}>Rótulo final</label><input type="text" style={input} value={(c.label as string) ?? ""} onChange={e => set("label", e.target.value)} placeholder="ex: Concluído" /></div>
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

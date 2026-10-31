"use client";

import { useEffect, useState } from "react";
import { LEAD_RESOLVERS, type LeadLike } from "@/lib/lead-variables";

/**
 * Lista de modelos aprovados de um número, com variáveis e prévia. Extraída do
 * TemplateDispatchModal (cartão 70d844a6) para o modal "Iniciar conversa" usar a
 * mesma escolha de modelo. Entrega por `onChange` o payload pronto do envio.
 */

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: { index: number; paramName: string; example: string }[];
  paramsType: "positional" | "named" | "none";
}

export interface TemplateEscolhido {
  template_name: string;
  template_language_code: string;
  template_variables: Record<string, string> | null;
  template_body: string;
}

interface Props {
  channelId: string;
  lead: LeadLike;
  onChange: (t: TemplateEscolhido | null) => void;
}

function resolveBody(
  body: string,
  params: MetaTemplate["params"],
  lead: LeadLike,
  inputs: Record<string, string>
): string {
  let text = body;
  for (const param of params) {
    const value =
      LEAD_RESOLVERS[param.paramName]?.(lead) ||
      inputs[param.paramName] ||
      (param.example ? `[${param.example}]` : `{{${param.paramName}}}`);
    text = text.replaceAll(`{{${param.paramName}}}`, value);
    text = text.replaceAll(`{{${param.index}}}`, value);
  }
  return text;
}

/** Payload do envio: variáveis resolvidas do lead + manuais, e o corpo resolvido. */
function montarEscolha(t: MetaTemplate, lead: LeadLike, inputs: Record<string, string>): TemplateEscolhido {
  let templateVariables: Record<string, string> | null = null;
  if (t.params.length > 0) {
    templateVariables = {};
    if (t.paramsType === "positional") {
      templateVariables["__params_type__"] = "positional";
    }
    for (const p of t.params) {
      templateVariables[p.paramName] = LEAD_RESOLVERS[p.paramName]?.(lead) || inputs[p.paramName] || p.example || "";
    }
  }
  return {
    template_name: t.name,
    template_language_code: t.language,
    template_variables: templateVariables,
    template_body: resolveBody(t.body, t.params, lead, inputs), // texto que fica no chat
  };
}

export function TemplatePicker({ channelId, lead, onChange }: Props) {
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [templateLoadError, setTemplateLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MetaTemplate | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [canalCarregado, setCanalCarregado] = useState(channelId);

  // Trocou o número: zera a escolha (o modelo de um número não vale no outro).
  if (canalCarregado !== channelId) {
    setCanalCarregado(channelId);
    setTemplates([]);
    setLoading(true);
    setTemplateLoadError(null);
    setSelected(null);
    setInputs({});
  }

  useEffect(() => {
    if (!channelId) return;
    let ativo = true;
    fetch(`/api/channels/${channelId}/templates`)
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "Erro ao carregar templates");
        return d;
      })
      .then((data) => {
        if (ativo) setTemplates(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        if (!ativo) return;
        setTemplates([]);
        setTemplateLoadError(err instanceof Error ? err.message : "Erro ao carregar templates");
      })
      .finally(() => {
        if (ativo) setLoading(false);
      });
    return () => {
      ativo = false;
    };
  }, [channelId]);

  function handleSelect(t: MetaTemplate) {
    const isAlreadySelected = selected?.name === t.name && selected?.language === t.language;
    if (isAlreadySelected) {
      setSelected(null);
      setInputs({});
      onChange(null);
      return;
    }
    setSelected(t);
    setInputs({});
    onChange(montarEscolha(t, lead, {}));
  }

  function handleInput(paramName: string, value: string) {
    const next = { ...inputs, [paramName]: value };
    setInputs(next);
    if (selected) onChange(montarEscolha(selected, lead, next));
  }

  const manualParams = (selected?.params ?? []).filter((p) => !LEAD_RESOLVERS[p.paramName]);
  const previewText = selected ? resolveBody(selected.body, selected.params, lead, inputs) : "";

  return (
    <>
      <p className="text-[11px] uppercase tracking-[0.8px] text-[#7b7b78] mb-2">
        Selecionar template
      </p>
      {loading ? (
        <p className="text-[13px] text-[#7b7b78]">Buscando templates...</p>
      ) : templateLoadError ? (
        <p className="text-[13px] text-[#c41c1c]">{templateLoadError}</p>
      ) : templates.length === 0 ? (
        <p className="text-[13px] text-[#c41c1c]">Nenhum template aprovado encontrado.</p>
      ) : (
        <div className="space-y-1.5">
          {templates.map((t) => {
            const isSelected = selected?.name === t.name && selected?.language === t.language;
            return (
              <div
                key={`${t.name}|${t.language}`}
                className={`rounded-[6px] border transition-colors ${
                  isSelected
                    ? "border-[#111111] bg-[#111111]/5"
                    : "border-[#dedbd6] hover:border-[#111111]/40 hover:bg-[#f0ede8]"
                }`}
              >
                <button
                  onClick={() => handleSelect(t)}
                  className="w-full text-left px-3 py-2.5"
                >
                  <span className="text-[13px] text-[#111111] font-medium">{t.name}</span>
                  {t.category && (
                    <span className="ml-2 text-[11px] text-[#7b7b78]">{t.category}</span>
                  )}
                  <span className="ml-1 text-[11px] text-[#7b7b78]">· {t.language}</span>
                </button>

                {/* Inline preview — appears right below the selected item */}
                {isSelected && (
                  <div className="px-3 pb-3 space-y-2.5 border-t border-[#dedbd6]/60 pt-2.5">
                    {/* Inputs for variables that can't be auto-resolved from the lead */}
                    {manualParams.length > 0 && (
                      <div className="space-y-1.5">
                        <p className="text-[11px] text-[#7b7b78]">Preencha as variáveis:</p>
                        {manualParams.map((p) => (
                          <div key={p.paramName} className="flex items-center gap-2">
                            <span className="text-[12px] text-[#7b7b78] w-28 shrink-0">{p.paramName}</span>
                            <input
                              type="text"
                              value={inputs[p.paramName] ?? ""}
                              onChange={(e) => handleInput(p.paramName, e.target.value)}
                              placeholder={p.example || "..."}
                              className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-2.5 py-1 text-[12px] text-[#111111] focus:border-[#111111] focus:outline-none"
                            />
                          </div>
                        ))}
                      </div>
                    )}

                    {/* WhatsApp-style bubble preview */}
                    <div className="bg-[#f0ede8] rounded-[6px] p-2.5">
                      <p className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1.5">
                        Como vai ficar
                      </p>
                      <div className="bg-white border border-[#dedbd6] rounded-[8px] rounded-tl-none px-3 py-2 max-w-[88%]">
                        <p className="text-[13px] text-[#111111] whitespace-pre-wrap leading-relaxed">
                          {previewText || "(sem corpo de template)"}
                        </p>
                        <p className="text-[10px] text-[#7b7b78] text-right mt-1">agora</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

"use client";

import { useState, useEffect } from "react";
import type { Conversation } from "@/lib/types";

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: { index: number; paramName: string; example: string }[];
  paramsType: "positional" | "named" | "none";
}

interface Props {
  conversation: Conversation;
  onClose: () => void;
  onSuccess: () => void;
}

// Mirrors _LEAD_FIELD_TOKENS in backend/app/broadcast/worker.py
const LEAD_RESOLVERS: Record<string, (l: { name?: string | null; phone?: string; company?: string | null }) => string> = {
  primeiro_nome: (l) => (l.name ?? "").split(" ")[0],
  nome_completo: (l) => l.name ?? "",
  telefone: (l) => l.phone ?? "",
  empresa: (l) => l.company ?? "",
  first_name: (l) => (l.name ?? "").split(" ")[0],
  lead_name: (l) => l.name ?? "",
  phone: (l) => l.phone ?? "",
};

function resolveBody(
  body: string,
  params: MetaTemplate["params"],
  lead: { name?: string | null; phone?: string; company?: string | null },
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

export function TemplateDispatchModal({ conversation, onClose, onSuccess }: Props) {
  const channelId = conversation.channel_id;
  const lead = conversation.leads;

  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [templateLoadError, setTemplateLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MetaTemplate | null>(null);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!channelId) return;
    fetch(`/api/channels/${channelId}/templates`)
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "Erro ao carregar templates");
        return d;
      })
      .then((data) => setTemplates(Array.isArray(data) ? data : []))
      .catch((err) => {
        setTemplates([]);
        setTemplateLoadError(err instanceof Error ? err.message : "Erro ao carregar templates");
      })
      .finally(() => setLoading(false));
  }, [channelId]);

  function handleSelect(t: MetaTemplate) {
    const isAlreadySelected = selected?.name === t.name && selected?.language === t.language;
    if (isAlreadySelected) {
      setSelected(null);
      setInputs({});
      return;
    }
    setSelected(t);
    setInputs({});
    setError(null);
  }

  const manualParams = (selected?.params ?? []).filter((p) => !LEAD_RESOLVERS[p.paramName]);
  const previewText = selected
    ? resolveBody(selected.body, selected.params, lead ?? {}, inputs)
    : "";

  async function handleSend() {
    if (!selected || !conversation.id) return;
    setSending(true);
    setError(null);

    // Build template_variables with resolved lead data + manual inputs
    let templateVariables: Record<string, string> | null = null;
    if (selected.params.length > 0) {
      templateVariables = {};
      if (selected.paramsType === "positional") {
        templateVariables["__params_type__"] = "positional";
      }
      for (const p of selected.params) {
        const value = LEAD_RESOLVERS[p.paramName]?.(lead ?? {}) || inputs[p.paramName] || p.example || "";
        templateVariables[p.paramName] = value;
      }
    }

    try {
      const res = await fetch(`/api/conversations/${conversation.id}/send-template`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_name: selected.name,
          template_language_code: selected.language,
          template_variables: templateVariables,
          template_body: previewText, // resolved text — stored as the message content in the chat
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Erro ao enviar template");
      }
      onSuccess();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] w-full max-w-lg mx-4 flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#dedbd6] flex-shrink-0">
          <h2
            style={{ letterSpacing: "-0.4px", lineHeight: "1.00" }}
            className="text-[17px] font-medium text-[#111111]"
          >
            Iniciar disparo
          </h2>
          <button
            onClick={onClose}
            className="text-[#7b7b78] hover:text-[#111111] transition-colors p-1"
            aria-label="Fechar"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5">
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
                                  onChange={(e) =>
                                    setInputs((prev) => ({ ...prev, [p.paramName]: e.target.value }))
                                  }
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
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-[#dedbd6] flex items-center justify-between gap-3 flex-shrink-0">
          <div className="flex-1">
            {error && <p className="text-[12px] text-[#c41c1c]">{error}</p>}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="border border-[#dedbd6] text-[#111111] text-[13px] px-4 py-2 rounded-[4px] hover:bg-[#dedbd6]/30 transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={handleSend}
              disabled={!selected || sending}
              className="bg-[#111111] text-white text-[13px] px-4 py-2 rounded-[4px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:hover:scale-100"
            >
              {sending ? "Enviando..." : "Confirmar envio"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

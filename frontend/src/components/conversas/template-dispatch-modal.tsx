"use client";

import { useState, useEffect } from "react";
import type { Conversation } from "@/lib/types";

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: { index: number; paramName: string; example: string }[];
}

interface Props {
  conversation: Conversation;
  onClose: () => void;
  onSuccess: () => void;
}

export function TemplateDispatchModal({ conversation, onClose, onSuccess }: Props) {
  const channelId = conversation.channel_id;

  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<MetaTemplate | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!channelId) return;
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((data) => setTemplates(Array.isArray(data) ? data : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, [channelId]);

  async function handleSend() {
    if (!selected || !conversation.id) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch(`/api/conversations/${conversation.id}/send-template`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_name: selected.name,
          template_language_code: selected.language,
          template_variables: null,
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
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Template list */}
          <div>
            <p className="text-[11px] uppercase tracking-[0.8px] text-[#7b7b78] mb-2">
              Selecionar template
            </p>
            {loading ? (
              <p className="text-[13px] text-[#7b7b78]">Buscando templates...</p>
            ) : templates.length === 0 ? (
              <p className="text-[13px] text-[#c41c1c]">Nenhum template aprovado encontrado.</p>
            ) : (
              <div className="space-y-1.5">
                {templates.map((t) => {
                  const isSelected =
                    selected?.name === t.name && selected?.language === t.language;
                  return (
                    <button
                      key={`${t.name}|${t.language}`}
                      onClick={() => setSelected(isSelected ? null : t)}
                      className={`w-full text-left px-3 py-2.5 rounded-[6px] border transition-colors ${
                        isSelected
                          ? "border-[#111111] bg-[#111111]/5"
                          : "border-[#dedbd6] hover:border-[#111111]/40 hover:bg-[#f0ede8]"
                      }`}
                    >
                      <span className="text-[13px] text-[#111111] font-medium">{t.name}</span>
                      {t.category && (
                        <span className="ml-2 text-[11px] text-[#7b7b78]">{t.category}</span>
                      )}
                      <span className="ml-1 text-[11px] text-[#7b7b78]">· {t.language}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Preview */}
          {selected && (
            <div>
              <p className="text-[11px] uppercase tracking-[0.8px] text-[#7b7b78] mb-2">
                Pré-visualização
              </p>
              <div className="bg-[#f0ede8] border border-[#dedbd6] rounded-[8px] p-3">
                <div className="bg-white border border-[#dedbd6] rounded-[8px] rounded-tl-none px-3 py-2.5 max-w-[88%]">
                  <p className="text-[13px] text-[#111111] whitespace-pre-wrap leading-relaxed">
                    {selected.body || "(sem corpo de template)"}
                  </p>
                  <p className="text-[10px] text-[#7b7b78] text-right mt-1">agora</p>
                </div>
              </div>
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

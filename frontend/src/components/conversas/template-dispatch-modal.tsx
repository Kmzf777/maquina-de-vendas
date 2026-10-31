"use client";

import { useState } from "react";
import type { Conversation } from "@/lib/types";
import { TemplatePicker, type TemplateEscolhido } from "./template-picker";

interface Props {
  conversation: Conversation;
  onClose: () => void;
  onSuccess: () => void;
}

export function TemplateDispatchModal({ conversation, onClose, onSuccess }: Props) {
  const channelId = conversation.channel_id;
  const lead = conversation.leads;

  const [escolha, setEscolha] = useState<TemplateEscolhido | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleChange(t: TemplateEscolhido | null) {
    setEscolha(t);
    setError(null);
  }

  async function handleSend() {
    if (!escolha || !conversation.id) return;
    setSending(true);
    setError(null);

    try {
      const res = await fetch(`/api/conversations/${conversation.id}/send-template`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(escolha),
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
          <TemplatePicker channelId={channelId ?? ""} lead={lead ?? {}} onChange={handleChange} />
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
              disabled={!escolha || sending}
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

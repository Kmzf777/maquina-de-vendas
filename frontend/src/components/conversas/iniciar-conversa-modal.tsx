"use client";

import { useEffect, useState } from "react";
import { TemplatePicker, type TemplateEscolhido } from "./template-picker";

/**
 * Iniciar conversa com lead sem conversa (cartão 70d844a6): escolhe o número
 * (canais Meta que o usuário vê) e um modelo aprovado dele, e manda pela rota
 * /api/leads/<id>/iniciar-conversa, que cria a conversa e envia o modelo.
 */

interface Dados {
  lead: { id: string; name: string | null; phone: string | null; company: string | null };
  telefone: string | null;
  canais: { id: string; name: string }[];
}

interface Props {
  leadId: string;
  onClose: () => void;
  onIniciada: (conversationId: string) => void;
}

export function IniciarConversaModal({ leadId, onClose, onIniciada }: Props) {
  const [dados, setDados] = useState<Dados | null>(null);
  const [erroCarga, setErroCarga] = useState<string | null>(null);
  const [canal, setCanal] = useState("");
  const [escolha, setEscolha] = useState<TemplateEscolhido | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ativo = true;
    fetch(`/api/leads/${leadId}/iniciar-conversa`)
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || "Erro ao carregar o lead");
        return d as Dados;
      })
      .then((d) => {
        if (!ativo) return;
        setDados(d);
        if (d.canais?.length === 1) setCanal(d.canais[0].id);
      })
      .catch((err) => {
        if (ativo) setErroCarga(err instanceof Error ? err.message : "Erro ao carregar o lead");
      });
    return () => {
      ativo = false;
    };
  }, [leadId]);

  function handleCanal(id: string) {
    setCanal(id);
    setEscolha(null);
    setError(null);
  }

  function handleEscolha(t: TemplateEscolhido | null) {
    setEscolha(t);
    setError(null);
  }

  async function handleSend() {
    if (!canal || !escolha) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch(`/api/leads/${leadId}/iniciar-conversa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: canal, ...escolha }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.conversation_id) {
        throw new Error(data.error || "Erro ao iniciar conversa");
      }
      onIniciada(data.conversation_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setSending(false);
    }
  }

  const canais = dados?.canais ?? [];
  const telefone = dados ? dados.telefone ?? dados.lead.phone : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label="Iniciar conversa"
        className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] w-full max-w-lg mx-4 flex flex-col max-h-[80vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#dedbd6] flex-shrink-0">
          <div className="min-w-0">
            <h2
              style={{ letterSpacing: "-0.4px", lineHeight: "1.00" }}
              className="text-[17px] font-medium text-[#111111]"
            >
              Iniciar conversa
            </h2>
            {dados && (
              <p className="mt-1.5 text-[12px] text-[#7b7b78] truncate">
                {dados.lead.name || "Lead sem nome"}
                {telefone ? ` · ${telefone}` : ""}
              </p>
            )}
          </div>
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
          {erroCarga ? (
            <p className="text-[13px] text-[#c41c1c]">{erroCarga}</p>
          ) : !dados ? (
            <p className="text-[13px] text-[#7b7b78]">Carregando…</p>
          ) : canais.length === 0 ? (
            <p className="text-[13px] text-[#c41c1c]">
              Você não tem número do WhatsApp para iniciar conversa.
            </p>
          ) : (
            <>
              <label
                htmlFor="iniciar-conversa-numero"
                className="block text-[11px] uppercase tracking-[0.8px] text-[#7b7b78] mb-2"
              >
                Número
              </label>
              <select
                id="iniciar-conversa-numero"
                value={canal}
                onChange={(e) => handleCanal(e.target.value)}
                className="w-full mb-5 bg-white border border-[#dedbd6] rounded-[4px] px-2.5 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
              >
                {canais.length > 1 && <option value="">Escolha o número</option>}
                {canais.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {canal && (
                <TemplatePicker key={canal} channelId={canal} lead={dados.lead} onChange={handleEscolha} />
              )}
            </>
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
              disabled={!canal || !escolha || sending}
              className="bg-[#111111] text-white text-[13px] px-4 py-2 rounded-[4px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 disabled:hover:scale-100"
            >
              {sending ? "Enviando..." : "Enviar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

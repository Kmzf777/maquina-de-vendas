"use client";

import { useState, useRef, useEffect } from "react";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import type { Lead } from "@/lib/types";

interface ChatActiveProps {
  lead: Lead;
  onClose: () => void;
  onOpenDetails: () => void;
}

export function ChatActive({ lead, onClose, onOpenDetails }: ChatActiveProps) {
  const { messages, loading } = useRealtimeMessages(lead.id);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || sending) return;

    setSending(true);
    try {
      const res = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ leadId: lead.id, text: text.trim() }),
      });
      if (res.ok) setText("");
    } finally {
      setSending(false);
    }
  }

  const handoffIndex = messages.findIndex(
    (m) => m.role === "system" && m.content.includes("encaminhado")
  );

  return (
    <div className="fixed inset-y-0 right-0 w-[480px] bg-white shadow-2xl border-l border-[#e5e5dc] flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-[#e5e5dc]">
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-full text-[#9ca3af] hover:text-[#1f1f1f] hover:bg-[#f6f7ed] transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="10 2 4 8 10 14" />
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-[15px] font-semibold text-[#1f1f1f] truncate">
            {lead.name || lead.phone}
          </h2>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="badge text-[11px]">{lead.stage}</span>
          </div>
        </div>
        <button
          onClick={onOpenDetails}
          className="btn-secondary px-3 py-1.5 rounded-lg text-[12px] font-medium"
        >
          Dados
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-5 space-y-3 bg-[#f6f7ed]">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={msg.id}>
            {i === handoffIndex && (
              <div className="flex items-center my-5">
                <div className="flex-1 border-t border-[#c8cc8e]" />
                <span className="px-3 text-[11px] text-[#9ca3af] font-medium">
                  Vendedor assumiu o chat
                </span>
                <div className="flex-1 border-t border-[#c8cc8e]" />
              </div>
            )}
            <div
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] px-4 py-2.5 text-[13px] ${
                  msg.role === "user"
                    ? "bg-[#1f1f1f] text-white rounded-2xl rounded-br-sm"
                    : msg.role === "system"
                    ? "text-[#9ca3af] italic text-[12px] text-center w-full bg-transparent"
                    : msg.sent_by === "seller"
                    ? "bg-[#f0f1e0] border border-[#e5e5dc] text-[#1f1f1f] rounded-2xl rounded-bl-sm"
                    : "bg-white border border-[#e5e5dc] text-[#1f1f1f] rounded-2xl rounded-bl-sm"
                }`}
              >
                {msg.role === "assistant" && (
                  <p className="text-[11px] text-[#9ca3af] mb-1">
                    {msg.sent_by === "seller" ? "Vendedor" : "Agente"}
                  </p>
                )}
                <p className="whitespace-pre-wrap">{msg.content}</p>
                {msg.role !== "system" && (
                  <p className="text-[11px] opacity-60 mt-1.5">
                    {new Date(msg.created_at).toLocaleTimeString("pt-BR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSend}
        className="border-t border-[#e5e5dc] bg-white px-4 py-3 flex gap-3"
      >
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Digite uma mensagem..."
          className="input-field flex-1"
        />
        <button
          type="submit"
          disabled={sending || !text.trim()}
          className="btn-primary px-5 py-2.5 rounded-xl text-[13px] font-medium disabled:opacity-50 flex items-center gap-2"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
          Enviar
        </button>
      </form>
    </div>
  );
}

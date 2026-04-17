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
    <div className="fixed inset-y-0 right-0 w-[480px] bg-[#faf9f6] border-l border-[#dedbd6] flex flex-col z-50">
      {/* Header */}
      <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3">
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30 transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="10 2 4 8 10 14" />
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-[14px] font-medium text-[#111111] truncate">
            {lead.name || lead.phone}
          </h2>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78]">{lead.stage}</span>
          </div>
        </div>
        <button
          onClick={onOpenDetails}
          className="bg-transparent text-[#111111] border border-[#111111] px-3 py-1.5 rounded-[4px] text-[12px] transition-transform hover:scale-110 active:scale-[0.85]"
        >
          Dados
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2 bg-[#faf9f6]">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={msg.id}>
            {i === handoffIndex && (
              <div className="flex items-center my-5">
                <div className="flex-1 border-t border-[#dedbd6]" />
                <span className="px-3 text-[11px] text-[#7b7b78]">
                  Vendedor assumiu o chat
                </span>
                <div className="flex-1 border-t border-[#dedbd6]" />
              </div>
            )}
            <div
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`text-[13px] px-3 py-2 ${
                  msg.role === "user"
                    ? "bg-[#111111] text-white rounded-[8px] max-w-[75%] ml-auto"
                    : msg.role === "system"
                    ? "text-[#7b7b78] italic text-[12px] text-center w-full bg-transparent"
                    : msg.sent_by === "seller"
                    ? "bg-white border border-[#dedbd6] text-[#111111] rounded-[8px] max-w-[75%]"
                    : "bg-white border border-[#dedbd6] text-[#111111] rounded-[8px] max-w-[75%]"
                }`}
              >
                {msg.role === "assistant" && (
                  <p className="text-[11px] text-[#7b7b78] mb-1">
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
        className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2"
      >
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Digite uma mensagem..."
          className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none"
        />
        <button
          type="submit"
          disabled={sending || !text.trim()}
          className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex items-center gap-2"
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

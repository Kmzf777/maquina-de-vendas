"use client";

import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import type { Lead } from "@/lib/types";

interface ChatPanelProps {
  lead: Lead;
  onClose: () => void;
}

export function ChatPanel({ lead, onClose }: ChatPanelProps) {
  const { messages, loading } = useRealtimeMessages(lead.id);

  return (
    <div className="fixed inset-y-0 right-0 w-[420px] bg-white shadow-2xl border-l border-[#e5e5dc] flex flex-col z-50">
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#e5e5dc]">
        <div>
          <h2 className="text-[15px] font-semibold text-[#1f1f1f]">
            {lead.name || lead.phone}
          </h2>
          <div className="flex items-center gap-2 mt-1">
            <span className="badge text-[11px]">{lead.stage}</span>
            <span className="text-[11px] text-[#9ca3af]">Somente leitura</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-full text-[#9ca3af] hover:text-[#1f1f1f] hover:bg-[#f6f7ed] transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-3 bg-[#f6f7ed]">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] px-4 py-2.5 text-[13px] ${
                msg.role === "user"
                  ? "bg-[#1f1f1f] text-white rounded-2xl rounded-br-sm"
                  : msg.role === "system"
                  ? "text-[#9ca3af] italic text-[12px] text-center w-full bg-transparent"
                  : "bg-[#f6f7ed] border border-[#e5e5dc] text-[#1f1f1f] rounded-2xl rounded-bl-sm"
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
        ))}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Lead, Message } from "@/lib/types";

interface ChatPanelProps {
  lead: Lead;
  onClose: () => void;
}

export function ChatPanel({ lead, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = useMemo(() => createClient(), []);

  const fetchMessages = useCallback(async () => {
    const { data } = await supabase
      .from("messages")
      .select("*")
      .eq("lead_id", lead.id)
      .order("created_at", { ascending: false });
    if (data) setMessages([...data].reverse() as Message[]);
    setLoading(false);
  }, [lead.id]);

  useEffect(() => {
    setMessages([]);
    setLoading(true);
    fetchMessages();

    const channel = supabase
      .channel(`panel-messages-${lead.id}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages", filter: `lead_id=eq.${lead.id}` },
        (payload) => setMessages((prev) => [...prev, payload.new as Message]),
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [lead.id, fetchMessages]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "instant" });
  }, [messages]);

  return (
    <div className="fixed inset-y-0 right-0 w-[420px] bg-[#faf9f6] border-l border-[#dedbd6] flex flex-col z-50">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#dedbd6] bg-[#faf9f6]">
        <div>
          <h2 className="text-[15px] font-medium text-[#111111]">
            {lead.name || lead.phone}
          </h2>
          {lead.name && (
            <p className="text-[12px] text-[#7b7b78] mt-0.5">{lead.phone}</p>
          )}
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78]">
              {lead.stage}
            </span>
            {lead.human_control && (
              <span
                className="text-[11px] px-2 py-0.5 rounded-[4px] border"
                style={{ background: "#fff3cd", color: "#8a6914", borderColor: "#f0d060" }}
              >
                Humano
              </span>
            )}
            {lead.on_hold && (
              <span className="text-[11px] px-2 py-0.5 rounded-[4px] border border-[#dedbd6] bg-[#f4f4f0] text-[#7b7b78]">
                Parado
              </span>
            )}
            <span className="text-[11px] text-[#7b7b78]">Somente leitura</span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30 transition-colors"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="4" x2="12" y2="12" />
            <line x1="12" y1="4" x2="4" y2="12" />
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-2 bg-[#faf9f6]">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "assistant" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`text-[13px] px-3 py-2 ${
                msg.role === "assistant"
                  ? "bg-[#111111] text-white rounded-[8px] max-w-[75%]"
                  : msg.role === "system"
                  ? "text-[#7b7b78] italic text-[12px] text-center w-full bg-transparent"
                  : "bg-white border border-[#dedbd6] text-[#111111] rounded-[8px] max-w-[75%]"
              }`}
            >
              {msg.role === "assistant" && (
                <p className="text-[11px] text-white/60 mb-1 text-right">
                  {msg.sent_by === "seller" ? "Vendedor" : "Agente"}
                </p>
              )}
              <p className="whitespace-pre-wrap">{msg.content}</p>
              {msg.role !== "system" && (
                <p className={`text-[11px] opacity-60 mt-1.5 ${msg.role === "assistant" ? "text-right" : ""}`}>
                  {new Date(msg.created_at).toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

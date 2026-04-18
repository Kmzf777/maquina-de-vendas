"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type { Message, Conversation, Tag } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
}

function formatTime(ts: string): string {
  const date = new Date(ts);
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function ChatView({ conversation, tags }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  // Real-time messages from Supabase (subscribed by lead_id)
  const { messages, loading } = useRealtimeMessages(lead?.id ?? null);

  // Optimistic messages: shown immediately on send, removed once real message arrives
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);

  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  // Clear optimistic messages when switching conversations
  useEffect(() => {
    setOptimisticMessages([]);
  }, [conversation.id]);

  // Abort in-flight fetch on conversation switch
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, [conversation.id]);

  // Merged display list: real messages + unconfirmed optimistic ones
  const displayMessages = useMemo(() => {
    return [...messages, ...optimisticMessages];
  }, [messages, optimisticMessages]);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayMessages]);

  async function handleSend() {
    if (!text.trim() || sendingRef.current) return;
    sendingRef.current = true;

    const content = text.trim();

    // Inject optimistic message immediately — user sees it at ~0ms
    const tempMsg: Message = {
      id: `temp_${Date.now()}`,
      lead_id: lead?.id ?? "",
      role: "assistant",
      content,
      stage: null,
      sent_by: "seller",
      created_at: new Date().toISOString(),
    };

    setText("");
    setOptimisticMessages((prev) => [...prev, tempMsg]);
    setSending(true);

    try {
      const controller = new AbortController();
      abortRef.current = controller;

      const res = await fetch(`/api/conversations/${conversation.id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content }),
        signal: controller.signal,
      });

      if (res.ok) {
        // Remove temp immediately — realtime delivers the real message in <1s
        setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
      } else {
        // Send failed — remove temp message and restore input
        setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
        setText(content);
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
      setText(content);
    } finally {
      setSending(false);
      sendingRef.current = false;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const displayName = lead?.name || lead?.phone || "Desconhecido";

  const tagIdsRaw = (lead as unknown as Record<string, unknown>)?.tag_ids;
  const tagIds = Array.isArray(tagIdsRaw) ? (tagIdsRaw as string[]) : [];
  const leadTagIds = lead ? tags.filter((t) => tagIds.includes(t.id)) : [] as Tag[];

  return (
    <div className="flex-1 flex flex-col h-full bg-[#faf9f6]">
      {/* Header */}
      <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-[#8a8a80] flex items-center justify-center text-white font-medium text-sm flex-shrink-0">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-[#111111] font-medium text-[14px] truncate">{displayName}</h2>
          <p className="text-[#7b7b78] text-[12px]">{lead?.phone || ""}</p>
        </div>
        {channel && (
          <span className="text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78]">
            {channel.name}
          </span>
        )}
        {leadTagIds.length > 0 && (
          <div className="flex gap-1">
            {leadTagIds.map((tag) => (
              <span
                key={tag.id}
                className="px-2 py-0.5 rounded-[4px] text-[11px] text-white"
                style={{ backgroundColor: tag.color }}
              >
                {tag.name}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2 bg-[#faf9f6]">
        {loading && (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
          </div>
        )}
        {!loading && displayMessages.length === 0 && (
          <p className="text-[#7b7b78] text-sm text-center py-8">Nenhuma mensagem.</p>
        )}
        {displayMessages.map((msg) => {
          const isFromMe = msg.role === "assistant";
          const isTemp = msg.id.startsWith("temp_");
          return (
            <div
              key={msg.id}
              className={`flex ${isFromMe ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`px-3 py-2 text-[14px] ${
                  isFromMe
                    ? "bg-[#111111] rounded-[8px] text-white max-w-[75%] ml-auto"
                    : "bg-white border border-[#dedbd6] rounded-[8px] text-[#111111] max-w-[75%]"
                } ${isTemp ? "opacity-70" : ""}`}
              >
                <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                <p
                  className={`text-[11px] mt-1 ${
                    isFromMe ? "text-white/50" : "text-[#7b7b78]"
                  }`}
                >
                  {isTemp ? "Enviando..." : formatTime(msg.created_at)}
                </p>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Digitar mensagem..."
          rows={1}
          className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32"
        />
        <button
          onClick={handleSend}
          disabled={sending || !text.trim()}
          className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex-shrink-0 self-end"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}

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
  const isMetaCloud = channel?.provider === "meta_cloud";

  const tagIdsRaw = (lead as unknown as Record<string, unknown>)?.tag_ids;
  const tagIds = Array.isArray(tagIdsRaw) ? (tagIdsRaw as string[]) : [];
  const leadTagIds = lead ? tags.filter((t) => tagIds.includes(t.id)) : [] as Tag[];

  return (
    <div className="flex-1 flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-white border-b border-[#e5e5dc]">
        <div className="w-10 h-10 rounded-full bg-[#c8cc8e] flex items-center justify-center text-white font-medium">
          {displayName.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1">
          <h2 className="text-[#1f1f1f] font-medium text-sm">{displayName}</h2>
          <p className="text-[#9ca3af] text-xs">{lead?.phone || ""}</p>
        </div>
        {channel && (
          <span
            className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
              isMetaCloud
                ? "bg-[#c8cc8e] text-[#1f1f1f]"
                : "bg-[#93c5fd] text-[#1e3a5f]"
            }`}
          >
            {channel.name}
          </span>
        )}
        {leadTagIds.length > 0 && (
          <div className="flex gap-1">
            {leadTagIds.map((tag) => (
              <span
                key={tag.id}
                className="px-2 py-0.5 rounded-full text-xs text-white"
                style={{ backgroundColor: tag.color }}
              >
                {tag.name}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2 bg-[#f6f7ed]">
        {loading && (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin" />
          </div>
        )}
        {!loading && displayMessages.length === 0 && (
          <p className="text-[#9ca3af] text-sm text-center py-8">Nenhuma mensagem.</p>
        )}
        {displayMessages.map((msg) => {
          const isFromMe =
            msg.role === "assistant" ||
            msg.sent_by === "agent" ||
            msg.sent_by === "seller";
          const isTemp = msg.id.startsWith("temp_");
          return (
            <div
              key={msg.id}
              className={`flex ${isFromMe ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[70%] px-3 py-2 ${
                  isFromMe
                    ? "bg-[#1f1f1f] text-white rounded-2xl rounded-br-sm"
                    : "bg-white border border-[#e5e5dc] text-[#1f1f1f] rounded-2xl rounded-bl-sm"
                } ${isTemp ? "opacity-70" : ""}`}
              >
                <p className="text-sm whitespace-pre-wrap break-words">{msg.content}</p>
                <p
                  className={`text-[11px] mt-1 ${
                    isFromMe ? "text-white/50" : "text-[#9ca3af]"
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
      <div className="px-4 py-3 bg-white border-t border-[#e5e5dc]">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-[#f6f7ed] text-[#1f1f1f] text-sm rounded-2xl px-4 py-2.5 placeholder-[#9ca3af] outline-none focus:ring-1 focus:ring-[#c8cc8e] resize-none max-h-32 border border-[#e5e5dc]"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="bg-[#1f1f1f] text-white p-2.5 rounded-full hover:bg-[#333] disabled:opacity-50 flex-shrink-0 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
    </div>
  );
}

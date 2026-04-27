"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type { Message, Conversation, Tag } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import { getWindowStatus, formatTimeRemaining, windowExpiresInMs } from "@/lib/window-status";
import { WindowReactivatePanel } from "@/components/conversas/window-reactivate-panel";
import { ChatHeader } from "@/components/conversas/chat-header";
import { MessageList } from "@/components/conversas/message-list";

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
}

export function ChatView({ conversation, tags }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const { messages, loading } = useRealtimeMessages(lead?.id ?? null);
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [showReactivatePanel, setShowReactivatePanel] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const provider = channel?.provider ?? null;
  const lastCustomerMsgAt = lead?.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const isInputBlocked = windowStatus === "closed";
  const timeRemainingMs =
    windowStatus === "expiring" && lastCustomerMsgAt
      ? windowExpiresInMs(lastCustomerMsgAt)
      : 0;

  useEffect(() => {
    setOptimisticMessages([]);
    setShowReactivatePanel(false);
  }, [conversation.id]);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, [conversation.id]);

  const displayMessages = useMemo(
    () => [...messages, ...optimisticMessages],
    [messages, optimisticMessages]
  );

  async function handleSend() {
    if (!text.trim() || sendingRef.current || isInputBlocked) return;
    sendingRef.current = true;
    const content = text.trim();

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
      if (!res.ok) setText(content);
      setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
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

  return (
    <div className="flex-1 flex flex-col h-full bg-[#faf9f6]">
      <ChatHeader conversation={conversation} tags={tags} />

      <MessageList key={conversation.id} messages={displayMessages} loading={loading} />

      {/* Window status banner */}
      {windowStatus === "expiring" && (
        <div className="bg-[#fef3c7] border-t border-[#f59e0b]/30 px-4 py-2 flex items-center gap-2 flex-shrink-0">
          <span className="text-[12px] text-[#92400e]">
            ⏱ Janela expira em {formatTimeRemaining(timeRemainingMs)} — responda logo ou envie um template.
          </span>
        </div>
      )}
      {windowStatus === "closed" && (
        <div className="bg-[#fff7ed] border-t border-[#f97316]/30 px-4 py-2 flex items-center justify-between gap-2 flex-shrink-0">
          <span className="text-[12px] text-[#7c2d12]">
            🔴 Janela de 24h encerrada. Não é possível enviar mensagens de texto livre.
          </span>
          <button
            onClick={() => setShowReactivatePanel((v) => !v)}
            className="flex-shrink-0 text-[12px] bg-[#111111] text-white px-3 py-1.5 rounded-[4px] hover:opacity-90 transition-opacity whitespace-nowrap"
          >
            Reativar conversa
          </button>
        </div>
      )}

      {showReactivatePanel && windowStatus === "closed" && (
        <WindowReactivatePanel
          conversation={conversation}
          onClose={() => setShowReactivatePanel(false)}
        />
      )}

      {/* Input */}
      <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2 flex-shrink-0">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isInputBlocked ? "Janela encerrada — use Reativar conversa" : "Digitar mensagem..."}
          rows={1}
          disabled={isInputBlocked}
          className={`flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32 ${isInputBlocked ? "opacity-40 cursor-not-allowed" : ""}`}
        />
        <button
          onClick={handleSend}
          disabled={sending || !text.trim() || isInputBlocked}
          className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex-shrink-0 self-end"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
    </div>
  );
}

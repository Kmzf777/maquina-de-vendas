"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type { Message, Conversation, Tag } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import { getWindowStatus } from "@/lib/window-status";
import { TemplateDispatchModal } from "@/components/conversas/template-dispatch-modal";
import { ChatHeader } from "@/components/conversas/chat-header";
import { MessageList } from "@/components/conversas/message-list";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
}

export function ChatView({ conversation, tags, aiEnabled, togglingAi, onToggleAi }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const { messages, loading } = useRealtimeMessages(lead?.id ?? null);
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [dispatchSuccess, setDispatchSuccess] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const provider = channel?.provider ?? null;
  const lastCustomerMsgAt = lead?.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const isInputBlocked = windowStatus === "closed";
  useEffect(() => {
    setOptimisticMessages([]);
    setShowTemplateModal(false);
    setDispatchSuccess(false);
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
      <ChatHeader
        conversation={conversation}
        tags={tags}
        aiEnabled={aiEnabled}
        togglingAi={togglingAi}
        onToggleAi={onToggleAi}
      />

      <MessageList
        key={conversation.id}
        messages={displayMessages}
        loading={loading}
        conversationId={conversation.id}
      />

      <WhatsappWindowIndicator
        expiresAt={conversation.whatsapp_window_expires_at}
        variant="banner"
        onReactivate={() => setShowTemplateModal(true)}
      />

      {/* Input or locked dispatch card */}
      {isInputBlocked ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-4 flex-shrink-0">
          {dispatchSuccess ? (
            <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] px-4 py-3 flex items-center gap-3">
              <span className="inline-block h-2 w-2 rounded-full bg-[#5aad65] flex-shrink-0" />
              <p className="text-[13px] text-[#111111]">
                Template enviado. Aguardando resposta do lead para reabrir a janela.
              </p>
            </div>
          ) : (
            <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] px-4 py-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-[13px] font-medium text-[#111111]">Janela de 24h encerrada</p>
                <p className="text-[12px] text-[#7b7b78] mt-0.5">
                  Envie um template aprovado para reabrir a conversa.
                </p>
              </div>
              <button
                onClick={() => setShowTemplateModal(true)}
                className="bg-[#111111] text-white text-[13px] px-4 py-2 rounded-[4px] transition-transform hover:scale-110 active:scale-[0.85] flex-shrink-0"
              >
                Iniciar disparo
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2 flex-shrink-0">
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
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      )}

      {showTemplateModal && (
        <TemplateDispatchModal
          conversation={conversation}
          onClose={() => setShowTemplateModal(false)}
          onSuccess={() => {
            setShowTemplateModal(false);
            setDispatchSuccess(true);
          }}
        />
      )}
    </div>
  );
}

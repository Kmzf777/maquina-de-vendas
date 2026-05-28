"use client";

import { useRef, useEffect, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import type { Message } from "@/lib/types";
import { DaySeparator } from "@/components/conversas/day-separator";
import { MessageBubble } from "@/components/conversas/message-bubble";
import { EventCard } from "@/components/conversas/event-card";

interface MessageListProps {
  messages: Message[];
  loading: boolean;
  conversationId: string;
  onReply?: (msg: Message) => void;
}

export interface MessageListHandle {
  scrollToBottom: () => void;
  scrollToMessage: (messageId: string) => void;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getDate() === b.getDate() &&
    a.getMonth() === b.getMonth() &&
    a.getFullYear() === b.getFullYear()
  );
}

function isGrouped(current: Message, previous: Message | undefined): boolean {
  if (!previous) return false;
  if (current.role !== previous.role) return false;
  const diff =
    new Date(current.created_at).getTime() -
    new Date(previous.created_at).getTime();
  return diff < 2 * 60 * 1000; // < 2 minutes
}

export const MessageList = forwardRef<MessageListHandle, MessageListProps>(
  function MessageList({ messages, loading, conversationId, onReply }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const bottomRef = useRef<HTMLDivElement>(null);
    const [showScrollButton, setShowScrollButton] = useState(false);
    const [unreadCount, setUnreadCount] = useState(0);
    const prevMessageCountRef = useRef(messages.length);
    const isAtBottomRef = useRef(true);
    const messageRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
    const [highlightedId, setHighlightedId] = useState<string | null>(null);

    useImperativeHandle(ref, () => ({
      scrollToBottom() {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      },
      scrollToMessage(id: string) {
        const el = messageRefsMap.current.get(id);
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        setHighlightedId(id);
        setTimeout(() => setHighlightedId(null), 1500);
      },
    }));

    const handleScroll = useCallback(() => {
      const el = containerRef.current;
      if (!el) return;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      const atBottom = distanceFromBottom < 100;
      isAtBottomRef.current = atBottom;
      setShowScrollButton(!atBottom);
      if (atBottom) setUnreadCount(0);
    }, []);

    // Auto-scroll on new messages if already at bottom; increment badge if not
    useEffect(() => {
      const newCount = messages.length;
      const prevCount = prevMessageCountRef.current;
      if (newCount > prevCount) {
        if (isAtBottomRef.current) {
          bottomRef.current?.scrollIntoView({ behavior: "smooth" });
          setUnreadCount(0);
        } else {
          setUnreadCount((c) => c + (newCount - prevCount));
        }
      }
      prevMessageCountRef.current = newCount;
    }, [messages.length]);

    // Initial scroll to bottom on mount / conversation switch
    useEffect(() => {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
      setUnreadCount(0);
      prevMessageCountRef.current = messages.length;
    }, []);  // eslint-disable-line react-hooks/exhaustive-deps

    function scrollToBottom() {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      setUnreadCount(0);
    }

    return (
      <div className="relative flex-1 overflow-hidden">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto px-4 py-4 bg-[#faf9f6]"
        >
          {loading && (
            <div className="flex justify-center py-8">
              <div className="w-6 h-6 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin" />
            </div>
          )}
          {!loading && messages.length === 0 && (
            <p className="text-[#7b7b78] text-sm text-center py-8">
              Nenhuma mensagem.
            </p>
          )}

          {messages.map((msg, idx) => {
            const prev = messages[idx - 1];
            const currDate = new Date(msg.created_at);
            const prevDate = prev ? new Date(prev.created_at) : null;
            const showDaySep = !prevDate || !isSameDay(currDate, prevDate);
            const grouped = isGrouped(msg, prev);
            const isHighlighted = highlightedId === msg.id;

            return (
              <div
                key={msg.id}
                ref={(el) => {
                  if (el) messageRefsMap.current.set(msg.id, el);
                  else messageRefsMap.current.delete(msg.id);
                }}
                className={`transition-colors duration-300 rounded-lg ${
                  isHighlighted ? "bg-yellow-100/60" : ""
                }`}
              >
                {showDaySep && <DaySeparator date={currDate} />}
                {msg.role === "system" ? (
                  <EventCard message={msg} />
                ) : (
                  <MessageBubble
                    message={msg}
                    isGrouped={grouped}
                    conversationId={conversationId}
                    onReply={onReply}
                    onScrollToMessage={(targetId) => {
                      const el = messageRefsMap.current.get(targetId);
                      if (!el) return;
                      el.scrollIntoView({ behavior: "smooth", block: "center" });
                      setHighlightedId(targetId);
                      setTimeout(() => setHighlightedId(null), 1500);
                    }}
                  />
                )}
              </div>
            );
          })}

          <div ref={bottomRef} />
        </div>

        {showScrollButton && (
          <button
            onClick={scrollToBottom}
            className="absolute bottom-4 right-4 w-9 h-9 bg-[#111111] text-white rounded-full shadow-lg flex items-center justify-center hover:opacity-90 transition-opacity"
          >
            {unreadCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] bg-red-500 text-white text-[10px] font-medium rounded-full flex items-center justify-center px-1">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        )}
      </div>
    );
  }
);

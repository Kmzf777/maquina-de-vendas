"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Message, QuotedMessage } from "@/lib/types";

function enrichWithQuotedMessages(raw: Message[]): Message[] {
  const wamidMap = new Map<string, Message>();
  const idMap = new Map<string, Message>();
  for (const msg of raw) {
    if (msg.wamid) wamidMap.set(msg.wamid, msg);
    idMap.set(msg.id, msg);
  }
  return raw.map((msg) => {
    const hasQuote = msg.quoted_wamid || msg.quoted_message_id;
    if (!hasQuote) return msg;
    const original =
      (msg.quoted_wamid ? wamidMap.get(msg.quoted_wamid) : undefined) ??
      (msg.quoted_message_id ? idMap.get(msg.quoted_message_id) : undefined);
    const quoted: QuotedMessage | null = original
      ? { id: original.id, content: original.content, role: original.role, message_type: original.message_type ?? null }
      : null;
    return { ...msg, quoted_message: quoted };
  });
}

export function useRealtimeMessages(conversationId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = useMemo(() => createClient(), []);

  const fetchMessages = useCallback(async () => {
    if (!conversationId) {
      setMessages([]);
      setLoading(false);
      return;
    }

    const { data } = await supabase
      .from("messages")
      .select("*")
      .eq("conversation_id", conversationId)
      .order("created_at", { ascending: false });

    if (data) setMessages(enrichWithQuotedMessages([...data].reverse() as Message[]));
    setLoading(false);
  }, [conversationId, supabase]);

  useEffect(() => {
    // Reset state immediately on conversationId change to avoid stale message flash
    setMessages([]);
    setLoading(true);
    fetchMessages();

    if (!conversationId) return;

    const channel = supabase
      .channel(`messages-conv-${conversationId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "messages",
          filter: `conversation_id=eq.${conversationId}`,
        },
        (payload) => {
          setMessages((prev) => enrichWithQuotedMessages([...prev, payload.new as Message]));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [conversationId, fetchMessages, supabase]);

  return { messages, loading, refetch: fetchMessages };
}

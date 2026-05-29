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

export function useRealtimeMessages(leadId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = useMemo(() => createClient(), []);

  const fetchMessages = useCallback(async () => {
    if (!leadId) {
      setMessages([]);
      setLoading(false);
      return;
    }

    const { data } = await supabase
      .from("messages")
      .select("*")
      .eq("lead_id", leadId)
      .order("created_at", { ascending: false });

    if (data) setMessages(enrichWithQuotedMessages([...data].reverse() as Message[]));
    setLoading(false);
  }, [leadId, supabase]);

  useEffect(() => {
    // Reset state immediately on leadId change to avoid stale message flash
    setMessages([]);
    setLoading(true);
    fetchMessages();

    if (!leadId) return;

    const channel = supabase
      .channel(`messages-${leadId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "messages",
          filter: `lead_id=eq.${leadId}`,
        },
        (payload) => {
          setMessages((prev) => enrichWithQuotedMessages([...prev, payload.new as Message]));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [leadId, fetchMessages, supabase]);

  return { messages, loading, refetch: fetchMessages };
}

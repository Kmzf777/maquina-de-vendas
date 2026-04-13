"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Message } from "@/lib/types";

export function useRealtimeMessages(leadId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

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
      .order("created_at", { ascending: true })
      .limit(200);

    if (data) setMessages(data);
    setLoading(false);
  }, [leadId]);

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
          setMessages((prev) => [...prev, payload.new as Message]);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [leadId, fetchMessages]);

  return { messages, loading };
}

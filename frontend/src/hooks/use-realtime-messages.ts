"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  MESSAGE_PAGE_SIZE,
  enrichWithQuotedMessages,
  mergeOlderPage,
  normalizeOrder,
  pageHasMore,
} from "@/lib/messages-window";
import type { Message } from "@/lib/types";

export function useRealtimeMessages(conversationId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const supabase = useMemo(() => createClient(), []);
  // Guardas contra corrida em troca rápida de conversa: respostas da conversa
  // anterior não podem sobrescrever a atual.
  const convRef = useRef(conversationId);
  useEffect(() => {
    convRef.current = conversationId;
  }, [conversationId]);
  // Espelho síncrono p/ loadOlder ler o cursor (created_at mais antigo carregado).
  const messagesRef = useRef<Message[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const fetchMessages = useCallback(async () => {
    if (!conversationId) {
      setMessages([]);
      setLoading(false);
      setHasMore(false);
      return;
    }

    // Janela: só as MESSAGE_PAGE_SIZE mais recentes (desc + reverse). Antes era a
    // thread inteira sem limit — o maior custo de egress/render do chat.
    const { data } = await supabase
      .from("messages")
      .select("*")
      .eq("conversation_id", conversationId)
      .order("created_at", { ascending: false })
      .limit(MESSAGE_PAGE_SIZE);

    if (convRef.current !== conversationId) return; // resposta obsoleta
    if (data) {
      setMessages(enrichWithQuotedMessages([...data].reverse() as Message[]));
      setHasMore(pageHasMore(data.length));
    }
    setLoading(false);
  }, [conversationId, supabase]);

  /** Pagina para trás: busca a página anterior ao cursor e faz prepend. */
  const loadOlder = useCallback(async () => {
    const oldest = messagesRef.current[0]?.created_at;
    if (!conversationId || !oldest) return;
    setLoadingOlder(true);
    try {
      const { data } = await supabase
        .from("messages")
        .select("*")
        .eq("conversation_id", conversationId)
        .lt("created_at", oldest)
        .order("created_at", { ascending: false })
        .limit(MESSAGE_PAGE_SIZE);
      if (convRef.current !== conversationId || !data) return;
      const olderAsc = [...data].reverse() as Message[];
      setMessages((prev) => mergeOlderPage(prev, olderAsc));
      setHasMore(pageHasMore(data.length));
    } finally {
      setLoadingOlder(false);
    }
  }, [conversationId, supabase]);

  useEffect(() => {
    // Reset state immediately on conversationId change to avoid stale message flash
    setMessages([]);
    setLoading(true);
    setHasMore(false);
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
          setMessages((prev) => enrichWithQuotedMessages(normalizeOrder([...prev, payload.new as Message])));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [conversationId, fetchMessages, supabase]);

  return { messages, loading, refetch: fetchMessages, hasMore, loadOlder, loadingOlder };
}

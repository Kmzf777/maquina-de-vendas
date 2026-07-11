"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  MESSAGE_PAGE_SIZE,
  collectUnresolvedWamids,
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
  // Fallback de resolução de wamid (citação/reação mais antiga que a janela):
  // linhas buscadas dirigidamente no banco, só para enriquecimento — nunca
  // entram na thread. `missing` evita refetch eterno de wamids inexistentes
  // (legado pré-10/07 sem wamid gravado = irrecuperável, fail-soft).
  const lookupRef = useRef<Map<string, Message>>(new Map());
  const missingRef = useRef<Set<string>>(new Set());

  const reEnrich = useCallback(
    (msgs: Message[]) => enrichWithQuotedMessages(msgs, [...lookupRef.current.values()]),
    [],
  );

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
      setMessages(reEnrich([...data].reverse() as Message[]));
      setHasMore(pageHasMore(data.length));
    }
    setLoading(false);
  }, [conversationId, supabase, reEnrich]);

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
      setMessages((prev) => mergeOlderPage(prev, olderAsc, [...lookupRef.current.values()]));
      setHasMore(pageHasMore(data.length));
    } finally {
      setLoadingOlder(false);
    }
  }, [conversationId, supabase]);

  // Resolução dirigida: wamids citados/reagidos que a janela não contém são
  // buscados uma única vez no banco e entram no cache de lookup; wamids que o
  // banco também não tem entram em `missing` e mantêm o fallback visual.
  useEffect(() => {
    if (!conversationId || messages.length === 0) return;
    const unresolved = collectUnresolvedWamids(messages).filter(
      (w) => !lookupRef.current.has(w) && !missingRef.current.has(w),
    );
    if (unresolved.length === 0) return;
    let cancelled = false;
    (async () => {
      const { data } = await supabase
        .from("messages")
        .select("id, wamid, content, role, message_type, created_at")
        .eq("conversation_id", conversationId)
        .in("wamid", unresolved);
      if (cancelled || convRef.current !== conversationId) return;
      for (const w of unresolved) missingRef.current.add(w);
      const rows = (data ?? []) as Message[];
      if (rows.length === 0) return;
      for (const row of rows) {
        if (row.wamid) {
          lookupRef.current.set(row.wamid, row);
          missingRef.current.delete(row.wamid);
        }
      }
      setMessages((prev) => reEnrich(prev));
    })();
    return () => {
      cancelled = true;
    };
  }, [messages, conversationId, supabase, reEnrich]);

  useEffect(() => {
    // Reset state immediately on conversationId change to avoid stale message flash
    setMessages([]);
    setLoading(true);
    setHasMore(false);
    lookupRef.current = new Map();
    missingRef.current = new Set();
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
          setMessages((prev) => reEnrich(normalizeOrder([...prev, payload.new as Message])));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [conversationId, fetchMessages, supabase, reEnrich]);

  return { messages, loading, refetch: fetchMessages, hasMore, loadOlder, loadingOlder };
}

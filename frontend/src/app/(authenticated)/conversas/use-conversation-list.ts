"use client";

/**
 * Estado vivo da lista de conversas: cache paginado (React Query infinite), contadores
 * do servidor, seleção derivada do cache e a inscrição Realtime que mantém tudo isso
 * atualizado sem refetch integral por evento.
 *
 * Saiu de `page.tsx` para poder ser testado com um QueryClient de verdade, `fetch`
 * falso e um canal Realtime falso (ver `use-conversation-list.test.tsx`). A página
 * fica só com os handlers de UI (toggles, tags, deep-link) e o layout.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { createClient } from "@/lib/supabase/client";
import { debounce } from "@/lib/debounce";
import { onResubscribe } from "@/lib/realtime-resync";
import {
  applyConversationUpdate,
  isBlockedConversationRow,
  previewFromMessage,
  type ConversationRow,
} from "@/lib/conversations-live";
import {
  conversationsListUrl,
  type ConversationCounts,
  type ConversationsPage,
} from "@/app/api/conversations/list-params";
import {
  conversationBelongsToKey,
  conversationsQueryKey,
  flattenPages,
  insertIntoPages,
  isWithinLoadedWindow,
  patchPages,
  shouldFetchUnknownRow,
  type ConversationPages,
} from "./conversation-pages";
import type { Conversation, Lead } from "@/lib/types";

// Espera do refetch integral disparado por eventos que o patch local não cobre
// (conversa nova/desconhecida). Rajadas colapsam em 1 invalidação.
export const REFETCH_DEBOUNCE_MS = 3_000;
// Conversa desconhecida que recebeu UPDATE: até este tanto, busca uma a uma pelo id
// (barato); acima, uma invalidação integral sai mais em conta.
const MAX_SINGLE_FETCHES = 10;
// Conversa buscada que não pertence à aba ativa: ignora novos UPDATEs dela por 1 min
// (aba de segmento não sabe o estágio do lead pela linha crua do Realtime).
export const IGNORE_OUTSIDE_TAB_MS = 60_000;

type SupabaseBrowserClient = ReturnType<typeof createClient>;

export function useConversationList({
  supabase,
  channelId,
  activeTab,
}: {
  supabase: SupabaseBrowserClient;
  channelId: string;
  activeTab: string;
}) {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Overrides temporais contra o realtime sobrescrever estado otimista:
  // mark-read e toggles em voo vencem pushes/refetches por ~30s.
  const recentlyMarkedRef = useRef<Map<string, number>>(new Map());
  const recentlyToggledAiRef = useRef<Map<string, boolean>>(new Map());
  const recentlyToggledFollowupRef = useRef<Map<string, boolean>>(new Map());

  const applyOverrides = useCallback((list: Conversation[]): Conversation[] => {
    const now = Date.now();
    for (const [id, ts] of recentlyMarkedRef.current) {
      if (now - ts > 30_000) recentlyMarkedRef.current.delete(id);
    }
    return list.map((c) => {
      let out = c;
      if (recentlyMarkedRef.current.has(c.id)) out = { ...out, unread_count: 0 };
      const pendingAi = recentlyToggledAiRef.current.get(c.id);
      if (pendingAi !== undefined)
        out = { ...out, leads: { ...(out.leads as Lead), ai_enabled: pendingAi } };
      const pendingFollowup = recentlyToggledFollowupRef.current.get(c.id);
      if (pendingFollowup !== undefined) out = { ...out, followup_enabled: pendingFollowup };
      return out;
    });
  }, []);

  /** Mark-read local: payload Realtime atrasado não ressuscita o badge por ~30s. */
  const noteMarkedRead = useCallback((id: string) => {
    recentlyMarkedRef.current.set(id, Date.now());
  }, []);
  /** Toggle de IA em voo (null = terminou): o valor otimista vence refetches. */
  const setPendingAi = useCallback((id: string, value: boolean | null) => {
    if (value === null) recentlyToggledAiRef.current.delete(id);
    else recentlyToggledAiRef.current.set(id, value);
  }, []);
  /** Toggle de follow-up em voo (null = terminou): vence payloads Realtime e refetches. */
  const setPendingFollowup = useCallback((id: string, value: boolean | null) => {
    if (value === null) recentlyToggledFollowupRef.current.delete(id);
    else recentlyToggledFollowupRef.current.set(id, value);
  }, []);

  // Lista PAGINADA por cursor (200 por página): o PostgREST corta toda leitura em
  // 1.000 linhas, então a lista inteira de uma vez cobria só ~11 dias. A aba é filtro
  // de servidor — um cache por canal + aba. latest-wins/abort/keep-previous seguem
  // sendo semântica nativa da queryKey + placeholderData.
  const {
    data: pagesData,
    isPending: convPending,
    isError: listError,
    isPlaceholderData: isRefreshing,
    refetch: refetchConversations,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useInfiniteQuery({
    queryKey: conversationsQueryKey(channelId, activeTab),
    queryFn: async ({ signal, pageParam }): Promise<ConversationsPage<Conversation>> => {
      const url = conversationsListUrl({ channelId, tab: activeTab, cursor: pageParam });
      const res = await fetch(url, { signal });
      if (!res.ok) throw new Error(`conversations ${res.status}`);
      const data = await res.json();
      const list: Conversation[] = Array.isArray(data?.conversations) ? data.conversations : [];
      return {
        conversations: applyOverrides(list),
        next_cursor: typeof data?.next_cursor === "string" ? data.next_cursor : null,
      };
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    placeholderData: keepPreviousData,
  });
  const conversations = useMemo(() => flattenPages(pagesData), [pagesData]);

  // Contadores do servidor: o badge de "Não lidas" e o total não podem contar só o
  // que está carregado.
  const { data: counts } = useQuery({
    queryKey: ["conversation-counts", channelId],
    queryFn: async ({ signal }): Promise<ConversationCounts | null> => {
      const qs = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : "";
      const res = await fetch(`/api/conversations/counts${qs}`, { signal });
      if (!res.ok) return null;
      return (await res.json()) as ConversationCounts;
    },
    placeholderData: keepPreviousData,
  });

  const loadMore = useCallback(() => {
    if (isRefreshing || !hasNextPage || isFetchingNextPage) return;
    void fetchNextPage();
  }, [isRefreshing, hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Patch local em TODOS os caches da lista (um por canal + aba): a mesma conversa
  // pode estar na aba "Todos" e na de "Atacado", e a troca de aba não pode mostrar
  // um estado velho. A seleção continua DERIVADA do cache da aba ativa.
  //
  // A cópia guardada da conversa aberta (`held`) recebe o mesmo patch: é ela que
  // sustenta a seleção quando a conversa não está no cache da aba ativa.
  const [held, setHeld] = useState<Conversation | null>(null);
  const patchList = useCallback(
    (updater: (list: Conversation[]) => Conversation[]) => {
      queryClient.setQueriesData<ConversationPages>({ queryKey: ["conversations"] }, (old) =>
        old ? patchPages(old, updater) : old,
      );
      setHeld((prev) => (prev ? (updater([prev]).find((c) => c.id === prev.id) ?? null) : prev));
    },
    [queryClient],
  );

  const patchConversation = useCallback(
    (id: string, patch: Partial<Conversation> | ((c: Conversation) => Conversation)) => {
      patchList((list) =>
        list.map((c) =>
          c.id === id ? (typeof patch === "function" ? patch(c) : { ...c, ...patch }) : c,
        ),
      );
    },
    [patchList],
  );

  /** Põe `conv` no cache da aba ativa (sem mexer na cópia guardada da seleção). */
  const injectIntoActiveList = useCallback(
    (conv: Conversation) => {
      queryClient.setQueryData<ConversationPages>(
        conversationsQueryKey(channelId, activeTab),
        (old) => (old ? insertIntoPages(old, conv) : old),
      );
    },
    [queryClient, channelId, activeTab],
  );

  /**
   * Injeta no cache da lista ATIVA uma conversa que veio de fora dela (busca de
   * contatos, resultado de mensagem, deep-link, irmã) e a guarda como cópia da
   * seleção. Sem isso a seleção é derivada de `conversations.find` e cairia num
   * fallback que não recebe os patches (toggle de IA, mark-read).
   */
  const ensureInList = useCallback(
    (conv: Conversation) => {
      setHeld(conv);
      injectIntoActiveList(conv);
    },
    [injectIntoActiveList],
  );

  /** Busca avulsa de uma conversa fora da lista carregada. null = sem acesso/inexistente. */
  const fetchConversationById = useCallback(async (id: string): Promise<Conversation | null> => {
    try {
      const res = await fetch(`/api/conversations/${id}`);
      if (!res.ok) return null;
      return (await res.json()) as Conversation;
    } catch {
      return null;
    }
  }, []);

  // Seleção derivada do cache; fallback para a cópia guardada cobre o instante em
  // que a conversa sai da lista (paridade com o `updated ?? prev` antigo).
  const foundSelected = useMemo(
    () => (selectedId ? (conversations.find((c) => c.id === selectedId) ?? null) : null),
    [conversations, selectedId],
  );
  // Mantém a cópia guardada igual à do cache enquanto a conversa está nele (padrão
  // "ajustar estado durante o render": sem efeito, sem render a mais).
  if (foundSelected && foundSelected !== held) setHeld(foundSelected);
  const selectedConversation =
    foundSelected ?? (selectedId && held?.id === selectedId ? held : null);

  // A conversa aberta precisa estar no cache da aba ATIVA para receber os patches.
  // Antes havia um cache só com todas as abas; agora, ao trocar de aba (ou depois de
  // um refetch que não a traz mais), ela é reinjetada a partir do último objeto
  // conhecido. A aba continua escondendo-a da lista se não pertencer a ela.
  useEffect(() => {
    if (!selectedId || !pagesData || isRefreshing) return;
    if (foundSelected) return;
    if (held && held.id === selectedId) injectIntoActiveList(held);
  }, [selectedId, pagesData, isRefreshing, foundSelected, held, injectIntoActiveList]);

  // A aba ativa é lida por ref no handler do Realtime: trocar de aba não pode
  // derrubar e refazer a inscrição (cada re-inscrição tem custo e janela cega).
  const activeTabRef = useRef(activeTab);
  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  // Realtime SEM refetch integral por evento (corte de Egress): o payload do
  // UPDATE já traz a linha nova de `conversations` — aplicamos o delta no cache
  // e o preview vem do INSERT de `messages`. Conversa que não está na página
  // carregada é buscada sozinha pelo id (se couber na janela/aba); a invalidação
  // integral (debounced) fica para conversa nova (INSERT) e rajadas grandes.
  useEffect(() => {
    const invalidateAll = () => queryClient.invalidateQueries({ queryKey: ["conversations"] });
    const debouncedInvalidate = debounce(invalidateAll, REFETCH_DEBOUNCE_MS);
    const debouncedCounts = debounce(
      () => queryClient.invalidateQueries({ queryKey: ["conversation-counts"] }),
      REFETCH_DEBOUNCE_MS,
    );

    const pendingUnknown = new Set<string>();
    const ignoredUntil = new Map<string, number>();
    const flushUnknown = debounce(async () => {
      const ids = [...pendingUnknown];
      pendingUnknown.clear();
      if (ids.length === 0) return;
      if (ids.length > MAX_SINGLE_FETCHES) {
        void invalidateAll();
        return;
      }
      const fetched = await Promise.all(ids.map((id) => fetchConversationById(id)));
      const activeKey = conversationsQueryKey(channelId, activeTabRef.current);
      for (const conv of fetched) {
        if (!conv || isBlockedConversationRow(conv)) continue;
        const [fresh] = applyOverrides([conv]);
        for (const query of queryClient.getQueryCache().findAll({ queryKey: ["conversations"] })) {
          if (!conversationBelongsToKey(fresh, query.queryKey)) continue;
          queryClient.setQueryData<ConversationPages>(query.queryKey, (old) =>
            old ? insertIntoPages(old, fresh, { respectWindow: true }) : old,
          );
        }
        if (!conversationBelongsToKey(fresh, activeKey)) {
          ignoredUntil.set(fresh.id, Date.now() + IGNORE_OUTSIDE_TAB_MS);
        }
      }
    }, REFETCH_DEBOUNCE_MS);

    const applyRowPatch = (row: ConversationRow) => {
      const overrides = {
        forceUnreadZero: recentlyMarkedRef.current.has(row.id),
        pendingFollowup: recentlyToggledFollowupRef.current.get(row.id),
      };
      patchList((prev) => applyConversationUpdate(prev, row, overrides));
      // A regra de bloqueio REMOVE a linha (ver applyConversationUpdate), e a
      // removida pode ser justamente a aberta. A seleção é derivada do cache mas
      // tem fallback para o último objeto conhecido, então sem zerar o id o
      // operador ficaria olhando um chat fantasma — de um lead que acabou de
      // pedir para sair — com o composer ainda montado.
      if (isBlockedConversationRow(row)) {
        setSelectedId((cur) => (cur === row.id ? null : cur));
      }
    };

    const realtimeChannel = supabase
      .channel("conversations-updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        (payload) => {
          debouncedCounts(); // não lidas/total podem ter mudado
          if (payload.eventType === "DELETE") {
            const oldId = (payload.old as { id?: string } | null)?.id;
            if (!oldId) return;
            patchList((prev) => prev.filter((c) => c.id !== oldId));
            // Sem isto a reinjeção da conversa aberta a ressuscitaria na lista.
            setSelectedId((cur) => (cur === oldId ? null : cur));
            return;
          }
          const row = payload.new as ConversationRow;
          // Filtro de canal ativo: eventos de outros canais não pertencem à lista.
          if (channelId && row.channel_id !== channelId) return;
          if (payload.eventType === "INSERT") {
            debouncedInvalidate(); // linha crua não tem lead/channel — precisa da API
            return;
          }
          // Patch em todo cache que já conhece a conversa (inclusive o bloqueio, que
          // remove a linha sem precisar dos joins da API).
          applyRowPatch(row);
          if (isBlockedConversationRow(row)) return;

          const tab = activeTabRef.current;
          const cached = queryClient.getQueryData<ConversationPages>(
            conversationsQueryKey(channelId, tab),
          );
          if (!cached) {
            debouncedInvalidate(); // aba ainda sem dados (fetch anterior falhou/em voo)
            return;
          }
          if (flattenPages(cached).some((c) => c.id === row.id)) return;
          // Desconhecida: fora da janela carregada → a próxima página a trará; aba que
          // não pode contê-la → ignora; senão busca só ela pelo id.
          if (!isWithinLoadedWindow(cached, row.last_msg_at)) return;
          if (!shouldFetchUnknownRow(row, tab)) return;
          if ((ignoredUntil.get(row.id) ?? 0) > Date.now()) return;
          pendingUnknown.add(row.id);
          flushUnknown();
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages" },
        (payload) => {
          // Atualiza só o preview da conversa afetada — paridade com a RPC
          // get_last_messages (última mensagem vence, com prefixo por autor).
          const msg = payload.new as {
            conversation_id?: string | null;
            role?: string | null;
            sent_by?: string | null;
            content?: string | null;
          };
          if (!msg.conversation_id) return;
          const preview = previewFromMessage(msg);
          patchList((prev) =>
            prev.map((c) =>
              c.id === msg.conversation_id
                ? { ...c, last_message_text: preview.text, last_message_direction: preview.direction }
                : c,
            ),
          );
        },
      )
      // Volta do canal = houve um buraco. `postgres_changes` não tem replay, e a
      // lista é mantida por patches em memória, então tudo que aconteceu com o
      // socket fora ficaria defasado para sempre (só o F5 corrigia). Invalidação
      // integral aqui, sem debounce: reconexão é rara e precisa reconciliar já.
      .subscribe(
        onResubscribe(() => {
          void invalidateAll();
          void queryClient.invalidateQueries({ queryKey: ["conversation-counts"] });
        }),
      );

    return () => {
      debouncedInvalidate.cancel();
      debouncedCounts.cancel();
      flushUnknown.cancel();
      supabase.removeChannel(realtimeChannel);
    };
  }, [channelId, queryClient, supabase, patchList, applyOverrides, fetchConversationById]);

  return {
    conversations,
    pagesData,
    convPending,
    listError,
    isRefreshing,
    refetchConversations,
    hasNextPage: !!hasNextPage,
    isFetchingNextPage,
    loadMore,
    counts,
    selectedId,
    setSelectedId,
    selectedConversation,
    patchList,
    patchConversation,
    ensureInList,
    fetchConversationById,
    noteMarkedRead,
    setPendingAi,
    setPendingFollowup,
  };
}

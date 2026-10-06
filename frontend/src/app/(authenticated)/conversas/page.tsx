"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView, type SiblingConversationSummary } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import { debounce } from "@/lib/debounce";
import { onResubscribe } from "@/lib/realtime-resync";
import { setActiveConversation } from "@/lib/active-conversation";
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
import { ConversasQueryProvider } from "./query-provider";
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
import type { Conversation, Channel, Tag, Lead } from "@/lib/types";

// Espera do refetch integral disparado por eventos que o patch local não cobre
// (conversa nova/desconhecida). Rajadas colapsam em 1 invalidação.
const REFETCH_DEBOUNCE_MS = 3_000;
// Conversa desconhecida que recebeu UPDATE: até este tanto, busca uma a uma pelo id
// (barato); acima, uma invalidação integral sai mais em conta.
const MAX_SINGLE_FETCHES = 10;
// Conversa buscada que não pertence à aba ativa: ignora novos UPDATEs dela por 1 min
// (aba de segmento não sabe o estágio do lead pela linha crua do Realtime).
const IGNORE_OUTSIDE_TAB_MS = 60_000;

export default function ConversasPage() {
  return (
    <ConversasQueryProvider>
      <ConversasContent />
    </ConversasQueryProvider>
  );
}

function ConversasContent() {
  const supabase = createClient();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkApplied = useRef(false);
  const [selectedChannelId, setSelectedChannelId] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingScrollMessageId, setPendingScrollMessageId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("todos");
  const [togglingAi, setTogglingAi] = useState(false);
  const [togglingFollowup, setTogglingFollowup] = useState(false);
  const [mobileView, setMobileView] = useState<"list" | "chat" | "contact">("list");
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
    queryKey: conversationsQueryKey(selectedChannelId, activeTab),
    queryFn: async ({ signal, pageParam }): Promise<ConversationsPage<Conversation>> => {
      const url = conversationsListUrl({
        channelId: selectedChannelId,
        tab: activeTab,
        cursor: pageParam,
      });
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
    queryKey: ["conversation-counts", selectedChannelId],
    queryFn: async ({ signal }): Promise<ConversationCounts | null> => {
      const qs = selectedChannelId ? `?channel_id=${encodeURIComponent(selectedChannelId)}` : "";
      const res = await fetch(`/api/conversations/counts${qs}`, { signal });
      if (!res.ok) return null;
      return (await res.json()) as ConversationCounts;
    },
    placeholderData: keepPreviousData,
  });

  const handleLoadMore = useCallback(() => {
    if (isRefreshing || !hasNextPage || isFetchingNextPage) return;
    void fetchNextPage();
  }, [isRefreshing, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const { data: channels = [], isPending: channelsPending } = useQuery({
    queryKey: ["channels"],
    queryFn: async (): Promise<Channel[]> => {
      const res = await fetch("/api/channels");
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    },
  });

  const { data: tags = [], isPending: tagsPending } = useQuery({
    queryKey: ["tags"],
    queryFn: async (): Promise<Tag[]> => {
      const res = await fetch("/api/tags");
      if (!res.ok) return [];
      return res.json();
    },
  });

  // Patch local em TODOS os caches da lista (um por canal + aba): a mesma conversa
  // pode estar na aba "Todos" e na de "Atacado", e a troca de aba não pode mostrar
  // um estado velho. A seleção continua DERIVADA do cache da aba ativa.
  const patchList = useCallback(
    (updater: (list: Conversation[]) => Conversation[]) => {
      queryClient.setQueriesData<ConversationPages>({ queryKey: ["conversations"] }, (old) =>
        old ? patchPages(old, updater) : old,
      );
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

  /**
   * Injeta no cache da lista ATIVA uma conversa que veio de fora dela (busca de
   * contatos, resultado de mensagem, deep-link, irmã, ou a aberta depois de trocar
   * de aba). Sem isso a seleção é derivada de `conversations.find` e cairia no
   * fallback — que não recebe os patches (toggle de IA, mark-read).
   */
  const ensureInList = useCallback(
    (conv: Conversation) => {
      queryClient.setQueryData<ConversationPages>(
        conversationsQueryKey(selectedChannelId, activeTab),
        (old) => (old ? insertIntoPages(old, conv) : old),
      );
    },
    [queryClient, selectedChannelId, activeTab],
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

  // Seleção derivada do cache; fallback para o último objeto conhecido cobre o
  // instante em que a conversa sai da lista (paridade com o `updated ?? prev` antigo).
  const lastSelectedRef = useRef<Conversation | null>(null);
  const selectedConversation = useMemo(() => {
    const found = conversations.find((c) => c.id === selectedId) ?? null;
    if (found) lastSelectedRef.current = found;
    return found ?? (selectedId ? lastSelectedRef.current : null);
  }, [conversations, selectedId]);

  // Publica a conversa aberta para o popup de SLA (shell) não interromper a
  // resposta a este lead. Só publica seleção não-nula: o popup já grava o lead
  // antes de navegar pelo "Responder agora", e limpar no mount apagaria isso.
  const selectedConvId = selectedConversation?.id ?? null;
  const selectedLeadId = (selectedConversation?.leads as Lead | undefined | null)?.id ?? null;
  useEffect(() => {
    if (selectedConvId) setActiveConversation({ conversationId: selectedConvId, leadId: selectedLeadId });
  }, [selectedConvId, selectedLeadId]);
  useEffect(() => () => setActiveConversation({ conversationId: null, leadId: null }), []);

  // A conversa aberta precisa estar no cache da aba ATIVA para receber os patches.
  // Antes havia um cache só com todas as abas; agora, ao trocar de aba (ou depois de
  // um refetch que não a traz mais), ela é reinjetada a partir do último objeto
  // conhecido. A aba continua escondendo-a da lista se não pertencer a ela.
  useEffect(() => {
    if (!selectedId || !pagesData || isRefreshing) return;
    if (conversations.some((c) => c.id === selectedId)) return;
    const last = lastSelectedRef.current;
    if (last && last.id === selectedId) ensureInList(last);
  }, [selectedId, pagesData, isRefreshing, conversations, ensureInList]);

  // Deep-link: pre-select conversation by lead_id from URL param
  useEffect(() => {
    if (deepLinkApplied.current || convPending) return;
    const leadId = searchParams.get("lead_id");
    if (!leadId) return;

    deepLinkApplied.current = true;
    const match = conversations.find((c) => (c.leads as Lead | undefined | null)?.id === leadId);
    if (match) {
      setSelectedId(match.id);
      router.replace("/conversas");
      return;
    }

    // Lead fora da lista carregada (teto de linhas do PostgREST): busca sob
    // demanda em vez de ignorar o link em silêncio.
    void (async () => {
      try {
        const res = await fetch(conversationsListUrl({ leadId }));
        if (!res.ok) return;
        const data = (await res.json()) as ConversationsPage<Conversation>;
        const conv = Array.isArray(data?.conversations) ? data.conversations[0] : null; // a rota já ordena por last_msg_at desc
        if (!conv) return;
        lastSelectedRef.current = conv;
        ensureInList(conv);
        setSelectedId(conv.id);
      } catch {
        // deep-link é conveniência: falha silenciosa mantém a lista utilizável
      } finally {
        router.replace("/conversas");
      }
    })();
  }, [conversations, convPending, searchParams, router, ensureInList]);

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
      const activeKey = conversationsQueryKey(selectedChannelId, activeTabRef.current);
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
          if (selectedChannelId && row.channel_id !== selectedChannelId) return;
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
            conversationsQueryKey(selectedChannelId, tab),
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
  }, [selectedChannelId, queryClient, supabase, patchList, applyOverrides, fetchConversationById]);

  function handleSelectConversation(conv: Conversation) {
    // A lista pode entregar um resultado da busca server-side, que não está no
    // cache — sem injetar, a seleção derivada abriria o chat anterior.
    lastSelectedRef.current = conv;
    ensureInList(conv);
    setSelectedId(conv.id);
    setPendingScrollMessageId(null);
    setMobileView("chat");
  }

  async function handleSelectMessageResult(conversationId: string, messageId: string) {
    if (!conversations.some((c) => c.id === conversationId)) {
      // Conversa fora da lista carregada: busca antes de selecionar. Antes isso
      // era um `return` mudo — o clique no resultado simplesmente não fazia nada.
      const conv = await fetchConversationById(conversationId);
      if (!conv) return;
      lastSelectedRef.current = conv;
      ensureInList(conv);
    }
    setSelectedId(conversationId);
    setPendingScrollMessageId(messageId);
    setMobileView("chat");
  }

  async function handleMarkRead(conversationId: string) {
    // Track immediately so any realtime push that fires before the response
    // can be overridden client-side
    recentlyMarkedRef.current.set(conversationId, Date.now());
    patchConversation(conversationId, { unread_count: 0 });
    try {
      await fetch(`/api/conversations/${conversationId}/mark-read`, { method: "POST" });
      void queryClient.invalidateQueries({ queryKey: ["conversation-counts"] });
    } catch (err) {
      console.warn("[mark-read] failed:", err);
    }
  }

  function handleChannelChange(channelId: string) {
    setSelectedChannelId(channelId);
    setSelectedId(null);
    setMobileView("list");
    // feedback do filtro novo = isPlaceholderData (keepPreviousData) — sem flag manual
  }

  const patchLeadFlag = useCallback(
    (conversationId: string, aiEnabled: boolean) => {
      patchConversation(conversationId, (c) => ({
        ...c,
        leads: { ...(c.leads as Lead), ai_enabled: aiEnabled },
      }));
    },
    [patchConversation],
  );

  async function handleToggleAi() {
    if (!selectedConversation || togglingAi) return;
    const conversationId = selectedConversation.id;
    const currentAiEnabled = (selectedConversation.leads as Lead | null)?.ai_enabled ?? true;
    const next = !currentAiEnabled;
    setTogglingAi(true);
    recentlyToggledAiRef.current.set(conversationId, next);
    patchLeadFlag(conversationId, next); // otimista
    try {
      const res = await fetch(`/api/conversations/${conversationId}/agent`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ai_enabled: next }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      // Confirm against server value — protects against silent backend failures
      const data = await res.json();
      patchLeadFlag(conversationId, data?.leads?.ai_enabled ?? next);
    } catch (err) {
      console.warn("[toggle-ai] failed:", err);
      patchLeadFlag(conversationId, !next); // rollback
    } finally {
      recentlyToggledAiRef.current.delete(conversationId);
      setTogglingAi(false);
    }
  }

  async function handleToggleFollowup() {
    if (!selectedConversation || togglingFollowup) return;
    const conversationId = selectedConversation.id;
    const current = selectedConversation.followup_enabled ?? true;
    const next = !current;
    setTogglingFollowup(true);
    recentlyToggledFollowupRef.current.set(conversationId, next);
    patchConversation(conversationId, { followup_enabled: next }); // otimista
    try {
      const res = await fetch(`/api/conversations/${conversationId}/followup`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
    } catch (err) {
      console.warn("[toggle-followup] failed:", err);
      patchConversation(conversationId, { followup_enabled: current }); // rollback
    } finally {
      recentlyToggledFollowupRef.current.delete(conversationId);
      setTogglingFollowup(false);
    }
  }

  const selectedLead = selectedConversation?.leads as Lead | undefined | null;

  // Tags SÓ do lead aberto: o mapa global de `lead_tags` (5,4k linhas) era cortado
  // em 1.000 pelo PostgREST e mostrava tags erradas no painel.
  const { data: selectedLeadTagIds } = useQuery({
    queryKey: ["lead-tags", selectedLeadId],
    enabled: !!selectedLeadId,
    queryFn: async (): Promise<string[]> => {
      const { data, error } = await supabase
        .from("lead_tags")
        .select("tag_id")
        .eq("lead_id", selectedLeadId as string);
      if (error) throw error;
      return (data ?? []).map((row: { tag_id: string }) => row.tag_id);
    },
  });

  const selectedLeadTags = selectedLeadTagIds
    ? tags.filter((t) => selectedLeadTagIds.includes(t.id))
    : [];

  // Conversas irmãs (mesmo lead, outro canal) vêm do servidor: a lista paginada
  // não garante que elas estejam carregadas.
  const { data: siblingRows = [] } = useQuery({
    queryKey: ["conversation-siblings", selectedLeadId, selectedChannelId],
    enabled: !!selectedLeadId,
    queryFn: async ({ signal }): Promise<Conversation[]> => {
      const res = await fetch(
        conversationsListUrl({ channelId: selectedChannelId, leadId: selectedLeadId as string }),
        { signal },
      );
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data?.conversations) ? data.conversations : [];
    },
  });

  const siblingConversations: SiblingConversationSummary[] = selectedConversation
    ? siblingRows
        .filter(
          (c) =>
            c.lead_id === selectedConversation.lead_id &&
            c.id !== selectedConversation.id,
        )
        .map((c) => ({
          id: c.id,
          channelName: c.channels?.name ?? "Outro canal",
        }))
    : [];

  function handleSelectSibling(id: string) {
    const sibling =
      conversations.find((c) => c.id === id) ?? siblingRows.find((c) => c.id === id);
    if (sibling) handleSelectConversation(sibling);
  }

  function handleLeadUpdate(leadId: string, patch: Partial<Lead>) {
    patchList((prev) =>
      prev.map((c) =>
        (c.leads as Lead)?.id === leadId
          ? { ...c, leads: { ...(c.leads as Lead), ...patch } }
          : c,
      ),
    );
  }

  async function handleTagToggle(tagId: string, add: boolean) {
    // Tags do lead ainda não carregadas: gravar agora sobrescreveria as existentes.
    if (!selectedLead || !selectedLeadTagIds) return;

    const newTagIds = add
      ? [...selectedLeadTagIds, tagId]
      : selectedLeadTagIds.filter((id) => id !== tagId);

    const res = await fetch(`/api/leads/${selectedLead.id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tagIds: newTagIds }),
    });

    if (res.ok) {
      queryClient.setQueryData<string[]>(["lead-tags", selectedLead.id], newTagIds);
    }
  }

  const initialLoading = channelsPending || tagsPending || (convPending && !isRefreshing);
  const openTotal = counts?.total ?? conversations.length;

  if (initialLoading) {
    return (
      <div className="flex items-center justify-center h-full bg-[#faf9f6]">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin mx-auto mb-3" />
          <p className="text-[#7b7b78] text-sm">Carregando conversas...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-w-0 overflow-hidden bg-[#faf9f6]">

      {/* Mobile: one panel at a time */}
      <div className={`md:hidden flex-1 min-w-0 flex-col h-full ${mobileView === "list" ? "flex" : "hidden"}`}>
        <ChatList
          conversations={conversations}
          channels={channels}
          activeTab={activeTab}
          selectedConversationId={selectedConversation?.id || null}
          selectedChannelId={selectedChannelId}
          onSelectConversation={handleSelectConversation}
          onMarkRead={handleMarkRead}
          onTabChange={setActiveTab}
          onChannelChange={handleChannelChange}
          listError={listError}
          isRefreshing={isRefreshing}
          onRetry={() => refetchConversations()}
          onSelectMessageResult={handleSelectMessageResult}
          unreadTotal={counts?.unread}
          hasMore={!!hasNextPage && !isRefreshing}
          loadingMore={isFetchingNextPage}
          onLoadMore={handleLoadMore}
        />
      </div>

      <div className={`md:hidden flex-1 min-w-0 flex-col h-full ${mobileView === "chat" && selectedConversation ? "flex" : "hidden"}`}>
        {selectedConversation && (
          <ChatView
            conversation={selectedConversation}
            tags={tags}
            aiEnabled={(selectedConversation.leads as Lead | null)?.ai_enabled ?? true}
            togglingAi={togglingAi}
            onToggleAi={handleToggleAi}
            followupEnabled={selectedConversation.followup_enabled ?? true}
            togglingFollowup={togglingFollowup}
            onToggleFollowup={handleToggleFollowup}
            onMarkRead={() => handleMarkRead(selectedConversation.id)}
            onBack={() => setMobileView("list")}
            onOpenContact={() => setMobileView("contact")}
            siblingConversations={siblingConversations}
            onSelectSibling={handleSelectSibling}
            targetMessageId={pendingScrollMessageId}
            onTargetConsumed={() => setPendingScrollMessageId(null)}
          />
        )}
      </div>

      <div className={`md:hidden flex-1 min-w-0 flex-col h-full overflow-y-auto ${mobileView === "contact" && selectedConversation ? "flex" : "hidden"}`}>
        {selectedConversation && (
          <ContactDetail
            conversation={selectedConversation}
            tags={tags}
            leadTags={selectedLeadTags}
            onTagToggle={handleTagToggle}
            onBack={() => setMobileView("chat")}
            aiEnabled={(selectedConversation.leads as Lead | null)?.ai_enabled ?? true}
            togglingAi={togglingAi}
            onToggleAi={handleToggleAi}
            followupEnabled={selectedConversation.followup_enabled ?? true}
            togglingFollowup={togglingFollowup}
            onToggleFollowup={handleToggleFollowup}
            onLeadUpdate={handleLeadUpdate}
          />
        )}
      </div>

      {/* Desktop: side-by-side panels */}
      <div className="hidden md:flex flex-1 overflow-hidden">
        <ChatList
          conversations={conversations}
          channels={channels}
          activeTab={activeTab}
          selectedConversationId={selectedConversation?.id || null}
          selectedChannelId={selectedChannelId}
          onSelectConversation={handleSelectConversation}
          onMarkRead={handleMarkRead}
          onTabChange={setActiveTab}
          onChannelChange={handleChannelChange}
          listError={listError}
          isRefreshing={isRefreshing}
          onRetry={() => refetchConversations()}
          onSelectMessageResult={handleSelectMessageResult}
          unreadTotal={counts?.unread}
          hasMore={!!hasNextPage && !isRefreshing}
          loadingMore={isFetchingNextPage}
          onLoadMore={handleLoadMore}
        />
        {selectedConversation ? (
          <>
            <ChatView
              conversation={selectedConversation}
              tags={tags}
              aiEnabled={(selectedConversation.leads as Lead | null)?.ai_enabled ?? true}
              togglingAi={togglingAi}
              onToggleAi={handleToggleAi}
              followupEnabled={selectedConversation.followup_enabled ?? true}
              togglingFollowup={togglingFollowup}
              onToggleFollowup={handleToggleFollowup}
              onMarkRead={() => handleMarkRead(selectedConversation.id)}
              siblingConversations={siblingConversations}
              onSelectSibling={handleSelectSibling}
              targetMessageId={pendingScrollMessageId}
              onTargetConsumed={() => setPendingScrollMessageId(null)}
            />
            <ContactDetail
              conversation={selectedConversation}
              tags={tags}
              leadTags={selectedLeadTags}
              onTagToggle={handleTagToggle}
              onLeadUpdate={handleLeadUpdate}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center bg-[#faf9f6]">
            <div className="text-center">
              <svg
                className="w-16 h-16 mx-auto mb-4 text-[#dedbd6]"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
              <p className="text-[#111111] text-[16px] font-medium">
                Selecione uma conversa
              </p>
              <p className="text-[#7b7b78] text-[14px] mt-1">
                {openTotal} conversa{openTotal !== 1 ? "s" : ""} aberta{openTotal !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

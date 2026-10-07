"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView, type SiblingConversationSummary } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import { setActiveConversation } from "@/lib/active-conversation";
import { useMediaQuery } from "@/hooks/use-media-query";
import {
  conversationsListUrl,
  type ConversationsPage,
} from "@/app/api/conversations/list-params";
import { ConversasQueryProvider } from "./query-provider";
import { useConversationList } from "./use-conversation-list";
import type { Conversation, Channel, Tag, Lead } from "@/lib/types";

/**
 * Ponto de corte do painel de venda/orçamento ACOPLADO (coluna ao lado do
 * chat, com a lista de conversas recolhida). Conta: menu 220 + painel "lg"
 * 672 (42rem) + chat mínimo ~360 = 1252 px → 1280 (o `xl` do Tailwind) deixa o
 * chat com ≥ 388 px. Abaixo disso o painel volta a sobrepor o chat, como nas
 * outras telas do CRM.
 */
const QUERY_PAINEL_ACOPLADO = "(min-width: 1280px)";

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
  const [pendingScrollMessageId, setPendingScrollMessageId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("todos");
  const [togglingAi, setTogglingAi] = useState(false);
  const [togglingFollowup, setTogglingFollowup] = useState(false);
  const [mobileView, setMobileView] = useState<"list" | "chat" | "contact">("list");
  const telaLarga = useMediaQuery(QUERY_PAINEL_ACOPLADO);
  // Painel de venda/orçamento aberto como coluna: a lista recolhe para o chat
  // não ficar espremido (o ContactDetail avisa ao abrir/fechar/trocar conversa).
  const [painelAcopladoAberto, setPainelAcopladoAberto] = useState(false);

  // Lista paginada + contadores + seleção + tempo real (ver use-conversation-list.ts).
  const {
    conversations,
    convPending,
    listError,
    isRefreshing,
    refetchConversations,
    hasNextPage,
    isFetchingNextPage,
    loadMore: handleLoadMore,
    counts,
    setSelectedId,
    selectedConversation,
    patchList,
    patchConversation,
    ensureInList,
    fetchConversationById,
    noteMarkedRead,
    setPendingAi,
    setPendingFollowup,
  } = useConversationList({ supabase, channelId: selectedChannelId, activeTab });

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

  // Publica a conversa aberta para o popup de SLA (shell) não interromper a
  // resposta a este lead. Só publica seleção não-nula: o popup já grava o lead
  // antes de navegar pelo "Responder agora", e limpar no mount apagaria isso.
  const selectedConvId = selectedConversation?.id ?? null;
  const selectedLeadId = (selectedConversation?.leads as Lead | undefined | null)?.id ?? null;
  useEffect(() => {
    if (selectedConvId) setActiveConversation({ conversationId: selectedConvId, leadId: selectedLeadId });
  }, [selectedConvId, selectedLeadId]);
  useEffect(() => () => setActiveConversation({ conversationId: null, leadId: null }), []);

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
        ensureInList(conv);
        setSelectedId(conv.id);
      } catch {
        // deep-link é conveniência: falha silenciosa mantém a lista utilizável
      } finally {
        router.replace("/conversas");
      }
    })();
  }, [conversations, convPending, searchParams, router, ensureInList, setSelectedId]);

  function handleSelectConversation(conv: Conversation) {
    // A lista pode entregar um resultado da busca server-side, que não está no
    // cache — sem injetar, a seleção derivada abriria o chat anterior.
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
      ensureInList(conv);
    }
    setSelectedId(conversationId);
    setPendingScrollMessageId(messageId);
    setMobileView("chat");
  }

  async function handleMarkRead(conversationId: string) {
    // Track immediately so any realtime push that fires before the response
    // can be overridden client-side
    noteMarkedRead(conversationId);
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
    setPendingAi(conversationId, next);
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
      setPendingAi(conversationId, null);
      setTogglingAi(false);
    }
  }

  async function handleToggleFollowup() {
    if (!selectedConversation || togglingFollowup) return;
    const conversationId = selectedConversation.id;
    const current = selectedConversation.followup_enabled ?? true;
    const next = !current;
    setTogglingFollowup(true);
    setPendingFollowup(conversationId, next);
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
      setPendingFollowup(conversationId, null);
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
        {/* Recolhida (não desmontada) com o painel acoplado aberto: busca,
            filtro e rolagem da lista estão lá quando o painel fecha. */}
        <div data-slot="coluna-lista" className={painelAcopladoAberto ? "hidden" : "contents"}>
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
              painelAcoplado={telaLarga}
              onPainelAcopladoChange={setPainelAcopladoAberto}
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

"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView, type SiblingConversationSummary } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import { debounce } from "@/lib/debounce";
import {
  mergeConversationRow,
  sortByLastMsgDesc,
  previewFromMessage,
  type ConversationRow,
} from "@/lib/conversations-live";
import { ConversasQueryProvider } from "./query-provider";
import type { Conversation, Channel, Tag, Lead } from "@/lib/types";

// Espera do refetch integral disparado por eventos que o patch local não cobre
// (conversa nova/desconhecida). Rajadas colapsam em 1 invalidação.
const REFETCH_DEBOUNCE_MS = 3_000;

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

  // Lista de conversas via React Query: latest-wins/abort/keep-previous que antes
  // eram coordenados à mão (AbortController + fetchSeqRef + isRefreshing) agora são
  // semântica nativa da queryKey + placeholderData.
  const {
    data: conversations = [],
    isPending: convPending,
    isError: listError,
    isPlaceholderData: isRefreshing,
    refetch: refetchConversations,
  } = useQuery({
    queryKey: ["conversations", selectedChannelId],
    queryFn: async ({ signal }): Promise<Conversation[]> => {
      const url = selectedChannelId
        ? `/api/conversations?channel_id=${selectedChannelId}`
        : "/api/conversations";
      const res = await fetch(url, { signal });
      if (!res.ok) throw new Error(`conversations ${res.status}`);
      const data = await res.json();
      return applyOverrides(Array.isArray(data) ? data : []);
    },
    placeholderData: keepPreviousData,
  });

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

  const { data: leadTagsMap = {}, isPending: leadTagsPending } = useQuery({
    queryKey: ["lead-tags"],
    queryFn: async (): Promise<Record<string, string[]>> => {
      const { data } = await supabase.from("lead_tags").select("lead_id, tag_id");
      const map: Record<string, string[]> = {};
      (data ?? []).forEach((row: { lead_id: string; tag_id: string }) => {
        (map[row.lead_id] ??= []).push(row.tag_id);
      });
      return map;
    },
  });

  // Patch local no cache da lista vigente (substitui os pares espelhados de
  // setConversations/setSelectedConversation — a seleção agora é DERIVADA).
  const patchList = useCallback(
    (updater: (list: Conversation[]) => Conversation[]) => {
      queryClient.setQueryData<Conversation[]>(
        ["conversations", selectedChannelId],
        (old) => updater(old ?? []),
      );
    },
    [queryClient, selectedChannelId],
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

  // Seleção derivada do cache; fallback para o último objeto conhecido cobre o
  // instante em que a conversa sai da lista (paridade com o `updated ?? prev` antigo).
  const lastSelectedRef = useRef<Conversation | null>(null);
  const selectedConversation = useMemo(() => {
    const found = conversations.find((c) => c.id === selectedId) ?? null;
    if (found) lastSelectedRef.current = found;
    return found ?? (selectedId ? lastSelectedRef.current : null);
  }, [conversations, selectedId]);

  // Deep-link: pre-select conversation by lead_id from URL param
  useEffect(() => {
    if (deepLinkApplied.current || conversations.length === 0) return;
    const leadId = searchParams.get("lead_id");
    if (!leadId) return;
    const match = conversations.find((c) => (c.leads as Lead | undefined | null)?.id === leadId);
    if (match) {
      setSelectedId(match.id);
      deepLinkApplied.current = true;
      router.replace("/conversas");
    }
  }, [conversations, searchParams, router]);

  // Realtime SEM refetch integral por evento (corte de Egress): o payload do
  // UPDATE já traz a linha nova de `conversations` — aplicamos o delta no cache
  // e o preview vem do INSERT de `messages`. A invalidação integral (debounced)
  // fica reservada para o que o delta não cobre: conversa nova/desconhecida
  // (precisa dos joins da API).
  useEffect(() => {
    const debouncedInvalidate = debounce(() => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    }, REFETCH_DEBOUNCE_MS);

    const applyRowPatch = (row: ConversationRow) => {
      const overrides = {
        forceUnreadZero: recentlyMarkedRef.current.has(row.id),
        pendingFollowup: recentlyToggledFollowupRef.current.get(row.id),
      };
      patchList((prev) =>
        sortByLastMsgDesc(
          prev.map((c) => (c.id === row.id ? mergeConversationRow(c, row, overrides) : c)),
        ),
      );
    };

    const realtimeChannel = supabase
      .channel("conversations-updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        (payload) => {
          if (payload.eventType === "DELETE") {
            const oldId = (payload.old as { id?: string } | null)?.id;
            if (!oldId) return;
            patchList((prev) => prev.filter((c) => c.id !== oldId));
            return;
          }
          const row = payload.new as ConversationRow;
          // Filtro de canal ativo: eventos de outros canais não pertencem à lista.
          if (selectedChannelId && row.channel_id !== selectedChannelId) return;
          if (payload.eventType === "INSERT") {
            debouncedInvalidate(); // linha crua não tem lead/channel — precisa da API
            return;
          }
          const cached = queryClient.getQueryData<Conversation[]>([
            "conversations",
            selectedChannelId,
          ]);
          if (!cached?.some((c) => c.id === row.id)) {
            debouncedInvalidate(); // conversa fora da lista atual (ex.: fetch anterior falhou)
            return;
          }
          applyRowPatch(row);
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
      .subscribe();

    return () => {
      debouncedInvalidate.cancel();
      supabase.removeChannel(realtimeChannel);
    };
  }, [selectedChannelId, queryClient, supabase, patchList]);

  function handleSelectConversation(conv: Conversation) {
    setSelectedId(conv.id);
    setPendingScrollMessageId(null);
    setMobileView("chat");
  }

  function handleSelectMessageResult(conversationId: string, messageId: string) {
    if (!conversations.some((c) => c.id === conversationId)) return; // fora do escopo
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

  const selectedLeadTags = selectedLead
    ? tags.filter((t) => leadTagsMap[selectedLead.id]?.includes(t.id))
    : [];

  // Sibling conversations: same lead_id as open conversation, different conversation id
  const siblingConversations: SiblingConversationSummary[] = selectedConversation
    ? conversations
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
    if (!selectedLead) return;

    const currentTagIds = leadTagsMap[selectedLead.id] || [];
    const newTagIds = add
      ? [...currentTagIds, tagId]
      : currentTagIds.filter((id) => id !== tagId);

    const res = await fetch(`/api/leads/${selectedLead.id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tagIds: newTagIds }),
    });

    if (res.ok) {
      queryClient.setQueryData<Record<string, string[]>>(["lead-tags"], (prev) => ({
        ...(prev ?? {}),
        [selectedLead.id]: newTagIds,
      }));
    }
  }

  const initialLoading =
    channelsPending || tagsPending || leadTagsPending || (convPending && !isRefreshing);

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
            onSelectSibling={(id) => {
              const sibling = conversations.find((c) => c.id === id);
              if (sibling) handleSelectConversation(sibling);
            }}
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
              onSelectSibling={(id) => {
                const sibling = conversations.find((c) => c.id === id);
                if (sibling) handleSelectConversation(sibling);
              }}
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
                {conversations.length} conversa{conversations.length !== 1 ? "s" : ""} aberta{conversations.length !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

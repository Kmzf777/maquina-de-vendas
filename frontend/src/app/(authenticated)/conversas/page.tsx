"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView, type SiblingConversationSummary } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import type { Conversation, Channel, Tag, Lead } from "@/lib/types";

export default function ConversasPage() {
  const supabase = createClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkApplied = useRef(false);
  // Cancelamento de fetch + guarda de sequência (latest-wins) para a lista de conversas.
  // Sem isso, trocar de filtro rápido fazia respostas fora de ordem sobrescreverem a lista.
  const fetchAbortRef = useRef<AbortController | null>(null);
  const fetchSeqRef = useRef(0);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, string[]>>({});
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<string>("");
  const [activeTab, setActiveTab] = useState("todos");
  const [loading, setLoading] = useState(true);
  // Primeira carga das conversas concluída (mantém o spinner inicial cobrindo a lista).
  const [initialConvDone, setInitialConvDone] = useState(false);
  // Erro ao buscar conversas: mantém a lista anterior e sinaliza, em vez de apagar tudo.
  const [listError, setListError] = useState(false);
  // Indicador sutil enquanto a lista do novo filtro carrega.
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [togglingAi, setTogglingAi] = useState(false);
  const [togglingFollowup, setTogglingFollowup] = useState(false);
  const [mobileView, setMobileView] = useState<"list" | "chat" | "contact">("list");
  // Tracks conversations marked-as-read locally so we can override stale realtime payloads
  // for ~30s. Without this, the Supabase realtime push wins and the badge reappears.
  const recentlyMarkedRef = useRef<Map<string, number>>(new Map());
  // Tracks ai_enabled value for in-flight toggles so realtime doesn't overwrite the optimistic state.
  const recentlyToggledAiRef = useRef<Map<string, boolean>>(new Map());
  // Same protection for followup_enabled toggles.
  const recentlyToggledFollowupRef = useRef<Map<string, boolean>>(new Map());

  const applyRecentlyMarkedOverride = useCallback((list: Conversation[]): Conversation[] => {
    const now = Date.now();
    // Drop entries older than 30s
    for (const [id, ts] of recentlyMarkedRef.current) {
      if (now - ts > 30_000) recentlyMarkedRef.current.delete(id);
    }
    if (recentlyMarkedRef.current.size === 0) return list;
    return list.map((c) =>
      recentlyMarkedRef.current.has(c.id) ? { ...c, unread_count: 0 } : c,
    );
  }, []);

  const fetchConversations = useCallback(async () => {
    // Cancela a requisição anterior em voo e marca esta como a vigente. Sem isso,
    // ao alternar filtros uma resposta antiga (mais lenta) sobrescrevia a lista
    // correta — e um erro virava lista vazia (a "tela em branco" relatada).
    fetchAbortRef.current?.abort();
    const ac = new AbortController();
    fetchAbortRef.current = ac;
    const seq = ++fetchSeqRef.current;
    try {
      const url = selectedChannelId
        ? `/api/conversations?channel_id=${selectedChannelId}`
        : "/api/conversations";
      const res = await fetch(url, { signal: ac.signal });
      if (seq !== fetchSeqRef.current) return; // resposta obsoleta — ignora
      if (!res.ok) {
        // Erro real (401/500): NÃO apaga a lista — mantém o estado anterior e sinaliza.
        setListError(true);
        return;
      }
      const data = await res.json();
      if (seq !== fetchSeqRef.current) return;
      const raw = Array.isArray(data) ? data : [];
      const base = applyRecentlyMarkedOverride(raw);
      // Preserve in-flight toggles so realtime doesn't race against PATCH
      const list = base.map((c) => {
        let out = c;
        const pendingAi = recentlyToggledAiRef.current.get(c.id);
        if (pendingAi !== undefined) out = { ...out, leads: { ...(out.leads as any), ai_enabled: pendingAi } };
        const pendingFollowup = recentlyToggledFollowupRef.current.get(c.id);
        if (pendingFollowup !== undefined) out = { ...out, followup_enabled: pendingFollowup };
        return out;
      });
      setListError(false);
      setConversations(list);
      // Sync selectedConversation when its data changes
      setSelectedConversation((prev: Conversation | null) => {
        if (!prev) return prev;
        const updated = list.find((c: Conversation) => c.id === prev.id);
        return updated ?? prev;
      });
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return; // cancelamento esperado — ignora
      // Falha de rede: mantém a lista anterior e sinaliza, em vez de apagar.
      if (seq === fetchSeqRef.current) setListError(true);
    } finally {
      // Só a requisição vigente controla os flags de UI (evita flicker de respostas obsoletas).
      if (seq === fetchSeqRef.current) {
        setIsRefreshing(false);
        setInitialConvDone(true);
      }
    }
  }, [selectedChannelId, applyRecentlyMarkedOverride]);

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    fetchConversations();
    // Aborta o fetch em voo ao trocar de filtro ou desmontar (evita race/leak).
    return () => fetchAbortRef.current?.abort();
  }, [fetchConversations]);

  // Deep-link: pre-select conversation by lead_id from URL param
  useEffect(() => {
    if (deepLinkApplied.current || loading || conversations.length === 0) return;
    const leadId = searchParams.get("lead_id");
    if (!leadId) return;
    const match = conversations.find((c) => {
      const lead = c.leads as Lead | undefined | null;
      return lead?.id === leadId;
    });
    if (match) {
      setSelectedConversation(match);
      deepLinkApplied.current = true;
      router.replace("/conversas");
    }
  }, [conversations, loading, searchParams, router]);

  // Realtime: re-sort list when any conversation's last_msg_at changes
  useEffect(() => {
    const realtimeChannel = supabase
      .channel("conversations-updates")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        () => {
          fetchConversations();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(realtimeChannel);
    };
  }, [fetchConversations]);

  async function loadData() {
    setLoading(true);
    // Conversas são carregadas pelo effect dedicado (com cancelamento), não aqui —
    // evita o duplo-fetch no mount. Aqui só os dados auxiliares.
    await Promise.all([fetchChannels(), fetchTags(), fetchLeadTags()]);
    setLoading(false);
  }

  async function fetchChannels() {
    try {
      const res = await fetch("/api/channels");
      if (res.ok) {
        const data = await res.json();
        setChannels(Array.isArray(data) ? data : []);
      }
    } catch {
      // ignore
    }
  }

  async function fetchLeadTags() {
    const { data: ltData } = await supabase
      .from("lead_tags")
      .select("lead_id, tag_id");
    if (ltData) {
      const map: Record<string, string[]> = {};
      ltData.forEach((row: { lead_id: string; tag_id: string }) => {
        if (!map[row.lead_id]) map[row.lead_id] = [];
        map[row.lead_id].push(row.tag_id);
      });
      setLeadTagsMap(map);
    }
  }

  async function fetchTags() {
    try {
      const res = await fetch("/api/tags");
      if (res.ok) {
        const data = await res.json();
        setTags(data);
      }
    } catch {
      // ignore
    }
  }

  function handleSelectConversation(conv: Conversation) {
    setSelectedConversation(conv);
    setMobileView("chat");
  }

  async function handleMarkRead(conversationId: string) {
    // Track immediately so any realtime push that fires before the response
    // can be overridden client-side
    recentlyMarkedRef.current.set(conversationId, Date.now());
    // Optimistic local zero
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, unread_count: 0 } : c)),
    );
    setSelectedConversation((prev) =>
      prev && prev.id === conversationId ? { ...prev, unread_count: 0 } : prev,
    );
    try {
      await fetch(`/api/conversations/${conversationId}/mark-read`, { method: "POST" });
    } catch (err) {
      console.warn("[mark-read] failed:", err);
    }
  }

  function handleChannelChange(channelId: string) {
    setSelectedChannelId(channelId);
    setSelectedConversation(null);
    setMobileView("list");
    setIsRefreshing(true); // feedback até a lista do novo filtro chegar
  }

  function handleAgentUpdate(
    conversationId: string,
    patch: { ai_enabled?: boolean; agent_profile_id?: string | null }
  ) {
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, ...patch } : c))
    );
    setSelectedConversation((prev) => {
      if (!prev || prev.id !== conversationId) return prev;
      return { ...prev, ...patch };
    });
  }

  async function handleToggleAi() {
    if (!selectedConversation || togglingAi) return;
    const currentAiEnabled = (selectedConversation.leads as any)?.ai_enabled ?? true;
    const next = !currentAiEnabled;
    setTogglingAi(true);
    recentlyToggledAiRef.current.set(selectedConversation.id, next);
    // Optimistic update — mirrors contact-detail.tsx pattern
    setConversations((prev) =>
      prev.map((c) =>
        c.id === selectedConversation.id
          ? { ...c, leads: { ...(c.leads as any), ai_enabled: next } }
          : c
      )
    );
    setSelectedConversation((prev) =>
      prev && prev.id === selectedConversation.id
        ? { ...prev, leads: { ...(prev.leads as any), ai_enabled: next } }
        : prev
    );
    try {
      const res = await fetch(`/api/conversations/${selectedConversation.id}/agent`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ai_enabled: next }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      // Confirm against server value — protects against silent backend failures
      const data = await res.json();
      const confirmed: boolean = data?.leads?.ai_enabled ?? next;
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConversation.id
            ? { ...c, leads: { ...(c.leads as any), ai_enabled: confirmed } }
            : c
        )
      );
      setSelectedConversation((prev) =>
        prev && prev.id === selectedConversation.id
          ? { ...prev, leads: { ...(prev.leads as any), ai_enabled: confirmed } }
          : prev
      );
    } catch (err) {
      console.warn("[toggle-ai] failed:", err);
      // Roll back optimistic update on failure
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConversation.id
            ? { ...c, leads: { ...(c.leads as any), ai_enabled: !next } }
            : c
        )
      );
      setSelectedConversation((prev) =>
        prev && prev.id === selectedConversation.id
          ? { ...prev, leads: { ...(prev.leads as any), ai_enabled: !next } }
          : prev
      );
    } finally {
      recentlyToggledAiRef.current.delete(selectedConversation.id);
      setTogglingAi(false);
    }
  }

  async function handleToggleFollowup() {
    if (!selectedConversation || togglingFollowup) return;
    const current = selectedConversation.followup_enabled ?? true;
    const next = !current;
    setTogglingFollowup(true);
    recentlyToggledFollowupRef.current.set(selectedConversation.id, next);

    // Optimistic update
    const patch = { followup_enabled: next };
    setConversations((prev) =>
      prev.map((c) => (c.id === selectedConversation.id ? { ...c, ...patch } : c))
    );
    setSelectedConversation((prev) =>
      prev && prev.id === selectedConversation.id ? { ...prev, ...patch } : prev
    );

    try {
      const res = await fetch(
        `/api/conversations/${selectedConversation.id}/followup`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: next }),
          signal: AbortSignal.timeout(10_000),
        }
      );
      if (!res.ok) throw new Error(`status ${res.status}`);
    } catch (err) {
      console.warn("[toggle-followup] failed:", err);
      // Rollback
      const rollback = { followup_enabled: current };
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConversation.id ? { ...c, ...rollback } : c
        )
      );
      setSelectedConversation((prev) =>
        prev && prev.id === selectedConversation.id
          ? { ...prev, ...rollback }
          : prev
      );
    } finally {
      recentlyToggledFollowupRef.current.delete(selectedConversation.id);
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
    const updateConv = (c: Conversation): Conversation =>
      (c.leads as Lead)?.id === leadId
        ? { ...c, leads: { ...(c.leads as Lead), ...patch } }
        : c;
    setConversations(prev => prev.map(updateConv));
    setSelectedConversation(prev => prev ? updateConv(prev) : prev);
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
      setLeadTagsMap((prev) => ({ ...prev, [selectedLead.id]: newTagIds }));
    }
  }

  if (loading || !initialConvDone) {
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
    <div className="flex h-full overflow-hidden bg-[#faf9f6]">

      {/* Mobile: one panel at a time */}
      <div className={`md:hidden flex-1 flex-col h-full ${mobileView === "list" ? "flex" : "hidden"}`}>
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
          onRetry={fetchConversations}
        />
      </div>

      <div className={`md:hidden flex-1 flex-col h-full ${mobileView === "chat" && selectedConversation ? "flex" : "hidden"}`}>
        {selectedConversation && (
          <ChatView
            conversation={selectedConversation}
            tags={tags}
            aiEnabled={(selectedConversation.leads as any)?.ai_enabled ?? true}
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
          />
        )}
      </div>

      <div className={`md:hidden flex-1 flex-col h-full overflow-y-auto ${mobileView === "contact" && selectedConversation ? "flex" : "hidden"}`}>
        {selectedConversation && (
          <ContactDetail
            conversation={selectedConversation}
            tags={tags}
            leadTags={selectedLeadTags}
            onTagToggle={handleTagToggle}
            onBack={() => setMobileView("chat")}
            aiEnabled={(selectedConversation.leads as any)?.ai_enabled ?? true}
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
          onRetry={fetchConversations}
        />
        {selectedConversation ? (
          <>
            <ChatView
              conversation={selectedConversation}
              tags={tags}
              aiEnabled={(selectedConversation.leads as any)?.ai_enabled ?? true}
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

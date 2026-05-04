"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import type { Conversation, Channel, Tag, Lead } from "@/lib/types";

export default function ConversasPage() {
  const supabase = createClient();
  const searchParams = useSearchParams();
  const router = useRouter();
  const deepLinkApplied = useRef(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, string[]>>({});
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<string>("");
  const [activeTab, setActiveTab] = useState("todos");
  const [loading, setLoading] = useState(true);
  const [togglingAi, setTogglingAi] = useState(false);
  const [togglingFollowup, setTogglingFollowup] = useState(false);
  const [mobileView, setMobileView] = useState<"list" | "chat" | "contact">("list");
  // Tracks conversations marked-as-read locally so we can override stale realtime payloads
  // for ~30s. Without this, the Supabase realtime push wins and the badge reappears.
  const recentlyMarkedRef = useRef<Map<string, number>>(new Map());
  // Tracks ai_enabled value for in-flight toggles so realtime doesn't overwrite the optimistic state.
  const recentlyToggledAiRef = useRef<Map<string, boolean>>(new Map());

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
    try {
      const url = selectedChannelId
        ? `/api/conversations?channel_id=${selectedChannelId}`
        : "/api/conversations";
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        const raw = Array.isArray(data) ? data : [];
        const base = applyRecentlyMarkedOverride(raw);
        // Preserve in-flight ai_enabled toggles so realtime doesn't race against PATCH
        const list = base.map((c) => {
          const pending = recentlyToggledAiRef.current.get(c.id);
          if (pending === undefined) return c;
          return { ...c, leads: { ...(c.leads as any), ai_enabled: pending } };
        });
        setConversations(list);
        // Sync selectedConversation when its data changes
        setSelectedConversation((prev: Conversation | null) => {
          if (!prev) return prev;
          const updated = list.find((c: Conversation) => c.id === prev.id);
          return updated ?? prev;
        });
      }
    } catch {
      // ignore
    }
  }, [selectedChannelId, applyRecentlyMarkedOverride]);

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    fetchConversations();
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
    await Promise.all([fetchConversations(), fetchChannels(), fetchTags(), fetchLeadTags()]);
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
      setTogglingFollowup(false);
    }
  }

  const selectedLead = selectedConversation?.leads as Lead | undefined | null;

  const selectedLeadTags = selectedLead
    ? tags.filter((t) => leadTagsMap[selectedLead.id]?.includes(t.id))
    : [];

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

  if (loading) {
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
      <div className={`md:hidden flex-1 flex flex-col h-full ${mobileView === "list" ? "flex" : "hidden"}`}>
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
        />
      </div>

      <div className={`md:hidden flex-1 flex flex-col h-full ${mobileView === "chat" && selectedConversation ? "flex" : "hidden"}`}>
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
            onBack={() => setMobileView("list")}
            onOpenContact={() => setMobileView("contact")}
          />
        )}
      </div>

      <div className={`md:hidden flex-1 flex flex-col h-full overflow-y-auto ${mobileView === "contact" && selectedConversation ? "flex" : "hidden"}`}>
        {selectedConversation && (
          <ContactDetail
            conversation={selectedConversation}
            tags={tags}
            leadTags={selectedLeadTags}
            onTagToggle={handleTagToggle}
            onBack={() => setMobileView("chat")}
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
            />
            <ContactDetail
              conversation={selectedConversation}
              tags={tags}
              leadTags={selectedLeadTags}
              onTagToggle={handleTagToggle}
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

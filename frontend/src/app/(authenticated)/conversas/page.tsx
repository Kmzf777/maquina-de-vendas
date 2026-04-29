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

  const fetchConversations = useCallback(async () => {
    try {
      const url = selectedChannelId
        ? `/api/conversations?channel_id=${selectedChannelId}`
        : "/api/conversations";
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : [];
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
  }, [selectedChannelId]);

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
  }

  function handleChannelChange(channelId: string) {
    setSelectedChannelId(channelId);
    setSelectedConversation(null);
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
    const next = !selectedConversation.ai_enabled;
    setTogglingAi(true);
    // Optimistic update — mirrors contact-detail.tsx pattern
    setConversations((prev) =>
      prev.map((c) =>
        c.id === selectedConversation.id ? { ...c, ai_enabled: next } : c
      )
    );
    setSelectedConversation((prev) =>
      prev && prev.id === selectedConversation.id
        ? { ...prev, ai_enabled: next }
        : prev
    );
    try {
      const res = await fetch(`/api/conversations/${selectedConversation.id}/agent`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ai_enabled: next }),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
    } catch (err) {
      console.warn("[toggle-ai] failed:", err);
      // Roll back optimistic update on failure
      setConversations((prev) =>
        prev.map((c) =>
          c.id === selectedConversation.id ? { ...c, ai_enabled: !next } : c
        )
      );
      setSelectedConversation((prev) =>
        prev && prev.id === selectedConversation.id
          ? { ...prev, ai_enabled: !next }
          : prev
      );
    } finally {
      setTogglingAi(false);
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
      <ChatList
        conversations={conversations}
        channels={channels}
        activeTab={activeTab}
        selectedConversationId={selectedConversation?.id || null}
        selectedChannelId={selectedChannelId}
        onSelectConversation={handleSelectConversation}
        onTabChange={setActiveTab}
        onChannelChange={handleChannelChange}
      />

      {selectedConversation ? (
        <>
          <ChatView
            conversation={selectedConversation}
            tags={tags}
            aiEnabled={selectedConversation.ai_enabled}
            togglingAi={togglingAi}
            onToggleAi={handleToggleAi}
          />
          <ContactDetail
            conversation={selectedConversation}
            tags={tags}
            leadTags={selectedLeadTags}
            onTagToggle={handleTagToggle}
            onAgentUpdate={handleAgentUpdate}
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
  );
}

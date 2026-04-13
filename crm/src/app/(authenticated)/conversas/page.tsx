"use client";

import { useState, useEffect, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { ChatList } from "@/components/conversas/chat-list";
import { ChatView } from "@/components/conversas/chat-view";
import { ContactDetail } from "@/components/conversas/contact-detail";
import type { Conversation, Channel, Tag, Lead } from "@/lib/types";

export default function ConversasPage() {
  const supabase = createClient();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [leadTagsMap, setLeadTagsMap] = useState<Record<string, string[]>>({});
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<string>("");
  const [activeTab, setActiveTab] = useState("todos");
  const [loading, setLoading] = useState(true);

  const fetchConversations = useCallback(async () => {
    try {
      const url = selectedChannelId
        ? `/api/conversations?channel_id=${selectedChannelId}`
        : "/api/conversations";
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setConversations(Array.isArray(data) ? data : []);
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
      <div className="flex items-center justify-center h-full bg-[#f6f7ed]">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-[#c8cc8e] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-[#5f6368] text-sm">Carregando conversas...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full bg-[#f6f7ed]">
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
          />
          <ContactDetail
            conversation={selectedConversation}
            tags={tags}
            leadTags={selectedLeadTags}
            onTagToggle={handleTagToggle}
          />
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center bg-[#f6f7ed]">
          <div className="text-center">
            <svg
              className="w-16 h-16 mx-auto mb-4 text-[#c8cc8e]"
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
            <p className="text-[#1f1f1f] text-lg font-medium">
              Selecione uma conversa
            </p>
            <p className="text-[#9ca3af] text-sm mt-1">
              Escolha um contato para ver as mensagens
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

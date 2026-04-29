"use client";

import { useState } from "react";
import { CONVERSATION_TABS, AGENT_STAGES } from "@/lib/constants";
import type { Conversation, Channel } from "@/lib/types";
import { formatRelativeTime } from "@/lib/datetime";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";

interface ChatListProps {
  conversations: Conversation[];
  channels: Channel[];
  activeTab: string;
  selectedConversationId: string | null;
  selectedChannelId: string;
  onSelectConversation: (conv: Conversation) => void;
  onTabChange: (tab: string) => void;
  onChannelChange: (channelId: string) => void;
}

function getStageColor(stage: string | undefined): string {
  const avatarColorMap: Record<string, string> = {
    secretaria: "bg-[#8a8a80]",
    atacado: "bg-[#5b8aad]",
    private_label: "bg-[#8b6bab]",
    exportacao: "bg-[#5aad65]",
    consumo: "bg-[#ad9c4a]",
  };
  if (!stage) return "bg-[#8a8a80]";
  return avatarColorMap[stage] || "bg-[#8a8a80]";
}

function getStagePillColor(stage: string | undefined): string {
  const pillColorMap: Record<string, string> = {
    secretaria: "bg-[#8a8a80]/10 text-[#8a8a80]",
    atacado: "bg-[#5b8aad]/10 text-[#5b8aad]",
    private_label: "bg-[#8b6bab]/10 text-[#8b6bab]",
    exportacao: "bg-[#5aad65]/10 text-[#5aad65]",
    consumo: "bg-[#ad9c4a]/10 text-[#ad9c4a]",
  };
  if (!stage) return "bg-[#dedbd6] text-[#7b7b78]";
  return pillColorMap[stage] || "bg-[#dedbd6] text-[#7b7b78]";
}

function getInitial(name: string | null | undefined): string {
  if (!name) return "?";
  return name.charAt(0).toUpperCase();
}

export function ChatList({
  conversations: initialConversations,
  channels,
  activeTab,
  selectedConversationId,
  selectedChannelId,
  onSelectConversation,
  onTabChange,
  onChannelChange,
}: ChatListProps) {
  const [search, setSearch] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>(initialConversations);

  // Sync if parent passes new conversations (e.g. after polling refresh)
  // We use a ref-less approach: only update if the incoming array reference changed
  const [prevInitial, setPrevInitial] = useState(initialConversations);
  if (prevInitial !== initialConversations) {
    setPrevInitial(initialConversations);
    setConversations(initialConversations);
  }

  const handleSelectConversation = (conv: Conversation) => {
    onSelectConversation(conv);
    if ((conv.unread_count ?? 0) > 0) {
      fetch(`/api/conversations/${conv.id}/mark-read`, { method: "POST" })
        .then((res) => {
          if (res.ok) {
            setConversations((prev) =>
              prev.map((c) => (c.id === conv.id ? { ...c, unread_count: 0 } : c)),
            );
          }
        })
        .catch((err) => console.warn("[mark-read] failed:", err));
    }
  };

  const filteredConversations = conversations
    .filter((conv) => {
      if (activeTab === "todos") return true;
      if (activeTab === "pessoal") return !conv.leads;
      return conv.leads?.stage === activeTab;
    })
    .filter((conv) => {
      if (!search) return true;
      const q = search.toLowerCase();
      const name = conv.leads?.name || conv.leads?.phone || "";
      const phone = conv.leads?.phone || "";
      return name.toLowerCase().includes(q) || phone.includes(q);
    });

  return (
    <div className="w-[320px] bg-[#f0ede8] border-r border-[#dedbd6] flex flex-col h-full">
      {/* Channel filter */}
      <div className="px-3 pt-3 pb-2">
        <select
          value={selectedChannelId}
          onChange={(e) => onChannelChange(e.target.value)}
          className="bg-white border border-[#dedbd6] rounded-[6px] text-[13px] px-3 py-2 w-full text-[#111111] focus:border-[#111111] focus:outline-none"
        >
          <option value="">Todos os canais</option>
          {channels.map((ch) => (
            <option key={ch.id} value={ch.id}>
              {ch.name} — {ch.phone}
            </option>
          ))}
        </select>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar conversa..."
          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none"
        />
      </div>

      {/* Tabs */}
      <div className="px-3 pb-2 flex gap-1 flex-wrap">
        {CONVERSATION_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={`px-2.5 py-1 rounded-[4px] text-[12px] transition-colors ${
              activeTab === tab.key
                ? "bg-[#111111] text-white"
                : "text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-y-auto py-1">
        {filteredConversations.length === 0 && (
          <p className="text-[#7b7b78] text-sm text-center py-8">
            Nenhuma conversa encontrada.
          </p>
        )}
        {filteredConversations.map((conv) => {
          const lead = conv.leads;
          const channel = conv.channels;
          const displayName = lead?.name || lead?.phone || "Desconhecido";
          const stage = lead?.stage;
          const isActive = selectedConversationId === conv.id;
          const unreadCount = conv.unread_count ?? 0;

          return (
            <button
              key={conv.id}
              onClick={() => handleSelectConversation(conv)}
              className={`w-full flex items-start gap-3 px-3 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-[#ff5600] focus-visible:ring-offset-1 focus-visible:outline-none ${
                isActive
                  ? "border-l-[3px] border-l-[#ff5600] bg-[#faf9f6] rounded-r-[6px] mx-2 cursor-pointer"
                  : "hover:bg-[#faf9f6] rounded-[6px] mx-2 cursor-pointer border-l-[3px] border-l-transparent"
              }`}
              style={{ width: "calc(100% - 16px)" }}
            >
              {/* Avatar */}
              <div
                className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-medium flex-shrink-0 mt-0.5 ${getStageColor(stage)}`}
              >
                {getInitial(displayName)}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                {/* L1 — Lead name + unread badge */}
                <div className="flex items-center gap-1">
                  <span
                    className={`text-sm truncate ${
                      unreadCount > 0 ? "font-bold text-[#111111]" : "font-semibold text-[#111111]"
                    }`}
                  >
                    {displayName}
                  </span>
                  {unreadCount > 0 && (
                    <span
                      className="ml-auto inline-flex min-w-[20px] items-center justify-center rounded-full bg-[#ff5600] px-1.5 py-0.5 text-[10px] font-semibold text-white animate-pulse flex-shrink-0"
                      aria-label={`${unreadCount} mensagens não lidas`}
                    >
                      {unreadCount > 9 ? "9+" : unreadCount}
                    </span>
                  )}
                </div>

                {/* L2 — Last message preview */}
                {conv.last_message_text && (
                  <p className="text-sm truncate text-[#7b7b78] mt-0.5">
                    {conv.last_message_text}
                  </p>
                )}

                {/* L3 — Meta row: timestamp · stage · window indicator */}
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  <span className="text-xs text-[#7b7b78]">
                    {formatRelativeTime(conv.last_msg_at)}
                  </span>
                  {stage && (
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-[4px] flex-shrink-0 font-medium ${getStagePillColor(stage)}`}
                    >
                      {stage}
                    </span>
                  )}
                  <WhatsappWindowIndicator
                    expiresAt={conv.whatsapp_window_expires_at}
                    variant="compact"
                  />
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

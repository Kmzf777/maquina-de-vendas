"use client";

import { useState } from "react";
import { CONVERSATION_TABS, AGENT_STAGES } from "@/lib/constants";
import type { Conversation, Channel } from "@/lib/types";

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

function getInitial(name: string | null | undefined): string {
  if (!name) return "?";
  return name.charAt(0).toUpperCase();
}

function formatTime(ts: string | null): string {
  if (!ts) return "";
  const date = new Date(ts);
  const now = new Date();
  const isToday =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear();

  if (isToday) {
    return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

export function ChatList({
  conversations,
  channels,
  activeTab,
  selectedConversationId,
  selectedChannelId,
  onSelectConversation,
  onTabChange,
  onChannelChange,
}: ChatListProps) {
  const [search, setSearch] = useState("");

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
    <div className="w-[320px] bg-white border-r border-[#e5e5dc] flex flex-col h-full">
      {/* Channel filter */}
      <div className="px-3 pt-3 pb-2">
        <select
          value={selectedChannelId}
          onChange={(e) => onChannelChange(e.target.value)}
          className="bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2 w-full outline-none focus:ring-1 focus:ring-[#c8cc8e]"
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
          className="input-field w-full text-[13px] rounded-xl px-4 py-2"
        />
      </div>

      {/* Tabs */}
      <div className="px-3 pb-2 flex gap-1 flex-wrap">
        {CONVERSATION_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-[#1f1f1f] text-white"
                : "text-[#5f6368] hover:text-[#1f1f1f] hover:bg-[#f6f7ed]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-y-auto">
        {filteredConversations.length === 0 && (
          <p className="text-[#9ca3af] text-sm text-center py-8">
            Nenhuma conversa encontrada.
          </p>
        )}
        {filteredConversations.map((conv) => {
          const lead = conv.leads;
          const channel = conv.channels;
          const displayName = lead?.name || lead?.phone || "Desconhecido";
          const stage = lead?.stage;
          const isMetaCloud = channel?.provider === "meta_cloud";

          return (
            <button
              key={conv.id}
              onClick={() => onSelectConversation(conv)}
              className={`w-full flex items-center gap-3 px-3 py-3 text-left transition-colors ${
                selectedConversationId === conv.id
                  ? "bg-[#f6f7ed]"
                  : "hover:bg-[#f6f7ed]/60"
              }`}
            >
              {/* Avatar */}
              <div
                className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-medium flex-shrink-0 ${getStageColor(stage)}`}
              >
                {getInitial(displayName)}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-[13px] text-[#1f1f1f] truncate font-semibold">
                    {displayName}
                  </span>
                  <span className="text-[11px] text-[#9ca3af] flex-shrink-0">
                    {formatTime(conv.last_msg_at)}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  {channel && (
                    <span
                      className={`text-[11px] px-2 py-0.5 rounded-full flex-shrink-0 font-medium ${
                        isMetaCloud
                          ? "bg-[#c8cc8e] text-[#1f1f1f]"
                          : "bg-[#93c5fd] text-[#1e3a5f]"
                      }`}
                    >
                      {channel.name}
                    </span>
                  )}
                  <span className="text-[12px] text-[#9ca3af] truncate">
                    {lead?.phone || ""}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

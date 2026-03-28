"use client";

import { useState } from "react";
import { CONVERSATION_TABS, AGENT_STAGES } from "@/lib/constants";
import type { EvolutionChat, Lead } from "@/lib/types";

interface ChatListProps {
  chats: EvolutionChat[];
  leads: Lead[];
  activeTab: string;
  selectedPhone: string | null;
  onSelectChat: (phone: string, pushName: string | null) => void;
  onTabChange: (tab: string) => void;
}

function extractPhone(remoteJid: string): string {
  return remoteJid.replace("@s.whatsapp.net", "").replace("@g.us", "");
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

function getInitial(name: string | null): string {
  if (!name) return "?";
  return name.charAt(0).toUpperCase();
}

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
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
  chats,
  leads,
  activeTab,
  selectedPhone,
  onSelectChat,
  onTabChange,
}: ChatListProps) {
  const [search, setSearch] = useState("");

  const leadsMap = new Map(leads.map((l) => [l.phone, l]));

  const enrichedChats = chats
    .filter((c) => c.remoteJid.endsWith("@s.whatsapp.net"))
    .map((chat) => {
      const phone = extractPhone(chat.remoteJid);
      const lead = leadsMap.get(phone);
      const displayName = lead?.name || chat.pushName || phone;
      const stage = lead?.stage || null;
      return { ...chat, phone, lead, displayName, stage };
    });

  const filteredChats = enrichedChats
    .filter((chat) => {
      if (activeTab === "todos") return true;
      if (activeTab === "pessoal") return !chat.lead;
      return chat.stage === activeTab;
    })
    .filter((chat) => {
      if (!search) return true;
      const q = search.toLowerCase();
      return (
        chat.displayName.toLowerCase().includes(q) ||
        chat.phone.includes(q)
      );
    })
    .sort((a, b) => {
      const tA = a.lastMessage?.timestamp || 0;
      const tB = b.lastMessage?.timestamp || 0;
      return tB - tA;
    });

  return (
    <div className="w-[320px] bg-white border-r border-[#e5e5dc] flex flex-col h-full">
      {/* Search */}
      <div className="p-3">
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
        {filteredChats.length === 0 && (
          <p className="text-[#9ca3af] text-sm text-center py-8">
            Nenhuma conversa encontrada.
          </p>
        )}
        {filteredChats.map((chat) => (
          <button
            key={chat.remoteJid}
            onClick={() => onSelectChat(chat.phone, chat.pushName)}
            className={`w-full flex items-center gap-3 px-3 py-3 text-left transition-colors ${
              selectedPhone === chat.phone
                ? "bg-[#f6f7ed]"
                : "hover:bg-[#f6f7ed]/60"
            }`}
          >
            {/* Avatar */}
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-sm font-medium flex-shrink-0 ${getStageColor(chat.stage || undefined)}`}
            >
              {getInitial(chat.displayName)}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <span className="text-[13px] text-[#1f1f1f] truncate font-semibold">
                  {chat.displayName}
                </span>
                {chat.lastMessage && (
                  <span className="text-[11px] text-[#9ca3af] flex-shrink-0 ml-2">
                    {formatTime(chat.lastMessage.timestamp)}
                  </span>
                )}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-[#9ca3af] truncate">
                  {chat.lastMessage?.content || ""}
                </span>
                {chat.unreadCount > 0 && (
                  <span className="bg-[#1f1f1f] text-white text-[11px] rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0 ml-2">
                    {chat.unreadCount}
                  </span>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

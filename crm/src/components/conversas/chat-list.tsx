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
  const found = AGENT_STAGES.find((s) => s.key === stage);
  if (!found) return "bg-gray-600";
  const colorMap: Record<string, string> = {
    "bg-gray-100": "bg-gray-600",
    "bg-blue-100": "bg-blue-600",
    "bg-purple-100": "bg-purple-600",
    "bg-green-100": "bg-green-600",
    "bg-yellow-100": "bg-yellow-600",
  };
  return colorMap[found.color] || "bg-gray-600";
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
    <div className="w-80 bg-gray-900 border-r border-gray-800 flex flex-col h-full">
      {/* Search */}
      <div className="p-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar conversa..."
          className="w-full bg-gray-800 text-white text-sm rounded-full px-4 py-2 placeholder-gray-500 outline-none focus:ring-1 focus:ring-violet-500"
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
                ? "bg-violet-600 text-white"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-y-auto">
        {filteredChats.length === 0 && (
          <p className="text-gray-500 text-sm text-center py-8">
            Nenhuma conversa encontrada.
          </p>
        )}
        {filteredChats.map((chat) => (
          <button
            key={chat.remoteJid}
            onClick={() => onSelectChat(chat.phone, chat.pushName)}
            className={`w-full flex items-center gap-3 px-3 py-3 text-left transition-colors ${
              selectedPhone === chat.phone
                ? "bg-gray-800"
                : "hover:bg-gray-800/50"
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
                <span className="text-sm text-white truncate font-medium">
                  {chat.displayName}
                </span>
                {chat.lastMessage && (
                  <span className="text-xs text-gray-500 flex-shrink-0 ml-2">
                    {formatTime(chat.lastMessage.timestamp)}
                  </span>
                )}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400 truncate">
                  {chat.lastMessage?.content || ""}
                </span>
                {chat.unreadCount > 0 && (
                  <span className="bg-violet-600 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0 ml-2">
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

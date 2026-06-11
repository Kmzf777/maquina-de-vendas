"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { CONVERSATION_TABS, AGENT_STAGES, UNREAD_TAB_KEY } from "@/lib/constants";
import type { Conversation, Channel } from "@/lib/types";
import { formatRelativeTime } from "@/lib/datetime";
import { getWindowStatus } from "@/lib/window-status";
import { businessMinutesElapsed } from "@/lib/business-hours";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
import { Badge } from "@/components/ui/badge";

interface ChatListProps {
  conversations: Conversation[];
  channels: Channel[];
  activeTab: string;
  selectedConversationId: string | null;
  selectedChannelId: string;
  onSelectConversation: (conv: Conversation) => void;
  onMarkRead?: (conversationId: string) => void;
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

function getChannelBadge(channelName: string | undefined): { label: string; color: string } | null {
  if (!channelName) return null;
  const upper = channelName.toUpperCase();
  if (upper === "NUMERO VALERIA") return { label: "Valéria", color: "#5aad65" };
  if (upper === "NUMERO ARTHUR") return { label: "Arthur", color: "#5b8aad" };
  if (upper === "NUMERO JOAO" || upper === "NUMERO JOÃO") return { label: "João", color: "#ff5600" };
  return null;
}

function getWindowBgClass(lastCustomerMsgAt: string | null | undefined, provider: string | null | undefined): string {
  const status = getWindowStatus(lastCustomerMsgAt ?? null, provider ?? null);
  if (status === "closed") return "bg-[#fdf2ec]";
  if (status === "expiring") return "bg-[#fff8f5]";
  return "";
}

function computeExpiresAt(lastCustomerMsgAt: string | null | undefined, provider: string | null | undefined): string | null {
  if (provider !== "meta_cloud" || !lastCustomerMsgAt) return null;
  return new Date(new Date(lastCustomerMsgAt).getTime() + 24 * 60 * 60 * 1000).toISOString();
}

/**
 * Retorna true se a conversa está em atraso de SLA (canal humano, sem resposta
 * do vendedor há mais de 20 minutos comerciais).
 */
function isSlaBreached(conv: Conversation): boolean {
  const channel = conv.channels;
  if (channel?.mode !== "human") return false;
  const lastCustomer = conv.leads?.last_customer_message_at;
  if (!lastCustomer) return false;
  const lastSeller = conv.last_seller_response_at;
  if (lastSeller && lastSeller >= lastCustomer) return false;
  return businessMinutesElapsed(new Date(lastCustomer)) > 20;
}

export function ChatList({
  conversations,
  channels,
  activeTab,
  selectedConversationId,
  selectedChannelId,
  onSelectConversation,
  onMarkRead,
  onTabChange,
  onChannelChange,
}: ChatListProps) {
  const [search, setSearch] = useState("");

  // Ticker de 1 minuto para reavaliação do SLA em tempo real
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const unreadTotal = conversations.filter((c) => (c.unread_count ?? 0) > 0).length;

  const tabsScrollRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateScrollButtons = useCallback(() => {
    const el = tabsScrollRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 1);
    setCanScrollRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 1);
  }, []);

  useEffect(() => {
    const el = tabsScrollRef.current;
    if (!el) return;
    const raf = requestAnimationFrame(updateScrollButtons);
    el.addEventListener("scroll", updateScrollButtons);
    window.addEventListener("resize", updateScrollButtons);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("scroll", updateScrollButtons);
      window.removeEventListener("resize", updateScrollButtons);
    };
  }, [updateScrollButtons]);

  const handleSelectConversation = (conv: Conversation) => {
    onSelectConversation(conv);
  };

  const filteredConversations = conversations
    .filter((conv) => {
      if (activeTab === UNREAD_TAB_KEY) return (conv.unread_count ?? 0) > 0;
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
    <div className="w-full md:w-[320px] bg-[#f0ede8] border-r border-[#dedbd6] flex flex-col h-full">
      {/* Channel filter */}
      {channels.length > 1 && (
        <div className="px-3 pt-3 pb-2">
          <div className="relative">
            <select
              value={selectedChannelId}
              onChange={(e) => onChannelChange(e.target.value)}
              className="w-full appearance-none bg-white border border-[#dedbd6] rounded-[6px] text-[13px] px-3 py-2.5 pr-8 text-[#111111] focus:border-[#111111] focus:outline-none cursor-pointer"
            >
              <option value="">Todos os canais</option>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.id}>
                  {ch.name} — {ch.phone}
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#7b7b78]">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </div>
          </div>
        </div>
      )}

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#7b7b78] pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar conversa..."
            className="w-full bg-white border border-[#dedbd6] rounded-[6px] pl-9 pr-3 py-2.5 text-[13px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none"
          />
        </div>
      </div>

      {/* Tabs — horizontal carousel */}
      <div className="relative pb-2">
        {/* Seta esquerda — desktop only */}
        <button
          type="button"
          onClick={() => tabsScrollRef.current?.scrollBy({ left: -120, behavior: "smooth" })}
          aria-label="Rolar tabs para esquerda"
          className={`hidden md:flex absolute left-0 top-1/2 -translate-y-1/2 z-10 w-6 h-6 items-center justify-center bg-[#f0ede8] text-[#7b7b78] hover:text-[#111111] transition-opacity ${
            canScrollLeft ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>

        <div
          ref={tabsScrollRef}
          className="overflow-x-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none] md:px-7"
        >
          <div className="flex gap-1 px-3 w-max">
            {/* Aba especial: Não lidas */}
            <button
              onClick={() => onTabChange(UNREAD_TAB_KEY)}
              className={`px-3 py-1.5 rounded-[4px] text-[12px] transition-colors whitespace-nowrap flex-shrink-0 flex items-center gap-1.5 ${
                activeTab === UNREAD_TAB_KEY
                  ? "bg-[#111111] text-white"
                  : "text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30"
              }`}
            >
              Não lidas
              {unreadTotal > 0 && (
                <span
                  aria-label={`${unreadTotal} conversas não lidas`}
                  className="inline-flex min-w-[16px] items-center justify-center rounded-full bg-[#ff5600] px-1 text-[10px] font-semibold text-white leading-none"
                >
                  {unreadTotal > 9 ? "9+" : unreadTotal}
                </span>
              )}
            </button>
            {CONVERSATION_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => onTabChange(tab.key)}
                className={`px-3 py-1.5 rounded-[4px] text-[12px] transition-colors whitespace-nowrap flex-shrink-0 ${
                  activeTab === tab.key
                    ? "bg-[#111111] text-white"
                    : "text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/30"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Seta direita — desktop only */}
        <button
          type="button"
          onClick={() => tabsScrollRef.current?.scrollBy({ left: 120, behavior: "smooth" })}
          aria-label="Rolar tabs para direita"
          className={`hidden md:flex absolute right-0 top-1/2 -translate-y-1/2 z-10 w-6 h-6 items-center justify-center bg-[#f0ede8] text-[#7b7b78] hover:text-[#111111] transition-opacity ${
            canScrollRight ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </button>
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
          const provider = channel?.provider;
          const lastCustomerMsgAt = lead?.last_customer_message_at;
          const windowBg = getWindowBgClass(lastCustomerMsgAt, provider);
          const windowExpiresAt = computeExpiresAt(lastCustomerMsgAt, provider);
          const breached = isSlaBreached(conv);

          return (
            <button
              key={conv.id}
              onClick={() => handleSelectConversation(conv)}
              className={`w-full flex items-start gap-3 px-3 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:ring-[#ff5600] focus-visible:ring-offset-1 focus-visible:outline-none ${
                isActive
                  ? "border-l-[3px] border-l-[#ff5600] bg-[#faf9f6] rounded-r-[6px] mx-2 cursor-pointer"
                  : breached
                  ? "border-l-[3px] border-l-[#c2410c] bg-[#fdf6ee] hover:bg-[#faeee0] rounded-[6px] mx-2 cursor-pointer"
                  : `hover:bg-[#faf9f6] rounded-[6px] mx-2 cursor-pointer border-l-[3px] border-l-transparent ${windowBg}`
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

                {/* L3 — Meta row: timestamp · funnel badge · window indicator */}
                <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <span className="text-xs text-[#7b7b78]">
                    {formatRelativeTime(conv.last_msg_at)}
                  </span>
                  {channels.length > 1 && (() => {
                    const badge = getChannelBadge(conv.channels?.name);
                    if (!badge) return null;
                    return (
                      <span
                        className="inline-flex items-center gap-0.5 rounded-[3px] px-1.5 py-px text-[10px] font-semibold leading-none tracking-wide flex-shrink-0"
                        style={{ backgroundColor: `${badge.color}15`, color: badge.color }}
                      >
                        {badge.label}
                      </span>
                    );
                  })()}
                  {breached && (
                    <span className="inline-flex items-center gap-0.5 rounded-[3px] bg-[#c2410c]/10 px-1.5 py-px text-[10px] font-semibold text-[#c2410c] leading-none tracking-wide uppercase flex-shrink-0">
                      <svg className="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                      </svg>
                      Atraso
                    </span>
                  )}
                  {conv.deal_stage_label && (
                    <Badge
                      variant="outline"
                      className="h-[18px] px-1.5 text-[10px] font-normal border-[#dedbd6] text-[#7b7b78] gap-1"
                    >
                      <span
                        className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: conv.deal_stage_dot_color ?? "#9ca3af" }}
                      />
                      {conv.deal_stage_label}
                    </Badge>
                  )}
                  {conv.deal_pipeline_name && (
                    <span className="text-[10px] text-[#9b9b98] truncate max-w-[100px]">
                      {conv.deal_pipeline_name}
                    </span>
                  )}
                  <WhatsappWindowIndicator
                    expiresAt={windowExpiresAt}
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

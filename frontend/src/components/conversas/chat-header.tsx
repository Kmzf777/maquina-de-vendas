"use client";

import type { Conversation, Tag } from "@/lib/types";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";

interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
  onBack?: () => void;
  onOpenContact?: () => void;
}

function getStageColor(stage: string | undefined): string {
  const map: Record<string, string> = {
    secretaria: "#8a8a80",
    atacado: "#5b8aad",
    private_label: "#8b6bab",
    exportacao: "#5aad65",
    consumo: "#ad9c4a",
  };
  return map[stage ?? ""] ?? "#8a8a80";
}

export function ChatHeader({
  conversation,
  tags,
  aiEnabled,
  togglingAi,
  onToggleAi,
  followupEnabled,
  togglingFollowup,
  onToggleFollowup,
  onBack,
  onOpenContact,
}: ChatHeaderProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarColor = getStageColor(lead?.stage);

  const tagIdsRaw = (lead as unknown as Record<string, unknown>)?.tag_ids;
  const tagIds = Array.isArray(tagIdsRaw) ? (tagIdsRaw as string[]) : [];
  const leadTags = tags.filter((t) => tagIds.includes(t.id));

  return (
    <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3 flex-shrink-0 overflow-x-auto [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
      {/* Mobile back button */}
      {onBack && (
        <button
          onClick={onBack}
          className="md:hidden flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-[4px] text-[#313130] hover:bg-[#dedbd6]/60 transition-colors"
          aria-label="Voltar"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
      )}

      {/* Avatar */}
      <div
        className={`w-9 h-9 rounded-full flex items-center justify-center text-white font-medium text-sm flex-shrink-0${onOpenContact ? " cursor-pointer" : ""}`}
        style={{ backgroundColor: avatarColor }}
        onClick={onOpenContact}
      >
        {initial}
      </div>

      {/* Name + phone */}
      <div
        className={`flex-1 min-w-0${onOpenContact ? " cursor-pointer" : ""}`}
        onClick={onOpenContact}
      >
        <h2 className="text-[#111111] font-medium text-[14px] truncate">
          {displayName}
        </h2>
        <p className="text-[#7b7b78] text-[12px]">{lead?.phone || ""}</p>
      </div>

      {/* Tags */}
      {leadTags.length > 0 && (
        <div className="flex gap-1 flex-shrink-0">
          {leadTags.map((tag) => (
            <span
              key={tag.id}
              className="px-2 py-0.5 rounded-[4px] text-[11px] text-white"
              style={{ backgroundColor: tag.color }}
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}

      {/* Channel badge */}
      {channel && (
        <span className="text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78] flex-shrink-0">
          {channel.name}
        </span>
      )}

      {/* WhatsApp 24h window indicator */}
      <WhatsappWindowIndicator
        expiresAt={conversation.whatsapp_window_expires_at ?? null}
        variant="header"
        className="flex-shrink-0"
      />

      {/* Valéria IA toggle */}
      <button
        type="button"
        onClick={() => onToggleAi()}
        disabled={togglingAi}
        className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1 text-xs font-medium transition-colors flex-shrink-0 ${
          aiEnabled
            ? "bg-[#ff5600] text-white hover:bg-[#e64e00]"
            : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
        } ${togglingAi ? "opacity-60 cursor-not-allowed" : ""}`}
        aria-pressed={aiEnabled}
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"
          }`}
          aria-hidden
        />
        Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
      </button>

      {/* Follow-up toggle */}
      <button
        type="button"
        onClick={() => onToggleFollowup()}
        disabled={togglingFollowup}
        className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1 text-xs font-medium transition-colors flex-shrink-0 ${
          followupEnabled
            ? "bg-[#1e6ee8] text-white hover:bg-[#1a5ec8]"
            : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
        } ${togglingFollowup ? "opacity-60 cursor-not-allowed" : ""}`}
        aria-pressed={followupEnabled}
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            followupEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"
          }`}
          aria-hidden
        />
        Follow-up · {followupEnabled ? "Ativo" : "Pausado"}
      </button>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import type { Conversation, Tag } from "@/lib/types";
import {
  getWindowStatus,
  windowExpiresInMs,
  formatTimeRemaining,
} from "@/lib/window-status";

interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
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

export function ChatHeader({ conversation, tags }: ChatHeaderProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;
  const [, setTick] = useState(0);

  const provider = channel?.provider ?? null;
  const lastCustomerMsgAt = lead?.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const timeRemainingMs =
    (windowStatus === "open" || windowStatus === "expiring") && lastCustomerMsgAt
      ? windowExpiresInMs(lastCustomerMsgAt)
      : 0;

  // Refresh countdown every 60s while window is open or expiring
  useEffect(() => {
    if (windowStatus === "closed" || windowStatus === "n/a") return;
    const interval = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(interval);
  }, [windowStatus]);

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarColor = getStageColor(lead?.stage);

  const tagIdsRaw = (lead as unknown as Record<string, unknown>)?.tag_ids;
  const tagIds = Array.isArray(tagIdsRaw) ? (tagIdsRaw as string[]) : [];
  const leadTags = tags.filter((t) => tagIds.includes(t.id));

  return (
    <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3 flex-shrink-0">
      {/* Avatar */}
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-white font-medium text-sm flex-shrink-0"
        style={{ backgroundColor: avatarColor }}
      >
        {initial}
      </div>

      {/* Name + phone */}
      <div className="flex-1 min-w-0">
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

      {/* 24h window countdown — only for meta_cloud */}
      {windowStatus === "open" && (
        <span className="text-[12px] text-green-700 flex-shrink-0 flex items-center gap-1">
          ⏳ Janela · {formatTimeRemaining(timeRemainingMs)}
        </span>
      )}
      {windowStatus === "expiring" && (
        <span className="text-[12px] text-amber-700 flex-shrink-0 flex items-center gap-1 animate-pulse">
          ⏱ Expira em {formatTimeRemaining(timeRemainingMs)}
        </span>
      )}
      {windowStatus === "closed" && (
        <span className="text-[12px] text-red-700 flex-shrink-0">
          🔒 Janela fechada
        </span>
      )}
    </div>
  );
}

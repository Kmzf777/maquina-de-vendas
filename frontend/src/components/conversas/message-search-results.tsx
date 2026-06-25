"use client";

import type { MessageSearchResult } from "@/lib/types";
import { highlightSegments } from "@/lib/message-search";
import { formatRelativeTime } from "@/lib/datetime";

interface MessageSearchResultsProps {
  query: string;
  results: MessageSearchResult[];
  loading: boolean;
  onSelect: (conversationId: string, messageId: string) => void;
}

function getInitial(name: string | null | undefined): string {
  if (!name) return "?";
  return name.charAt(0).toUpperCase();
}

export function MessageSearchResults({ query, results, loading, onSelect }: MessageSearchResultsProps) {
  if (loading) {
    return (
      <div className="px-3 py-3 flex items-center gap-2 text-[11px] text-[#7b7b78]">
        <span className="w-3 h-3 border-2 border-[#dedbd6] border-t-[#111111] rounded-full animate-spin flex-shrink-0" />
        Buscando mensagens...
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <p className="text-[#7b7b78] text-xs px-3 py-3">Nenhuma mensagem encontrada.</p>
    );
  }

  return (
    <div>
      {results.map((r) => {
        const displayName = r.lead_name || r.lead_phone || "Desconhecido";
        const segments = highlightSegments(r.snippet, query);
        return (
          <button
            key={r.message_id}
            onClick={() => onSelect(r.conversation_id, r.message_id)}
            className="w-full flex items-start gap-3 px-3 py-2.5 text-left hover:bg-[#faf9f6] rounded-[6px] mx-2 cursor-pointer"
            style={{ width: "calc(100% - 16px)" }}
          >
            <div className="w-9 h-9 rounded-full bg-[#8a8a80] flex items-center justify-center text-white text-sm font-medium flex-shrink-0 mt-0.5">
              {getInitial(displayName)}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1">
                <span className="text-sm font-semibold text-[#111111] truncate">{displayName}</span>
                <span className="ml-auto text-[10px] text-[#7b7b78] flex-shrink-0">
                  {formatRelativeTime(r.match_created_at)}
                </span>
              </div>
              <p className="text-xs text-[#7b7b78] mt-0.5 line-clamp-2">
                {segments.map((seg, i) =>
                  seg.match ? (
                    <mark key={i} className="bg-yellow-200 text-[#111111] rounded-sm px-0.5">
                      {seg.text}
                    </mark>
                  ) : (
                    <span key={i}>{seg.text}</span>
                  ),
                )}
              </p>
              {r.match_count > 1 && (
                <span className="text-[10px] text-[#9b9b98]">{r.match_count} mensagens</span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

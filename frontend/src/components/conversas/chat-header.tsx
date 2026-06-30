"use client";

import { useState, useRef, useEffect } from "react";
import type { Conversation, Tag } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AgentPersonaBadge } from "@/components/conversas/agent-persona-badge";

interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
  onMarkRead?: () => void | Promise<void>;
  onBack?: () => void;
  onOpenContact?: () => void;
  onOptOut?: () => void | Promise<void>;
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
  onMarkRead,
  onBack,
  onOpenContact,
  onOptOut,
}: ChatHeaderProps) {
  const lead = conversation.leads;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarColor = getStageColor(lead?.stage);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  async function handleFinalize() {
    setMenuOpen(false);
    const supabase = createClient();
    await supabase
      .from("conversations")
      .update({ last_seller_response_at: new Date().toISOString() })
      .eq("id", conversation.id);
    await onMarkRead?.();
  }

  return (
    <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3 flex-shrink-0">
      {/* Mobile back button */}
      {onBack && (
        <button
          onClick={onBack}
          className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-[4px] text-[#313130] hover:bg-[#dedbd6]/60 transition-colors"
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

      {/* Name */}
      <div
        className={`flex-1 min-w-0${onOpenContact ? " cursor-pointer" : ""}`}
        onClick={onOpenContact}
      >
        <h2 className="text-[#111111] font-medium text-[14px] truncate">{displayName}</h2>
        <AgentPersonaBadge conversation={conversation} />
      </div>

      {/* Valéria IA button — hidden for human-only channels */}
      {conversation.channels?.mode !== "human" && (
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
            className={`inline-block h-1.5 w-1.5 rounded-full ${aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"}`}
            aria-hidden
          />
          Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
        </button>
      )}

      {/* Finalizar Conversa — ação dedicada, ao lado do menu "..." */}
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={handleFinalize}
              className="inline-flex items-center gap-2 rounded-[4px] border border-[#dedbd6] bg-[#faf9f6] px-2.5 py-1 text-xs font-medium text-[#111111] transition-colors hover:bg-[#dedbd6]/60 hover:border-[#cbc7c0] flex-shrink-0"
              aria-label="Finalizar Conversa"
            >
              <svg
                className="w-4 h-4 text-[#7b7b78] flex-shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
                aria-hidden
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="hidden sm:inline">Finalizar Conversa</span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="sm:hidden">
            Finalizar Conversa
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {/* ... dropdown */}
      <div className="relative flex-shrink-0" ref={menuRef}>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          className="w-8 h-8 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#dedbd6]/60 transition-colors"
          aria-label="Mais opções"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <circle cx="5" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="19" cy="12" r="2" />
          </svg>
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full mt-1 w-52 bg-white border border-[#dedbd6] rounded-[8px] shadow-lg py-1 z-50">
            {/* Follow-up toggle */}
            <button
              type="button"
              onClick={() => { onToggleFollowup(); setMenuOpen(false); }}
              disabled={togglingFollowup}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-left transition-colors hover:bg-[#f5f3f0] ${
                togglingFollowup ? "opacity-60 cursor-not-allowed" : ""
              }`}
            >
              <span
                className={`inline-block h-2 w-2 rounded-full flex-shrink-0 ${
                  followupEnabled ? "bg-[#1e6ee8] animate-pulse" : "bg-[#7b7b78]"
                }`}
                aria-hidden
              />
              <span className="flex-1 text-[#111111]">Follow-up</span>
              <span className={`text-[11px] font-medium ${followupEnabled ? "text-[#1e6ee8]" : "text-[#7b7b78]"}`}>
                {followupEnabled ? "Ativo" : "Pausado"}
              </span>
            </button>

            {onOptOut && (
              <>
                <div className="border-t border-[#dedbd6] my-1" />
                {/* Parar mensagens — opt-out manual */}
                <button
                  type="button"
                  onClick={() => { setMenuOpen(false); onOptOut(); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-[13px] text-left hover:bg-red-50 transition-colors"
                >
                  <svg
                    className="w-4 h-4 text-red-500 flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 0 0 5.636 5.636m12.728 12.728A9 9 0 0 1 5.636 5.636m12.728 12.728L5.636 5.636" />
                  </svg>
                  <span className="text-red-600">Parar mensagens</span>
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import type { Conversation } from "@/lib/types";
import { getAgentPersona } from "@/lib/agent-persona";

interface AgentPersonaBadgeProps {
  conversation: Conversation;
}

export function AgentPersonaBadge({ conversation }: AgentPersonaBadgeProps) {
  const persona = getAgentPersona(conversation);
  if (!persona) return null;
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-[3px] px-1.5 py-px text-[10px] font-semibold leading-none tracking-wide flex-shrink-0"
      style={{ backgroundColor: `${persona.color}15`, color: persona.color }}
      title={
        persona.direction === "human"
          ? "Atendimento humano (IA desativada / canal humano)"
          : persona.direction === "outbound"
            ? "Atendimento ativo (outbound)"
            : "Atendimento receptivo (inbound)"
      }
    >
      <svg
        className="w-2.5 h-2.5"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {persona.direction === "human" ? (
          // ícone de pessoa (neutro) — atendimento humano / handoff
          <path d="M12 12a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0" />
        ) : persona.direction === "outbound" ? (
          <path d="M12 19V5M5 12l7-7 7 7" />
        ) : (
          <path d="M12 5v14M19 12l-7 7-7-7" />
        )}
      </svg>
      {persona.label}
    </span>
  );
}

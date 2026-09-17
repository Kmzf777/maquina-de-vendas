"use client";

import { useState } from "react";
import type { Campaign } from "@/lib/types";
import { campaignNodeCount } from "@/lib/campaign-node-count";
import { cardToggleState, isSystemCampaign } from "@/lib/system-campaign";

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:    { bg: "bg-[#f0ede8]",       text: "text-[#7b7b78]",   label: "Rascunho" },
  active:   { bg: "bg-[#0bdf50]/10",    text: "text-[#0bdf50]",   label: "Ativa" },
  paused:   { bg: "bg-[#fe4c02]/10",    text: "text-[#fe4c02]",   label: "Pausada" },
  archived: { bg: "bg-[#f0ede8]",       text: "text-[#7b7b78]",   label: "Arquivada" },
};

/**
 * Corpo de erro do POST /activate (ou /pause) → mensagens para o operador.
 *
 * A validação de 12 regras do backend (`backend/app/campaigns/validation.py`, atrás de
 * `backend/app/campaigns/router.py`) recusa a ativação com
 * `{detail: {problemas: [{no_id, codigo, mensagem}]}}` — um item por nó com defeito,
 * não uma `error` string plana. O proxy Next (`activate/route.ts`) devolve
 * `{error: "..."}` (string) quando o próprio FastAPI está fora do ar (502). Um corpo
 * que não bate com nenhum dos dois formatos ainda precisa virar mensagem: silêncio
 * nunca é resposta aceitável para uma recusa.
 *
 * Pura e exportada para o teste direto — é aqui que mora a lógica de verdade.
 * Duplicada (mesmo formato) em `cadence-flow/index.tsx`, o outro chamador de
 * /activate: os dois arquivos não compartilham módulo de lib nesta task.
 */
export function parseActivationErrorMessages(data: unknown): string[] {
  const body = (data ?? {}) as { detail?: { problemas?: unknown }; error?: unknown };
  const problemas = body.detail?.problemas;
  if (Array.isArray(problemas) && problemas.length > 0) {
    return problemas.map((p) => {
      const mensagem = (p as { mensagem?: unknown } | null)?.mensagem;
      return typeof mensagem === "string" && mensagem ? mensagem : "Problema não especificado.";
    });
  }
  if (typeof body.error === "string" && body.error) {
    return [body.error];
  }
  return ["Não foi possível concluir a operação. Tente novamente."];
}

interface CadenceCardProps {
  campaign: Campaign;
  onClick: () => void;
  onRefresh: () => void;
  /** Estado da flag de visibilidade do espelho do motor — só usado pelo card de sistema. */
  mirrorVisible?: boolean;
  /** Aciona a regra de visibilidade do espelho (POST /api/cadence/mirror-visibility). */
  onToggleMirror?: () => void | Promise<void>;
}

export function CadenceCard({ campaign, onClick, onRefresh, mirrorVisible, onToggleMirror }: CadenceCardProps) {
  const [saving, setSaving] = useState(false);

  // O espelho do motor da Valéria é tecnicamente draft (proteção de backend contra
  // execução dupla), mas "Rascunho" sugere fluxo inacabado — o selo vira "Sistema".
  const st = isSystemCampaign(campaign.id)
    ? { bg: "bg-[#ff5600]/10", text: "text-[#ff5600]", label: "Sistema" }
    : (STATUS_STYLES[campaign.status] ?? STATUS_STYLES.draft);
  const nodeCount = campaignNodeCount(campaign);

  // Toggle padronizado em TODO card (11/07): convencional = activate/pause da
  // campanha; espelho do motor = regra de visibilidade/estado (NUNCA activate —
  // que segue bloqueado com 409 no backend contra execução dupla).
  const toggle = cardToggleState(campaign, mirrorVisible ?? false);

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation(); // o card inteiro navega para o builder — o switch não
    if (saving) return;
    setSaving(true);
    try {
      if (toggle.kind === "mirror") {
        await onToggleMirror?.();
      } else {
        const endpoint = toggle.on ? "pause" : "activate";
        const res = await fetch(`/api/campaigns/${campaign.id}/${endpoint}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          // A validação de 12 regras devolve `detail.problemas[]` — um item por nó com
          // defeito, não uma `error` string. "Erro ao ativar: Bad Request" escondia os
          // motivos de verdade (e, com mais de um problema, todos menos o primeiro).
          alert(parseActivationErrorMessages(data).join("\n\n"));
        } else {
          onRefresh();
        }
      }
    } catch (err) {
      alert(`Erro de rede: ${err}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      onClick={onClick}
      className="bg-white border border-[#dedbd6] rounded-[8px] p-5 cursor-pointer hover:border-[#111111] transition-colors"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[15px] font-medium text-[#111111] leading-tight">{campaign.name}</p>
          {campaign.description && (
            <p className="text-[12px] text-[#7b7b78] mt-0.5">{campaign.description}</p>
          )}
        </div>
        <span className={`text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] flex-shrink-0 ml-2 ${st.bg} ${st.text}`}>
          {st.label}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-[12px] text-[#7b7b78]">
          <span>{nodeCount} nós</span>
          <span>·</span>
          <span>Criada {new Date(campaign.created_at).toLocaleDateString("pt-BR")}</span>
        </div>
        <button
          onClick={handleToggle}
          disabled={saving}
          role="switch"
          aria-checked={toggle.on}
          title={
            toggle.kind === "mirror"
              ? (toggle.on ? "Desativar espelho do motor" : "Ativar espelho do motor")
              : (toggle.on ? "Pausar cadência" : "Ativar cadência")
          }
          className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
            toggle.on ? "bg-[#0bdf50]" : "bg-[#dedbd6]"
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
              toggle.on ? "translate-x-[18px]" : "translate-x-[3px]"
            }`}
          />
        </button>
      </div>
    </div>
  );
}

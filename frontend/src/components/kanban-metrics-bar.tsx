"use client";

import { useEffect, useMemo, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { Lead } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";
import {
  fetchRepasseResposta,
  formatarMinutos,
  resumirTempoCloser,
  type RepasseResposta,
} from "@/lib/repasse-resposta";

interface KanbanMetricsBarProps {
  leads: Lead[];
}

export function KanbanMetricsBar({ leads }: KanbanMetricsBarProps) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const leadsToday = leads.filter((l) => new Date(l.created_at) >= today).length;
  const leadsYesterday = leads.filter((l) => {
    const d = new Date(l.created_at);
    return d >= yesterday && d < today;
  }).length;

  // Tempo até o closer assumir (D4/D6): minutos úteis da view, a partir do 1º repasse.
  // Busca só os leads exibidos (lotes de 200 em fetchRepasseResposta). A chave é o
  // conjunto ordenado de ids: re-render/filtro que não muda o conjunto não refaz a consulta.
  const idsKey = useMemo(
    () => Array.from(new Set(leads.map((l) => l.id))).sort().join(","),
    [leads],
  );
  const [repasses, setRepasses] = useState<{ key: string; mapa: Map<string, RepasseResposta> } | null>(null);
  useEffect(() => {
    let vivo = true;
    const ids = idsKey ? idsKey.split(",") : [];
    fetchRepasseResposta(createClient() as unknown as SupabaseClient, ids)
      .then((mapa) => {
        if (vivo) setRepasses({ key: idsKey, mapa });
      })
      .catch(() => {
        // View ausente/erro: mostra "—" e o resto da barra segue.
        if (vivo) setRepasses({ key: idsKey, mapa: new Map() });
      });
    return () => {
      vivo = false;
    };
  }, [idsKey]);
  const resumo =
    repasses && repasses.key === idsKey ? resumirTempoCloser(repasses.mapa, idsKey ? idsKey.split(",") : []) : null;
  const responseStr = formatarMinutos(resumo?.mediana);

  return (
    <div className="bg-[#f7f5f1] border-b border-[#dedbd6] px-6 py-3 flex gap-8 flex-shrink-0">
      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.3px' }} className="text-[20px] font-normal text-[#111111]">
          {leads.length}
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Total no funil</span>
      </div>

      <div className="flex flex-col">
        <span style={{ letterSpacing: '-0.3px' }} className="text-[20px] font-normal text-[#111111]">
          {leadsToday} / {leadsYesterday}
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Novos hoje / ontem</span>
      </div>

      <div className="flex flex-col">
        <span
          data-testid="tempo-closer"
          style={{ letterSpacing: '-0.3px' }}
          className="text-[20px] font-normal text-[#111111]"
          title="Mediana, em horário comercial do vendedor, do 1º repasse até a 1ª mensagem do closer"
        >
          {responseStr}
        </span>
        <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
          Tempo até o closer assumir (horário comercial)
        </span>
        {resumo && resumo.amostras > 0 && (
          <span className="text-[11px] text-[#7b7b78]">
            mediana · média {formatarMinutos(resumo.media)} · {resumo.amostras} {resumo.amostras === 1 ? "lead" : "leads"}
          </span>
        )}
      </div>
    </div>
  );
}

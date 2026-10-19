"use client";

import { useEffect, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { Lead } from "@/lib/types";
import { createClient } from "@/lib/supabase/client";
import {
  fetchRepasseRespostaTodas,
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
  // A view é lida uma vez; o filtro da página só muda quais leads entram na conta.
  const [repasses, setRepasses] = useState<Map<string, RepasseResposta> | null>(null);
  useEffect(() => {
    let vivo = true;
    fetchRepasseRespostaTodas(createClient() as unknown as SupabaseClient)
      .then((m) => {
        if (vivo) setRepasses(m);
      })
      .catch(() => {
        // View ausente/erro: mostra "—" e o resto da barra segue.
        if (vivo) setRepasses(new Map());
      });
    return () => {
      vivo = false;
    };
  }, []);
  const resumo = repasses ? resumirTempoCloser(repasses, leads.map((l) => l.id)) : null;
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

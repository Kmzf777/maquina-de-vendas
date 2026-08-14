"use client";

import { useState } from "react";
import { findInadimplentes, valorVencidoDe, type LeadComTags } from "@/lib/inadimplentes";

const MOEDA = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

interface InadimplentesWarningProps {
  leads: LeadComTags[];
  selectedLeadIds: Set<string>;
  onDeselect?: (ids: string[]) => void;
  variant: "selection" | "review";
}

/**
 * Avisa que há leads com débito vencido entre os selecionados.
 *
 * Não bloqueia a criação do disparo (decisão D5 do spec de 14/08): a base
 * inclui inadimplentes de propósito; o papel do aviso é tornar a inclusão num
 * disparo específico consciente, não impedi-la.
 */
export function InadimplentesWarning({
  leads,
  selectedLeadIds,
  onDeselect,
  variant,
}: InadimplentesWarningProps) {
  const [expandido, setExpandido] = useState(false);
  const { leads: inadimplentes, totalVencido } = findInadimplentes(leads, selectedLeadIds);

  if (inadimplentes.length === 0) return null;

  const total = MOEDA.format(totalVencido);

  if (variant === "review") {
    return (
      <p className="text-[13px] text-[#c41c1c]">
        ⚠ {inadimplentes.length} dos {selectedLeadIds.size} com débito vencido ({total})
      </p>
    );
  }

  const visiveis = expandido ? inadimplentes : inadimplentes.slice(0, 3);
  const restantes = inadimplentes.length - visiveis.length;

  return (
    <div className="border border-[#c41c1c]/30 bg-[#c41c1c]/5 rounded-[6px] p-3 space-y-2">
      <p className="text-[13px] text-[#c41c1c] font-medium">
        ⚠ {inadimplentes.length} dos {selectedLeadIds.size} selecionados têm débito vencido
        {totalVencido > 0 && <span className="font-normal"> ({total})</span>}
      </p>

      <ul className="space-y-0.5">
        {visiveis.map((lead) => {
          const valor = valorVencidoDe(lead);
          const dias = lead.metadata?.dias_atraso_max;
          return (
            <li key={lead.id} className="text-[12px] text-[#7b7b78] flex gap-2">
              <span className="text-[#111111] truncate max-w-[160px]">
                {lead.name ?? "—"}
              </span>
              <span>{lead.phone}</span>
              {valor > 0 && <span>{MOEDA.format(valor)}</span>}
              {dias ? <span>· {String(dias)}d</span> : null}
            </li>
          );
        })}
      </ul>

      <div className="flex items-center gap-3">
        {restantes > 0 && (
          <button
            type="button"
            onClick={() => setExpandido(true)}
            className="text-[12px] text-[#7b7b78] underline hover:text-[#111111] transition-colors"
          >
            + {restantes} outro{restantes !== 1 ? "s" : ""}
          </button>
        )}
        {expandido && inadimplentes.length > 3 && (
          <button
            type="button"
            onClick={() => setExpandido(false)}
            className="text-[12px] text-[#7b7b78] underline hover:text-[#111111] transition-colors"
          >
            ver menos
          </button>
        )}
        {onDeselect && (
          <button
            type="button"
            onClick={() => onDeselect(inadimplentes.map((l) => l.id))}
            className="ml-auto text-[12px] text-[#111111] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-white hover:border-[#111111] transition-colors"
          >
            Desmarcar os {inadimplentes.length}
          </button>
        )}
      </div>
    </div>
  );
}

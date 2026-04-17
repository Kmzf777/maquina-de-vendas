"use client";

import { useState } from "react";
import type { Deal } from "@/lib/types";
import { DEAL_STAGES, DEAL_CATEGORIES } from "@/lib/constants";

function formatCurrency(value: number): string {
  if (value === 0) return "R$ 0";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface DealDetailSidebarProps {
  deal: Deal;
  onClose: () => void;
  onUpdate: (dealId: string, data: Record<string, unknown>) => Promise<void>;
}

export function DealDetailSidebar({ deal, onClose, onUpdate }: DealDetailSidebarProps) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    title: deal.title,
    value: deal.value,
    category: deal.category || "",
    assigned_to: deal.assigned_to || "",
    expected_close_date: deal.expected_close_date || "",
  });

  const lead = deal.leads;
  const displayName = lead?.name || lead?.company || lead?.nome_fantasia || lead?.phone || "—";
  const stageInfo = DEAL_STAGES.find((s) => s.key === deal.stage);
  const categoryInfo = DEAL_CATEGORIES.find((c) => c.key === deal.category);
  const daysActive = Math.floor(
    (Date.now() - new Date(deal.created_at).getTime()) / (1000 * 60 * 60 * 24)
  );

  async function handleSave() {
    await onUpdate(deal.id, {
      title: form.title,
      value: Number(form.value) || 0,
      category: form.category || null,
      assigned_to: form.assigned_to || null,
      expected_close_date: form.expected_close_date || null,
    });
    setEditing(false);
  }

  return (
    <div className="fixed inset-y-0 right-0 w-[380px] bg-[#faf9f6] border-l border-[#dedbd6] z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-[#dedbd6]">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: stageInfo?.dotColor || "#dedbd6" }} />
          <span className="text-[13px] text-[#111111]">{stageInfo?.label || deal.stage}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setEditing(!editing)} className="text-[12px] text-[#7b7b78] hover:text-[#111111] px-2 py-1 rounded-[4px] border border-[#dedbd6] hover:border-[#111111] transition-colors">
            {editing ? "Cancelar" : "Editar"}
          </button>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {editing ? (
          <div className="space-y-3">
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Titulo</label>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Valor (R$)</label>
              <input type="number" value={form.value} onChange={(e) => setForm({ ...form, value: Number(e.target.value) })} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Categoria</label>
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full">
                <option value="">Nenhuma</option>
                {DEAL_CATEGORIES.map((c) => (<option key={c.key} value={c.key}>{c.label}</option>))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Responsavel</label>
              <input value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} placeholder="Nome do vendedor" className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full" />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Previsao de fechamento</label>
              <input type="date" value={form.expected_close_date} onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
            </div>
            <button onClick={handleSave} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] w-full">Salvar</button>
          </div>
        ) : (
          <>
            <div>
              <h3 className="text-[18px] font-normal text-[#111111]" style={{ letterSpacing: '-0.48px', lineHeight: '1.00' }}>{deal.title}</h3>
              <p className="text-[20px] font-normal text-[#111111] mt-1" style={{ letterSpacing: '-0.2px' }}>{formatCurrency(deal.value)}</p>
            </div>
            {categoryInfo && (
              <span className="inline-block text-[11px] uppercase tracking-[0.4px] px-2.5 py-0.5 rounded-[4px]" style={{ backgroundColor: categoryInfo.color + "22", color: categoryInfo.color }}>
                {categoryInfo.label}
              </span>
            )}
          </>
        )}

        <div className="border-t border-[#dedbd6] pt-4">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-2">Lead vinculado</span>
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-[6px] bg-[#dedbd6] flex items-center justify-center text-[13px] font-normal text-[#111111]">
              {displayName[0]?.toUpperCase() || "?"}
            </div>
            <div>
              <p className="text-[14px] text-[#111111]">{displayName}</p>
              <p className="text-[12px] text-[#7b7b78]">{lead?.phone || "—"}</p>
            </div>
          </div>
        </div>

        <div className="border-t border-[#dedbd6] pt-4 space-y-2">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-2">Detalhes</span>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#7b7b78]">Responsavel</span>
            <span className="text-[13px] text-[#111111]">{deal.assigned_to || "—"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#7b7b78]">Previsao</span>
            <span className="text-[13px] text-[#111111]">
              {deal.expected_close_date ? new Date(deal.expected_close_date).toLocaleDateString("pt-BR") : "—"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#7b7b78]">Dias ativo</span>
            <span className="text-[13px] text-[#111111]">{daysActive}d</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[12px] text-[#7b7b78]">Criado em</span>
            <span className="text-[13px] text-[#111111]">{new Date(deal.created_at).toLocaleDateString("pt-BR")}</span>
          </div>
          {deal.lost_reason && (
            <div className="mt-2 p-3 bg-[#faf9f6] border border-[#dedbd6] rounded-[6px]">
              <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Motivo da perda</span>
              <p className="text-[13px] text-[#111111]">{deal.lost_reason}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

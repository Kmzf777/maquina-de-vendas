"use client";

import { useState } from "react";
import { DEAL_CATEGORIES } from "@/lib/constants";
import type { Lead } from "@/lib/types";

interface DealCreateModalProps {
  leads: Lead[];
  preselectedLead?: Lead;
  onClose: () => void;
  onCreate: (data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
  }) => Promise<void>;
}

export function DealCreateModal({ leads, preselectedLead, onClose, onCreate }: DealCreateModalProps) {
  const [title, setTitle] = useState("");
  const [leadSearch, setLeadSearch] = useState(
    preselectedLead ? (preselectedLead.name || preselectedLead.phone) : ""
  );
  const [selectedLeadId, setSelectedLeadId] = useState(preselectedLead?.id || "");
  const [value, setValue] = useState("");
  const [category, setCategory] = useState("");
  const [expectedClose, setExpectedClose] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [saving, setSaving] = useState(false);

  const filteredLeads = leads.filter((l) => {
    if (!leadSearch) return true;
    const q = leadSearch.toLowerCase();
    return (
      (l.name || "").toLowerCase().includes(q) ||
      l.phone.includes(q) ||
      (l.company || "").toLowerCase().includes(q)
    );
  }).slice(0, 8);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedLeadId || !title.trim()) return;
    setSaving(true);
    await onCreate({
      lead_id: selectedLeadId,
      title: title.trim(),
      value: Number(value) || 0,
      category,
      expected_close_date: expectedClose,
    });
    setSaving(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: '-0.48px', lineHeight: '1.00' }}>Nova Oportunidade</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Lead *</label>
            <input
              value={leadSearch}
              onChange={(e) => { setLeadSearch(e.target.value); setSelectedLeadId(""); setShowDropdown(true); }}
              onFocus={() => setShowDropdown(true)}
              placeholder="Buscar lead por nome ou telefone..."
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
              readOnly={!!preselectedLead}
            />
            {showDropdown && !selectedLeadId && !preselectedLead && filteredLeads.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-[#dedbd6] rounded-[6px] z-10 max-h-48 overflow-y-auto">
                {filteredLeads.map((l) => (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => {
                      setSelectedLeadId(l.id);
                      setLeadSearch(l.name || l.phone);
                      setShowDropdown(false);
                      if (!title) setTitle(`${l.name || l.phone} - Oportunidade`);
                    }}
                    className="w-full text-left px-3 py-2 text-[13px] hover:bg-[#faf9f6] flex justify-between transition-colors"
                  >
                    <span className="text-[#111111]">{l.name || l.phone}</span>
                    <span className="text-[#7b7b78]">{l.phone}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Titulo *</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ex: Atacado 50kg - Cafe Especial" className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full" required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Valor (R$)</label>
              <input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="0" className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full" />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Categoria</label>
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full">
                <option value="">Selecionar...</option>
                {DEAL_CATEGORIES.map((c) => (<option key={c.key} value={c.key}>{c.label}</option>))}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Previsao de fechamento</label>
            <input type="date" value={expectedClose} onChange={(e) => setExpectedClose(e.target.value)} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
          </div>
          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">Cancelar</button>
            <button type="submit" disabled={saving || !selectedLeadId || !title.trim()} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Oportunidade"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

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
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="relative bg-white rounded-2xl p-6 w-full max-w-[480px] shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-semibold text-[#1f1f1f] mb-4">Nova Oportunidade</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Lead *</label>
            <input
              value={leadSearch}
              onChange={(e) => { setLeadSearch(e.target.value); setSelectedLeadId(""); setShowDropdown(true); }}
              onFocus={() => setShowDropdown(true)}
              placeholder="Buscar lead por nome ou telefone..."
              className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
              readOnly={!!preselectedLead}
            />
            {showDropdown && !selectedLeadId && !preselectedLead && filteredLeads.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-[#e5e5dc] rounded-xl shadow-lg z-10 max-h-48 overflow-y-auto">
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
                    className="w-full text-left px-3 py-2 text-[13px] hover:bg-[#f6f7ed] flex justify-between"
                  >
                    <span className="text-[#1f1f1f]">{l.name || l.phone}</span>
                    <span className="text-[#9ca3af]">{l.phone}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Titulo *</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ex: Atacado 50kg - Cafe Especial" className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]" required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Valor (R$)</label>
              <input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="0" className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]" />
            </div>
            <div>
              <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Categoria</label>
              <select value={category} onChange={(e) => setCategory(e.target.value)} className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] bg-white">
                <option value="">Selecionar...</option>
                {DEAL_CATEGORIES.map((c) => (<option key={c.key} value={c.key}>{c.label}</option>))}
              </select>
            </div>
          </div>
          <div>
            <label className="text-[11px] text-[#9ca3af] uppercase block mb-1">Previsao de fechamento</label>
            <input type="date" value={expectedClose} onChange={(e) => setExpectedClose(e.target.value)} className="w-full text-[14px] px-3 py-2.5 rounded-xl border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]" />
          </div>
          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose} className="px-5 py-2.5 rounded-xl border border-[#e5e5dc] bg-white text-[13px] text-[#5f6368] hover:bg-[#f6f7ed]">Cancelar</button>
            <button type="submit" disabled={saving || !selectedLeadId || !title.trim()} className="px-5 py-2.5 rounded-xl bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Oportunidade"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { DEAL_CATEGORIES } from "@/lib/constants";
import type { Lead, Pipeline } from "@/lib/types";

interface DealCreateModalProps {
  leads: Lead[];
  pipelines?: Pipeline[];
  preselectedLead?: Lead;
  onClose: () => void;
  onCreate: (data: {
    lead_id: string;
    title: string;
    value: number;
    category: string;
    expected_close_date: string;
    pipeline_id?: string;
  }) => Promise<void>;
}

export function DealCreateModal({ leads, pipelines, preselectedLead, onClose, onCreate }: DealCreateModalProps) {
  const [title, setTitle] = useState("");
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(preselectedLead ?? null);
  const [selectedLeadId, setSelectedLeadId] = useState(preselectedLead?.id || "");
  const [selectedPipelineId, setSelectedPipelineId] = useState(pipelines?.[0]?.id || "");
  const [value, setValue] = useState("");
  const [category, setCategory] = useState("");
  const [expectedClose, setExpectedClose] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 20 recentes por padrão; filtra tudo quando há busca
  const filteredLeads = leadSearch.trim()
    ? leads.filter((l) => {
        const q = leadSearch.toLowerCase();
        return (
          (l.name || "").toLowerCase().includes(q) ||
          l.phone.includes(q) ||
          (l.company || "").toLowerCase().includes(q)
        );
      }).slice(0, 30)
    : leads.slice(0, 20);

  function handleSelectLead(l: Lead) {
    setSelectedLead(l);
    setSelectedLeadId(l.id);
    setLeadSearch("");
    setShowDropdown(false);
    if (!title) setTitle(`${l.name || l.phone} - Oportunidade`);
  }

  function handleClearLead() {
    setSelectedLead(null);
    setSelectedLeadId("");
    setLeadSearch("");
    setShowDropdown(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedLeadId || !title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onCreate({
        lead_id: selectedLeadId,
        title: title.trim(),
        value: Number(value) || 0,
        category,
        expected_close_date: expectedClose,
        pipeline_id: selectedPipelineId || undefined,
      });
      onClose();
    } catch (err) {
      setSaving(false);
      setError(err instanceof Error ? err.message : "Erro ao criar oportunidade.");
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: '-0.48px', lineHeight: '1.00' }}>Nova Oportunidade</h3>
        <form onSubmit={handleSubmit} className="space-y-4">

          {/* Campo Lead */}
          <div className="relative">
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Lead *</label>

            {selectedLead ? (
              /* Card do lead selecionado */
              <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2.5 flex items-center justify-between">
                <div className="flex flex-col gap-0.5">
                  <span className="text-[14px] font-medium text-[#111111] leading-tight">
                    {selectedLead.name || selectedLead.phone}
                  </span>
                  <span className="text-[12px] text-[#7b7b78] leading-tight">
                    {selectedLead.phone}
                  </span>
                </div>
                {!preselectedLead && (
                  <button
                    type="button"
                    onClick={handleClearLead}
                    className="text-[#7b7b78] hover:text-[#111111] transition-colors text-[18px] leading-none pl-3 flex-shrink-0"
                    title="Remover lead"
                  >
                    ×
                  </button>
                )}
              </div>
            ) : (
              /* Input de busca */
              <>
                <input
                  value={leadSearch}
                  onChange={(e) => { setLeadSearch(e.target.value); setShowDropdown(true); }}
                  onFocus={() => setShowDropdown(true)}
                  onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
                  placeholder="Buscar por nome, telefone ou empresa..."
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  readOnly={!!preselectedLead}
                  autoComplete="off"
                />
                {showDropdown && !preselectedLead && (
                  <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-[#dedbd6] rounded-[6px] z-10 max-h-52 overflow-y-auto shadow-sm">
                    {filteredLeads.length === 0 ? (
                      <p className="px-3 py-2.5 text-[13px] text-[#7b7b78]">Nenhum lead encontrado.</p>
                    ) : (
                      <>
                        {!leadSearch.trim() && (
                          <div className="px-3 py-1.5 border-b border-[#f0ede8]">
                            <span className="text-[10px] uppercase tracking-[0.8px] text-[#7b7b78]">Recentes</span>
                          </div>
                        )}
                        {filteredLeads.map((l) => (
                          <button
                            key={l.id}
                            type="button"
                            onMouseDown={() => handleSelectLead(l)}
                            className="w-full text-left px-3 py-2 hover:bg-[#faf9f6] flex items-center justify-between gap-3 transition-colors"
                          >
                            <span className="text-[13px] text-[#111111] font-medium truncate">{l.name || l.phone}</span>
                            <span className="text-[12px] text-[#7b7b78] flex-shrink-0">{l.phone}</span>
                          </button>
                        ))}
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {pipelines && pipelines.length > 0 && (
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Funil *</label>
              <select
                value={selectedPipelineId}
                onChange={(e) => setSelectedPipelineId(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                required
              >
                <option value="">Selecionar funil...</option>
                {pipelines.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          )}

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

          {error && (
            <p className="text-[12px] text-red-600 bg-red-50 border border-red-200 rounded-[6px] px-3 py-2">{error}</p>
          )}

          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">Cancelar</button>
            <button type="submit" disabled={saving || !selectedLeadId || !title.trim() || (!!pipelines?.length && !selectedPipelineId)} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Oportunidade"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

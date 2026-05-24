"use client";

import { useState, useEffect } from "react";
import type { Lead, Pipeline, PipelineStage } from "@/lib/types";

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
    stage_id?: string;
  }) => Promise<void>;
}

export function DealCreateModal({ leads, pipelines, preselectedLead, onClose, onCreate }: DealCreateModalProps) {
  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLead, setSelectedLead] = useState<Lead | null>(preselectedLead ?? null);
  const [selectedLeadId, setSelectedLeadId] = useState(preselectedLead?.id || "");
  const [selectedPipelineId, setSelectedPipelineId] = useState(pipelines?.[0]?.id || "");
  const [selectedStageId, setSelectedStageId] = useState("");
  const [stageOptions, setStageOptions] = useState<PipelineStage[]>([]);
  const [notes, setNotes] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [stagesLoading, setStagesLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedPipelineId) { setStageOptions([]); setSelectedStageId(""); return; }
    setStagesLoading(true);
    fetch(`/api/pipelines/${selectedPipelineId}/stages`)
      .then((r) => r.json())
      .then((data: PipelineStage[]) => {
        const active = Array.isArray(data) ? data.filter((s) => !s.is_protected) : [];
        setStageOptions(active);
        setSelectedStageId(active[0]?.id || "");
      })
      .catch(() => { setStageOptions([]); setSelectedStageId(""); })
      .finally(() => setStagesLoading(false));
  }, [selectedPipelineId]);

  const filteredLeads = leadSearch.trim()
    ? leads.filter((l) => {
        const q = leadSearch.toLowerCase();
        return (l.name || "").toLowerCase().includes(q) || l.phone.includes(q) || (l.company || "").toLowerCase().includes(q);
      }).slice(0, 30)
    : leads.slice(0, 20);

  function handleSelectLead(l: Lead) {
    setSelectedLead(l);
    setSelectedLeadId(l.id);
    setLeadSearch("");
    setShowDropdown(false);
  }

  function handleClearLead() {
    setSelectedLead(null);
    setSelectedLeadId("");
    setLeadSearch("");
    setShowDropdown(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedLeadId || !selectedPipelineId || !selectedStageId) return;
    setSaving(true);
    setError(null);

    const pipeline = pipelines?.find((p) => p.id === selectedPipelineId);
    const leadName = selectedLead?.name || selectedLead?.phone || "Lead";
    const autoTitle = `${leadName} - ${pipeline?.name || "Funil"}`;

    try {
      await onCreate({
        lead_id: selectedLeadId,
        title: autoTitle,
        value: 0,
        category: "",
        expected_close_date: "",
        pipeline_id: selectedPipelineId,
        stage_id: selectedStageId,
      });

      if (notes.trim()) {
        await fetch(`/api/leads/${selectedLeadId}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author: "Usuário", content: notes.trim() }),
        });
      }

      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar card.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Novo Card
        </h3>
        <form onSubmit={handleSubmit} className="space-y-4">

          {/* Lead */}
          <div className="relative">
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Lead *</label>
            {selectedLead ? (
              <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2.5 flex items-center justify-between">
                <div className="flex flex-col gap-0.5">
                  <span className="text-[14px] font-medium text-[#111111] leading-tight">{selectedLead.name || selectedLead.phone}</span>
                  <span className="text-[12px] text-[#7b7b78] leading-tight">{selectedLead.phone}</span>
                </div>
                {!preselectedLead && (
                  <button type="button" onClick={handleClearLead} className="text-[#7b7b78] hover:text-[#111111] transition-colors text-[18px] leading-none pl-3 flex-shrink-0" title="Remover lead">×</button>
                )}
              </div>
            ) : (
              <>
                <input
                  value={leadSearch}
                  onChange={(e) => { setLeadSearch(e.target.value); setShowDropdown(true); }}
                  onFocus={() => setShowDropdown(true)}
                  onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
                  placeholder="Buscar por nome, telefone ou empresa..."
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  autoComplete="off"
                />
                {showDropdown && (
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
                          <button key={l.id} type="button" onMouseDown={() => handleSelectLead(l)}
                            className="w-full text-left px-3 py-2 hover:bg-[#faf9f6] flex items-center justify-between gap-3 transition-colors">
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

          {/* Funil */}
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
                {pipelines.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </div>
          )}

          {/* Stage (dependente do funil) */}
          {selectedPipelineId && (
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Stage *</label>
              {stagesLoading ? (
                <p className="text-[12px] text-[#7b7b78] py-1">Carregando stages...</p>
              ) : stageOptions.length === 0 ? (
                <p className="text-[12px] text-[#7b7b78] py-1">Nenhum stage disponível.</p>
              ) : (
                <select
                  value={selectedStageId}
                  onChange={(e) => setSelectedStageId(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                  required
                >
                  {stageOptions.map((s) => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Observações */}
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Observações</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Anotações sobre este lead ou oportunidade..."
              rows={3}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full resize-none"
            />
          </div>

          {error && (
            <p className="text-[12px] text-red-600 bg-red-50 border border-red-200 rounded-[6px] px-3 py-2">{error}</p>
          )}

          <div className="flex gap-2 justify-end pt-2">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">Cancelar</button>
            <button
              type="submit"
              disabled={saving || !selectedLeadId || !selectedPipelineId || !selectedStageId}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Card"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Deal, PipelineStage } from "@/lib/types";
import { DEAL_CATEGORIES } from "@/lib/constants";

function formatCurrency(value: number): string {
  if (value === 0) return "R$ 0";
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 0 })}`;
}

interface DealDetailSidebarProps {
  deal: Deal;
  stages: PipelineStage[];
  onClose: () => void;
  onUpdate: (dealId: string, data: Record<string, unknown>) => Promise<void>;
  onDelete: (dealId: string) => void;
}

export function DealDetailSidebar({ deal, stages, onClose, onUpdate, onDelete }: DealDetailSidebarProps) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [form, setForm] = useState({
    title: deal.title,
    value: deal.value,
    category: deal.category || "",
    assigned_to: deal.assigned_to || "",
    expected_close_date: deal.expected_close_date || "",
  });
  const [notesDraft, setNotesDraft] = useState(deal.leads?.notes || "");
  const [savingNotes, setSavingNotes] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [notesSaved, setNotesSaved] = useState(false);

  // Sincronizar form quando o deal atualizar via realtime (sem modo edição ativo)
  useEffect(() => {
    if (!editing) {
      setForm({
        title: deal.title,
        value: deal.value,
        category: deal.category || "",
        assigned_to: deal.assigned_to || "",
        expected_close_date: deal.expected_close_date || "",
      });
    }
  }, [deal, editing]);

  // Sincronizar notas quando o lead atualizar via realtime (sem edição ativa)
  useEffect(() => {
    setNotesDraft(deal.leads?.notes || "");
  }, [deal.leads?.notes]);

  const lead = deal.leads;
  const displayName = lead?.name || lead?.company || lead?.nome_fantasia || lead?.phone || "—";
  const stageInfo = deal.pipeline_stages ?? stages.find((s) => s.id === deal.stage_id) ?? null;
  const categoryInfo = DEAL_CATEGORIES.find((c) => c.key === deal.category);
  const daysActive = Math.floor(
    (Date.now() - new Date(deal.created_at).getTime()) / (1000 * 60 * 60 * 24)
  );

  async function handleSaveNotes() {
    if (!deal.lead_id) return;
    setSavingNotes(true);
    setNotesError(null);
    setNotesSaved(false);
    try {
      const res = await fetch(`/api/leads/${deal.lead_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes: notesDraft || null }),
      });
      if (!res.ok) throw new Error();
      setNotesSaved(true);
      setTimeout(() => setNotesSaved(false), 2000);
    } catch {
      setNotesError("Erro ao salvar. Tente novamente.");
    } finally {
      setSavingNotes(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      await onUpdate(deal.id, {
        title: form.title,
        value: Number(form.value) || 0,
        category: form.category || null,
        assigned_to: form.assigned_to || null,
        expected_close_date: form.expected_close_date || null,
      });
      setEditing(false);
    } catch {
      setSaveError("Erro ao salvar. Tente novamente.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-y-0 right-0 w-[380px] bg-[#faf9f6] border-l border-[#dedbd6] z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-[#dedbd6]">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: stageInfo?.dot_color || "#dedbd6" }} />
          <span className="text-[13px] text-[#111111]">{stageInfo?.label || "—"}</span>
        </div>
        <div className="flex items-center gap-2">
          {deal.lead_id && (
            <button
              onClick={() => router.push(`/conversas?lead_id=${deal.lead_id}`)}
              className="text-[12px] text-[#7b7b78] hover:text-[#111111] px-2 py-1 rounded-[4px] border border-[#dedbd6] hover:border-[#111111] transition-colors flex items-center gap-1"
              title="Abrir conversa do lead"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              Conversa
            </button>
          )}
          <button onClick={() => setEditing(!editing)} className="text-[12px] text-[#7b7b78] hover:text-[#111111] px-2 py-1 rounded-[4px] border border-[#dedbd6] hover:border-[#111111] transition-colors">
            {editing ? "Cancelar" : "Editar"}
          </button>
          <button
            onClick={() => onDelete(deal.id)}
            className="w-8 h-8 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#e07a7a] hover:text-[#e07a7a] transition-colors"
            title="Excluir deal"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
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
            {saveError && <p className="text-[12px] text-red-600">{saveError}</p>}
            <button onClick={handleSave} disabled={saving} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] w-full disabled:opacity-50">
              {saving ? "Salvando..." : "Salvar"}
            </button>
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

        <div className="border-t border-[#dedbd6] pt-4">
          <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-2">Observacoes</span>
          <textarea
            value={notesDraft}
            onChange={(e) => setNotesDraft(e.target.value)}
            placeholder="Anotacoes sobre este lead..."
            rows={4}
            className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full resize-none"
          />
          <div className="flex items-center justify-between mt-2">
            {notesError && <p className="text-[12px] text-red-600">{notesError}</p>}
            {notesSaved && <p className="text-[12px] text-green-700">Salvo!</p>}
            {!notesError && !notesSaved && <span />}
            <button
              onClick={handleSaveNotes}
              disabled={savingNotes}
              className="text-[12px] text-[#7b7b78] hover:text-[#111111] px-3 py-1 rounded-[4px] border border-[#dedbd6] hover:border-[#111111] transition-colors disabled:opacity-50"
            >
              {savingNotes ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

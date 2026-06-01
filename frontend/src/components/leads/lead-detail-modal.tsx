"use client";

import { useState, useEffect } from "react";
import { LeadBroadcastHistory } from "./lead-broadcast-history";
import type { Lead, Tag, LeadNote, LeadEvent } from "@/lib/types";
import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import { AGENT_STAGES, LEAD_CHANNELS, DEAL_STAGES } from "@/lib/constants";

interface LeadDetailModalProps {
  lead: Lead;
  tags: Tag[];
  leadTagIds: string[];
  onClose: () => void;
  onSave: (leadId: string, data: Partial<Lead>) => Promise<void>;
  onTagsChange: (leadId: string, tagIds: string[]) => Promise<void>;
  onDelete?: (leadId: string) => Promise<void>;
}

type TabKey = "dados" | "campanhas" | "tags_notas" | "metricas";

const TABS: { key: TabKey; label: string }[] = [
  { key: "dados", label: "Dados Gerais" },
  { key: "campanhas", label: "Campanhas" },
  { key: "tags_notas", label: "Tags & Notas" },
  { key: "metricas", label: "Metricas" },
];

export function LeadDetailModal({
  lead,
  tags,
  leadTagIds,
  onClose,
  onSave,
  onTagsChange,
  onDelete,
}: LeadDetailModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("dados");
  const [form, setForm] = useState({ ...lead });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notes, setNotes] = useState<LeadNote[]>([]);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [newNote, setNewNote] = useState("");
  const [enrollments, setEnrollments] = useState<Array<{
    campaign_name: string;
    campaign_created_at: string;
    status: string;
    enrolled_at: string;
    next_execute_at: string | null;
    completed_at: string | null;
  }>>([]);
  const [currentTagIds, setCurrentTagIds] = useState<string[]>(leadTagIds);
  const [showTagDropdown, setShowTagDropdown] = useState(false);
  const [leadDeals, setLeadDeals] = useState<Array<{ id: string; title: string; value: number; stage: string; category: string | null }>>([]);

  const temp = getTemperature(lead.last_msg_at);
  const tempConfig = TEMPERATURE_CONFIG[temp];
  const initials = (lead.name || lead.phone)
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");

  // Fetch notes and events when tab changes
  useEffect(() => {
    if (activeTab === "tags_notas") {
      fetch(`/api/leads/${lead.id}/notes`).then((r) => r.json()).then(setNotes);
      fetch(`/api/leads/${lead.id}/events`).then((r) => r.json()).then(setEvents);
    }
    if (activeTab === "campanhas") {
      fetch(`/api/leads/${lead.id}/campaign-enrollments`)
        .then((r) => r.json())
        .then((data: Record<string, unknown>[]) => {
          if (Array.isArray(data)) {
            setEnrollments(
              data.map((ce) => {
                const camp = ce.campaigns as { id: string; name: string; created_at: string } | null;
                return {
                  campaign_name: camp?.name || "Campanha",
                  campaign_created_at: camp?.created_at || "",
                  status: ce.status as string,
                  enrolled_at: ce.enrolled_at as string,
                  next_execute_at: ce.next_execute_at as string | null,
                  completed_at: ce.completed_at as string | null,
                };
              })
            );
          }
        });
    }
  }, [activeTab, lead.id]);

  useEffect(() => {
    import("@/lib/supabase/client").then(({ createClient }) => {
      const supabase = createClient();
      supabase
        .from("deals")
        .select("id, title, value, stage, category")
        .eq("lead_id", lead.id)
        .order("created_at", { ascending: false })
        .then(({ data }) => {
          if (data) setLeadDeals(data);
        });
    });
  }, [lead.id]);

  function updateField(field: string, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setDirty(true);
  }

  async function handleSave() {
    setSaving(true);
    const changes: Record<string, unknown> = {};
    for (const key of Object.keys(form) as (keyof Lead)[]) {
      if (form[key] !== lead[key]) {
        changes[key] = form[key];
      }
    }
    await onSave(lead.id, changes as Partial<Lead>);
    setSaving(false);
    setDirty(false);
  }

  async function handleAddNote() {
    if (!newNote.trim()) return;
    const res = await fetch(`/api/leads/${lead.id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author: "Rafael", content: newNote.trim() }),
    });
    const note = await res.json();
    setNotes((prev) => [note, ...prev]);
    setNewNote("");
  }

  async function handleToggleTag(tagId: string) {
    let newTagIds: string[];
    if (currentTagIds.includes(tagId)) {
      newTagIds = currentTagIds.filter((id) => id !== tagId);
    } else {
      newTagIds = [...currentTagIds, tagId];
    }
    setCurrentTagIds(newTagIds);
    await onTagsChange(lead.id, newTagIds);
  }

  const availableTags = tags.filter((t) => !currentTagIds.includes(t.id));
  const activeTags = tags.filter((t) => currentTagIds.includes(t.id));

  const timeline = [
    ...notes.map((n) => ({ type: "note" as const, data: n, date: n.created_at })),
    ...events.map((e) => ({ type: "event" as const, data: e, date: e.created_at })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  function formatEventText(event: LeadEvent): string {
    switch (event.event_type) {
      case "stage_change":
        return `Stage alterado de ${event.old_value} para ${event.new_value}`;
      case "deal_stage_change":
        return `Etapa do deal alterada de ${event.old_value} para ${event.new_value}`;
      case "campaign_added":
      case "cadence_enrolled":
        return `Adicionado a cadência ${event.new_value}`;
      case "campaign_removed":
      case "cadence_unenrolled":
        return `Removido de cadência ${event.new_value}`;
      case "first_response":
        return "Primeira resposta recebida";
      default:
        return event.event_type;
    }
  }

  const daysInCrm = Math.floor((Date.now() - new Date(lead.created_at).getTime()) / (1000 * 60 * 60 * 24));
  const firstResponseTime = lead.first_response_at
    ? Math.round((new Date(lead.first_response_at).getTime() - new Date(lead.created_at).getTime()) / 60000)
    : null;
  const firstResponseStr = firstResponseTime !== null
    ? firstResponseTime < 60 ? `${firstResponseTime}min` : `${Math.round(firstResponseTime / 60)}h`
    : "\u2014";

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[720px] max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[#dedbd6] flex justify-between items-center">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-full bg-[#111111] flex items-center justify-center font-semibold text-base text-white">
              {initials}
            </div>
            <div>
              <h3
                className="text-[24px] font-normal text-[#111111]"
                style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
              >
                {lead.name || lead.phone}
              </h3>
              <p className="text-[13px] text-[#7b7b78]">
                {lead.phone}{lead.company ? ` \u00b7 ${lead.company}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            <span
              className="text-[10px] font-semibold px-2.5 py-1 rounded-[4px]"
              style={{ background: tempConfig.bg, color: tempConfig.color }}
            >
              {tempConfig.label.toUpperCase()}
            </span>
            {onDelete && (
              confirmDelete ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-[12px] text-[#7b7b78]">Confirmar?</span>
                  <button
                    onClick={async () => {
                      setDeleting(true);
                      await onDelete(lead.id);
                      setDeleting(false);
                    }}
                    disabled={deleting}
                    className="px-2.5 py-1 rounded-[4px] bg-[#c41c1c] text-white text-[12px] font-medium hover:bg-[#a01515] transition-colors disabled:opacity-50"
                  >
                    {deleting ? "..." : "Sim"}
                  </button>
                  <button
                    onClick={() => setConfirmDelete(false)}
                    className="px-2.5 py-1 rounded-[4px] border border-[#dedbd6] bg-white text-[12px] text-[#7b7b78] hover:border-[#111111] transition-colors"
                  >
                    Não
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmDelete(true)}
                  title="Deletar lead"
                  className="w-8 h-8 rounded-[4px] border border-[#dedbd6] bg-white flex items-center justify-center text-[#7b7b78] hover:text-[#c41c1c] hover:border-[#c41c1c] transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                  </svg>
                </button>
              )
            )}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-[4px] border border-[#dedbd6] bg-white flex items-center justify-center text-[#7b7b78] hover:text-[#111111] hover:border-[#111111] transition-colors"
            >
              ×
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#dedbd6] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-3 text-[13px] border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "text-[#111111] border-[#111111]"
                  : "text-[#7b7b78] border-transparent hover:text-[#111111]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="p-6 max-h-[450px] overflow-y-auto">

          {/* TAB: Dados Gerais */}
          {activeTab === "dados" && (
            <div>
              <div className="grid grid-cols-2 gap-5">
                {/* Contato */}
                <div>
                  <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Contato</p>
                  <div className="space-y-3">
                    {([
                      { label: "Nome", field: "name" as const, isReadonly: false },
                      { label: "Telefone", field: "phone" as const, isReadonly: true },
                      { label: "Email", field: "email" as const, isReadonly: false },
                      { label: "Instagram", field: "instagram" as const, isReadonly: false },
                    ]).map(({ label, field, isReadonly }) => (
                      <div key={field}>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">{label}</label>
                        <input
                          value={(form[field] as string) || ""}
                          onChange={(e) => updateField(field, e.target.value)}
                          readOnly={isReadonly}
                          className={`bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full ${isReadonly ? "opacity-60 cursor-not-allowed" : ""}`}
                        />
                      </div>
                    ))}
                    <div>
                      <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Canal</label>
                      <select
                        value={form.channel || ""}
                        onChange={(e) => updateField("channel", e.target.value)}
                        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                      >
                        {LEAD_CHANNELS.map((c) => (
                          <option key={c.key} value={c.key}>{c.label}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>

                {/* Empresa B2B */}
                <div>
                  <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Empresa (B2B)</p>
                  <div className="space-y-3">
                    {([
                      { label: "Razao Social", field: "razao_social" },
                      { label: "Nome Fantasia", field: "nome_fantasia" },
                      { label: "CNPJ", field: "cnpj" },
                      { label: "Telefone Comercial", field: "telefone_comercial" },
                      { label: "Endereco", field: "endereco" },
                    ] as const).map(({ label, field }) => (
                      <div key={field}>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">{label}</label>
                        <input
                          value={(form[field] as string) || ""}
                          onChange={(e) => updateField(field, e.target.value)}
                          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* CRM Status row */}
              <div className="mt-5 pt-4 border-t border-[#dedbd6]">
                <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Status no CRM</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] p-3">
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Stage (IA)</label>
                    <select
                      value={form.stage}
                      onChange={(e) => updateField("stage", e.target.value)}
                      className="w-full text-[13px] font-medium text-[#111111] bg-transparent outline-none cursor-pointer"
                    >
                      {AGENT_STAGES.map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] p-3">
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Atribuido a</label>
                    <input
                      value={(form.assigned_to as string) || ""}
                      onChange={(e) => updateField("assigned_to", e.target.value)}
                      placeholder="Ninguem"
                      className="w-full text-[13px] font-medium text-[#111111] bg-transparent outline-none placeholder:text-[#7b7b78]"
                    />
                  </div>
                </div>
              </div>

              <div className="mt-5 pt-4 border-t border-[#dedbd6]">
                <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
                  Oportunidades ({leadDeals.length})
                </p>
                {leadDeals.length === 0 && (
                  <p className="text-[13px] text-[#7b7b78]">Nenhuma oportunidade vinculada.</p>
                )}
                <div className="space-y-2">
                  {leadDeals.map((deal) => {
                    const stageInfo = DEAL_STAGES.find((s) => s.key === deal.stage);
                    return (
                      <div key={deal.id} className="flex items-center justify-between bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] p-3">
                        <div>
                          <p className="text-[13px] font-medium text-[#111111]">{deal.title}</p>
                          <span
                            className="text-[10px] font-medium px-2 py-0.5 rounded-[4px]"
                            style={{ backgroundColor: (stageInfo?.dotColor || "#7b7b78") + "22", color: stageInfo?.dotColor || "#7b7b78" }}
                          >
                            {stageInfo?.label || deal.stage}
                          </span>
                        </div>
                        <span className="text-[14px] font-semibold text-[#0bdf50]">
                          {deal.value > 0 ? `R$ ${deal.value.toLocaleString("pt-BR")}` : "\u2014"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {dirty && (
                <div className="mt-4 flex justify-end">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
                  >
                    {saving ? "Salvando..." : "Salvar alteracoes"}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* TAB: Campanhas */}
          {activeTab === "campanhas" && (
            <div>
              <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-4">
                Campanhas participadas ({enrollments.length})
              </p>
              {enrollments.length === 0 && (
                <p className="text-[13px] text-[#7b7b78] text-center py-8">Nenhuma campanha encontrada.</p>
              )}
              <div className="space-y-3">
                {enrollments.map((c, i) => {
                  const statusColors: Record<string, { bg: string; text: string }> = {
                    active: { bg: "#fef3c7", text: "#d97706" },
                    completed: { bg: "#d1fae5", text: "#059669" },
                    failed: { bg: "#fee2e2", text: "#c41c1c" },
                    paused: { bg: "#faf9f6", text: "#7b7b78" },
                  };
                  const statusLabels: Record<string, string> = {
                    active: "Ativa", completed: "Concluída", failed: "Falhou", paused: "Pausada",
                  };
                  const sc = statusColors[c.status] || statusColors.active;
                  return (
                    <div key={i} className="border border-[#dedbd6] rounded-[8px] p-4">
                      <div className="flex justify-between items-center mb-2.5">
                        <div>
                          <p className="text-[14px] font-medium text-[#111111]">{c.campaign_name}</p>
                          <p className="text-[12px] text-[#7b7b78]">
                            Criada em {new Date(c.campaign_created_at).toLocaleDateString("pt-BR")}
                          </p>
                        </div>
                        <span
                          className="text-[11px] font-semibold px-2.5 py-0.5 rounded-[4px]"
                          style={{ background: sc.bg, color: sc.text }}
                        >
                          {statusLabels[c.status] || c.status}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2.5">
                        <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                          <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">Inscrito em</p>
                          <p className="text-[13px] font-medium text-[#111111]">
                            {new Date(c.enrolled_at).toLocaleDateString("pt-BR")}
                          </p>
                        </div>
                        <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2">
                          <p className="text-[10px] text-[#7b7b78] uppercase tracking-[0.6px]">
                            {c.completed_at ? "Concluído em" : "Próxima execução"}
                          </p>
                          <p className="text-[13px] font-medium text-[#111111]">
                            {c.completed_at
                              ? new Date(c.completed_at).toLocaleDateString("pt-BR")
                              : c.next_execute_at
                                ? new Date(c.next_execute_at).toLocaleDateString("pt-BR")
                                : "—"}
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Disparos */}
              <div className="mt-6">
                <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">
                  Disparos Recebidos
                </p>
                <LeadBroadcastHistory leadId={lead.id} />
              </div>
            </div>
          )}

          {/* TAB: Tags & Notas */}
          {activeTab === "tags_notas" && (
            <div>
              <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Tags</p>
              <div className="flex gap-2 flex-wrap mb-3">
                {activeTags.map((tag) => (
                  <span
                    key={tag.id}
                    className="px-3 py-1 rounded-[4px] text-[12px] flex items-center gap-1.5 border"
                    style={{ borderColor: tag.color + "44", background: tag.color + "15", color: tag.color }}
                  >
                    {tag.name}
                    <button onClick={() => handleToggleTag(tag.id)} className="opacity-60 hover:opacity-100">×</button>
                  </span>
                ))}
                <div className="relative">
                  <button
                    onClick={() => setShowTagDropdown(!showTagDropdown)}
                    className="bg-transparent text-[#111111] border border-[#111111] px-3 py-1 rounded-[4px] text-[12px] transition-transform hover:scale-110 active:scale-[0.85]"
                  >
                    + Adicionar tag
                  </button>
                  {showTagDropdown && availableTags.length > 0 && (
                    <div className="absolute top-full left-0 mt-1 bg-white border border-[#dedbd6] rounded-[8px] z-10 py-1 min-w-[150px]">
                      {availableTags.map((tag) => (
                        <button
                          key={tag.id}
                          onClick={() => { handleToggleTag(tag.id); setShowTagDropdown(false); }}
                          className="w-full text-left px-3 py-1.5 text-[12px] hover:bg-[#faf9f6] flex items-center gap-2 transition-colors"
                        >
                          <span className="w-2.5 h-2.5 rounded-full" style={{ background: tag.color }} />
                          {tag.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mt-5 mb-3">Notas & Timeline</p>
              <div className="flex gap-2 mb-4">
                <input
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
                  placeholder="Adicionar uma nota..."
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
                />
                <button
                  onClick={handleAddNote}
                  className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
                >
                  Salvar
                </button>
              </div>

              <div className="space-y-2.5">
                {timeline.map((item) => (
                  <div
                    key={`${item.type}-${item.data.id}`}
                    className={`rounded-[8px] p-3.5 border ${
                      item.type === "note"
                        ? "border-[#dedbd6] bg-white"
                        : "border-[#dedbd6] bg-[#faf9f6]"
                    }`}
                  >
                    <div className="flex justify-between mb-1">
                      <p className="text-[12px] font-medium text-[#111111]">
                        {item.type === "note" ? (item.data as LeadNote).author : "Sistema"}
                      </p>
                      <p className="text-[11px] text-[#7b7b78]">
                        {new Date(item.date).toLocaleString("pt-BR", {
                          day: "2-digit", month: "2-digit", year: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </p>
                    </div>
                    <p className="text-[13px] text-[#7b7b78] leading-relaxed">
                      {item.type === "note"
                        ? (item.data as LeadNote).content
                        : formatEventText(item.data as LeadEvent)}
                    </p>
                  </div>
                ))}
                {timeline.length === 0 && (
                  <p className="text-[13px] text-[#7b7b78] text-center py-4">Nenhuma nota ou evento ainda.</p>
                )}
              </div>
            </div>
          )}

          {/* TAB: Metricas */}
          {activeTab === "metricas" && (
            <div>
              <div className="grid grid-cols-2 gap-3 mb-5">
                <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 text-center">
                  <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Temperatura</p>
                  <p className="text-[14px] font-semibold mt-2" style={{ color: tempConfig.color }}>
                    {tempConfig.label}
                  </p>
                  <p className="text-[11px] text-[#7b7b78] mt-0.5">
                    Ultima msg: {lead.last_msg_at ? new Date(lead.last_msg_at).toLocaleDateString("pt-BR") : "Nunca"}
                  </p>
                </div>
                <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 text-center">
                  <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">1a Resposta</p>
                  <p className="text-[24px] font-semibold text-[#111111] mt-1">{firstResponseStr}</p>
                </div>
              </div>

              <p className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-3">Engajamento</p>
              <div className="grid grid-cols-3 gap-2.5">
                <div className="border border-[#dedbd6] rounded-[8px] p-3 text-center">
                  <p className="text-[20px] font-semibold text-[#111111]">{enrollments.length}</p>
                  <p className="text-[11px] text-[#7b7b78] mt-1">Cadências</p>
                </div>
                <div className="border border-[#dedbd6] rounded-[8px] p-3 text-center">
                  <p className="text-[20px] font-semibold text-[#111111]">{daysInCrm}d</p>
                  <p className="text-[11px] text-[#7b7b78] mt-1">No CRM</p>
                </div>
                <div className="border border-[#dedbd6] rounded-[8px] p-3 text-center">
                  <p className="text-[20px] font-semibold text-[#111111]">
                    {lead.entered_stage_at
                      ? `${Math.floor((Date.now() - new Date(lead.entered_stage_at).getTime()) / (1000 * 60 * 60 * 24))}d`
                      : "\u2014"}
                  </p>
                  <p className="text-[11px] text-[#7b7b78] mt-1">No stage atual</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

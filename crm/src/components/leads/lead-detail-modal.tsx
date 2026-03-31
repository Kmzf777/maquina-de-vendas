"use client";

import { useState, useEffect } from "react";
import type { Lead, Tag, LeadNote, LeadEvent } from "@/lib/types";
import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import { AGENT_STAGES, SELLER_STAGES, LEAD_CHANNELS } from "@/lib/constants";

interface LeadDetailModalProps {
  lead: Lead;
  tags: Tag[];
  leadTagIds: string[];
  onClose: () => void;
  onSave: (leadId: string, data: Partial<Lead>) => Promise<void>;
  onTagsChange: (leadId: string, tagIds: string[]) => Promise<void>;
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
}: LeadDetailModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>("dados");
  const [form, setForm] = useState({ ...lead });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState<LeadNote[]>([]);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [newNote, setNewNote] = useState("");
  const [campaigns, setCampaigns] = useState<Array<{
    campaign_name: string;
    campaign_created_at: string;
    status: string;
    current_step: number;
    max_messages: number;
    total_messages_sent: number;
    next_send_at: string | null;
    responded_at: string | null;
  }>>([]);
  const [currentTagIds, setCurrentTagIds] = useState<string[]>(leadTagIds);
  const [showTagDropdown, setShowTagDropdown] = useState(false);

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
      import("@/lib/supabase/client").then(({ createClient }) => {
        const supabase = createClient();
        supabase
          .from("cadence_state")
          .select("*, campaigns(name, created_at)")
          .eq("lead_id", lead.id)
          .then(({ data }) => {
            if (data) {
              setCampaigns(
                data.map((cs: Record<string, unknown>) => {
                  const camp = cs.campaigns as { name: string; created_at: string } | null;
                  return {
                    campaign_name: camp?.name || "Campanha",
                    campaign_created_at: camp?.created_at || "",
                    status: cs.status as string,
                    current_step: cs.current_step as number,
                    max_messages: cs.max_messages as number,
                    total_messages_sent: cs.total_messages_sent as number,
                    next_send_at: cs.next_send_at as string | null,
                    responded_at: cs.responded_at as string | null,
                  };
                })
              );
            }
          });
      });
    }
  }, [activeTab, lead.id]);

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
      case "seller_stage_change":
        return `Etapa vendas alterada de ${event.old_value} para ${event.new_value}`;
      case "campaign_added":
        return `Adicionado a campanha ${event.new_value}`;
      case "campaign_removed":
        return `Removido de campanha ${event.new_value}`;
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
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl w-full max-w-[720px] overflow-hidden shadow-[0_25px_50px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-5 border-b border-[#f3f3f0] flex justify-between items-center">
          <div className="flex items-center gap-3.5">
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center font-bold text-base"
              style={{ background: "#c8cc8e", color: "#1f1f1f" }}
            >
              {initials}
            </div>
            <div>
              <h3 className="text-[18px] font-semibold text-[#1f1f1f]">
                {lead.name || lead.phone}
              </h3>
              <p className="text-[13px] text-[#9ca3af]">
                {lead.phone}{lead.company ? ` \u00b7 ${lead.company}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2.5">
            <span
              className="text-[10px] font-semibold px-2.5 py-1 rounded-xl"
              style={{ background: tempConfig.bg, color: tempConfig.color }}
            >
              {tempConfig.label.toUpperCase()}
            </span>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg border border-[#e5e5dc] bg-white flex items-center justify-center text-[#9ca3af] hover:text-[#1f1f1f] transition-colors"
            >
              x
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#f3f3f0] px-6">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-3 text-[13px] font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "text-[#1f1f1f] border-[#1f1f1f]"
                  : "text-[#9ca3af] border-transparent hover:text-[#5f6368]"
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
                  <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Contato</p>
                  <div className="space-y-3">
                    {([
                      { label: "Nome", field: "name", type: "text" },
                      { label: "Telefone", field: "phone", type: "text", readonly: true },
                      { label: "Email", field: "email", type: "text" },
                      { label: "Instagram", field: "instagram", type: "text" },
                    ] as const).map(({ label, field, readonly }) => (
                      <div key={field}>
                        <label className="text-[11px] text-[#b0b0b0] block mb-0.5">{label}</label>
                        <input
                          value={(form[field] as string) || ""}
                          onChange={(e) => updateField(field, e.target.value)}
                          readOnly={readonly}
                          className={`w-full text-[14px] text-[#1f1f1f] px-2.5 py-1.5 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors ${readonly ? "bg-[#f6f7ed] text-[#9ca3af]" : ""}`}
                        />
                      </div>
                    ))}
                    <div>
                      <label className="text-[11px] text-[#b0b0b0] block mb-0.5">Canal</label>
                      <select
                        value={form.channel || ""}
                        onChange={(e) => updateField("channel", e.target.value)}
                        className="w-full text-[14px] text-[#1f1f1f] px-2.5 py-1.5 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] bg-white"
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
                  <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Empresa (B2B)</p>
                  <div className="space-y-3">
                    {([
                      { label: "Razao Social", field: "razao_social" },
                      { label: "Nome Fantasia", field: "nome_fantasia" },
                      { label: "CNPJ", field: "cnpj" },
                      { label: "Telefone Comercial", field: "telefone_comercial" },
                      { label: "Endereco", field: "endereco" },
                    ] as const).map(({ label, field }) => (
                      <div key={field}>
                        <label className="text-[11px] text-[#b0b0b0] block mb-0.5">{label}</label>
                        <input
                          value={(form[field] as string) || ""}
                          onChange={(e) => updateField(field, e.target.value)}
                          className="w-full text-[14px] text-[#1f1f1f] px-2.5 py-1.5 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] transition-colors"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* CRM Status row */}
              <div className="mt-5 pt-4 border-t border-[#f3f3f0]">
                <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Status no CRM</p>
                <div className="grid grid-cols-4 gap-3">
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Stage (IA)</label>
                    <select
                      value={form.stage}
                      onChange={(e) => updateField("stage", e.target.value)}
                      className="w-full text-[13px] font-semibold text-[#1f1f1f] bg-transparent outline-none cursor-pointer"
                    >
                      {AGENT_STAGES.map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Etapa Vendas</label>
                    <select
                      value={form.seller_stage}
                      onChange={(e) => updateField("seller_stage", e.target.value)}
                      className="w-full text-[13px] font-semibold text-[#1f1f1f] bg-transparent outline-none cursor-pointer"
                    >
                      {SELLER_STAGES.map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Atribuido a</label>
                    <input
                      value={(form.assigned_to as string) || ""}
                      onChange={(e) => updateField("assigned_to", e.target.value)}
                      placeholder="Ninguem"
                      className="w-full text-[13px] font-semibold text-[#1f1f1f] bg-transparent outline-none"
                    />
                  </div>
                  <div className="bg-[#f6f7ed] rounded-lg p-3">
                    <label className="text-[11px] text-[#b0b0b0] block mb-1">Valor de Venda</label>
                    <input
                      value={form.sale_value || ""}
                      onChange={(e) => updateField("sale_value", Number(e.target.value) || 0)}
                      type="number"
                      placeholder="0"
                      className="w-full text-[13px] font-semibold text-[#4ade80] bg-transparent outline-none"
                    />
                  </div>
                </div>
              </div>

              {dirty && (
                <div className="mt-4 flex justify-end">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-5 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors disabled:opacity-50"
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
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-4">
                Campanhas participadas ({campaigns.length})
              </p>
              {campaigns.length === 0 && (
                <p className="text-[13px] text-[#9ca3af] text-center py-8">Nenhuma campanha encontrada.</p>
              )}
              <div className="space-y-3">
                {campaigns.map((c, i) => {
                  const statusColors: Record<string, { bg: string; text: string }> = {
                    active: { bg: "#fefce8", text: "#ca8a04" },
                    responded: { bg: "#f0fdf4", text: "#22c55e" },
                    exhausted: { bg: "#fee2e2", text: "#ef4444" },
                    cooled: { bg: "#f4f4f0", text: "#9ca3af" },
                  };
                  const statusLabels: Record<string, string> = {
                    active: "Ativa", responded: "Respondeu", exhausted: "Esgotado", cooled: "Esfriado",
                  };
                  const sc = statusColors[c.status] || statusColors.active;
                  return (
                    <div key={i} className="border border-[#e5e5dc] rounded-[10px] p-4">
                      <div className="flex justify-between items-center mb-2.5">
                        <div>
                          <p className="text-[14px] font-semibold text-[#1f1f1f]">{c.campaign_name}</p>
                          <p className="text-[12px] text-[#9ca3af]">
                            Criada em {new Date(c.campaign_created_at).toLocaleDateString("pt-BR")}
                          </p>
                        </div>
                        <span
                          className="text-[11px] font-semibold px-2.5 py-0.5 rounded-[10px]"
                          style={{ background: sc.bg, color: sc.text }}
                        >
                          {statusLabels[c.status] || c.status}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-2.5">
                        <div className="bg-[#f6f7ed] rounded-md px-3 py-2">
                          <p className="text-[10px] text-[#b0b0b0]">Cadencia</p>
                          <p className="text-[13px] font-semibold text-[#1f1f1f]">Step {c.current_step} de {c.max_messages}</p>
                        </div>
                        <div className="bg-[#f6f7ed] rounded-md px-3 py-2">
                          <p className="text-[10px] text-[#b0b0b0]">Mensagens</p>
                          <p className="text-[13px] font-semibold text-[#1f1f1f]">{c.total_messages_sent} enviadas</p>
                        </div>
                        <div className="bg-[#f6f7ed] rounded-md px-3 py-2">
                          <p className="text-[10px] text-[#b0b0b0]">
                            {c.responded_at ? "Respondeu em" : "Proximo envio"}
                          </p>
                          <p className="text-[13px] font-semibold text-[#1f1f1f]">
                            {c.responded_at
                              ? new Date(c.responded_at).toLocaleDateString("pt-BR")
                              : c.next_send_at
                                ? new Date(c.next_send_at).toLocaleDateString("pt-BR")
                                : "\u2014"}
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* TAB: Tags & Notas */}
          {activeTab === "tags_notas" && (
            <div>
              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Tags</p>
              <div className="flex gap-2 flex-wrap mb-3">
                {activeTags.map((tag) => (
                  <span
                    key={tag.id}
                    className="px-3 py-1 rounded-full text-[12px] flex items-center gap-1.5"
                    style={{ background: tag.color + "22", color: tag.color }}
                  >
                    {tag.name}
                    <button onClick={() => handleToggleTag(tag.id)} className="opacity-60 hover:opacity-100">x</button>
                  </span>
                ))}
                <div className="relative">
                  <button
                    onClick={() => setShowTagDropdown(!showTagDropdown)}
                    className="px-3 py-1 rounded-full text-[12px] border border-dashed border-[#d1d5db] text-[#9ca3af] hover:border-[#9ca3af] transition-colors"
                  >
                    + Adicionar tag
                  </button>
                  {showTagDropdown && availableTags.length > 0 && (
                    <div className="absolute top-full left-0 mt-1 bg-white border border-[#e5e5dc] rounded-lg shadow-lg z-10 py-1 min-w-[150px]">
                      {availableTags.map((tag) => (
                        <button
                          key={tag.id}
                          onClick={() => { handleToggleTag(tag.id); setShowTagDropdown(false); }}
                          className="w-full text-left px-3 py-1.5 text-[12px] hover:bg-[#f6f7ed] flex items-center gap-2"
                        >
                          <span className="w-2.5 h-2.5 rounded-full" style={{ background: tag.color }} />
                          {tag.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mt-5 mb-3">Notas & Timeline</p>
              <div className="flex gap-2 mb-4">
                <input
                  value={newNote}
                  onChange={(e) => setNewNote(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
                  placeholder="Adicionar uma nota..."
                  className="flex-1 px-3.5 py-2 rounded-lg border border-[#e5e5dc] text-[13px] outline-none focus:border-[#c8cc8e]"
                />
                <button
                  onClick={handleAddNote}
                  className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors"
                >
                  Salvar
                </button>
              </div>

              <div className="space-y-2.5">
                {timeline.map((item) => (
                  <div
                    key={`${item.type}-${item.data.id}`}
                    className={`rounded-[10px] p-3.5 border ${
                      item.type === "note"
                        ? "border-[#e5e5dc] bg-white"
                        : "border-[#f3f3f0] bg-[#f6f7ed]"
                    }`}
                  >
                    <div className="flex justify-between mb-1">
                      <p className="text-[12px] font-semibold text-[#1f1f1f]">
                        {item.type === "note" ? (item.data as LeadNote).author : "Sistema"}
                      </p>
                      <p className="text-[11px] text-[#b0b0b0]">
                        {new Date(item.date).toLocaleString("pt-BR", {
                          day: "2-digit", month: "2-digit", year: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </p>
                    </div>
                    <p className="text-[13px] text-[#5f6368] leading-relaxed">
                      {item.type === "note"
                        ? (item.data as LeadNote).content
                        : formatEventText(item.data as LeadEvent)}
                    </p>
                  </div>
                ))}
                {timeline.length === 0 && (
                  <p className="text-[13px] text-[#9ca3af] text-center py-4">Nenhuma nota ou evento ainda.</p>
                )}
              </div>
            </div>
          )}

          {/* TAB: Metricas */}
          {activeTab === "metricas" && (
            <div>
              <div className="grid grid-cols-3 gap-3 mb-5">
                <div className="bg-[#f6f7ed] rounded-[10px] p-4 text-center">
                  <p className="text-[11px] text-[#b0b0b0] uppercase">Temperatura</p>
                  <p className="text-[14px] font-bold mt-2" style={{ color: tempConfig.color }}>
                    {tempConfig.label}
                  </p>
                  <p className="text-[11px] text-[#9ca3af] mt-0.5">
                    Ultima msg: {lead.last_msg_at ? new Date(lead.last_msg_at).toLocaleDateString("pt-BR") : "Nunca"}
                  </p>
                </div>
                <div className="bg-[#f6f7ed] rounded-[10px] p-4 text-center">
                  <p className="text-[11px] text-[#b0b0b0] uppercase">Valor de Venda</p>
                  <p className="text-[24px] font-bold text-[#4ade80] mt-1">
                    {lead.sale_value ? `R$ ${lead.sale_value.toLocaleString("pt-BR")}` : "\u2014"}
                  </p>
                </div>
                <div className="bg-[#f6f7ed] rounded-[10px] p-4 text-center">
                  <p className="text-[11px] text-[#b0b0b0] uppercase">1a Resposta</p>
                  <p className="text-[24px] font-bold text-[#1f1f1f] mt-1">{firstResponseStr}</p>
                </div>
              </div>

              <p className="text-[12px] font-semibold text-[#9ca3af] uppercase tracking-wider mb-3">Engajamento</p>
              <div className="grid grid-cols-3 gap-2.5">
                <div className="border border-[#e5e5dc] rounded-lg p-3 text-center">
                  <p className="text-[20px] font-bold text-[#1f1f1f]">{campaigns.length}</p>
                  <p className="text-[11px] text-[#9ca3af] mt-1">Campanhas</p>
                </div>
                <div className="border border-[#e5e5dc] rounded-lg p-3 text-center">
                  <p className="text-[20px] font-bold text-[#1f1f1f]">{daysInCrm}d</p>
                  <p className="text-[11px] text-[#9ca3af] mt-1">No CRM</p>
                </div>
                <div className="border border-[#e5e5dc] rounded-lg p-3 text-center">
                  <p className="text-[20px] font-bold text-[#1f1f1f]">
                    {lead.entered_stage_at
                      ? `${Math.floor((Date.now() - new Date(lead.entered_stage_at).getTime()) / (1000 * 60 * 60 * 24))}d`
                      : "\u2014"}
                  </p>
                  <p className="text-[11px] text-[#9ca3af] mt-1">No stage atual</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

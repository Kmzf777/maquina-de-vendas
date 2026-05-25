"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import type { Channel, AgentProfile } from "@/lib/types";
import { TemplatePreviewCard, autoSuggestToken, type MetaTemplate } from "@/components/campaigns/template-preview-card";
import { LeadFilterPanel, type LeadFilters } from "@/components/campaigns/lead-filter-panel";
import { CreateTemplateModal } from "@/components/canais/create-template-modal";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";

interface Lead {
  id: string;
  name: string | null;
  phone: string;
  company: string | null;
  nome_fantasia: string | null;
  lead_tags?: { tag_id: string; tags: { id: string; name: string; color: string } | null }[];
}

interface MovePipeline {
  id: string;
  name: string;
}

interface MoveStage {
  id: string;
  label: string;
  dot_color: string;
}

// ─── Prefill prop ─────────────────────────────────────────────────────────────

export interface BroadcastPrefill {
  channelId?: string;
  templateName?: string;
  templateLanguage?: string;
  varValues?: Record<string, string>;
  leadIds?: string[];
}

// ─── Step labels ──────────────────────────────────────────────────────────────

const STEPS = ["Configuração", "Template", "Leads", "Ação", "Agendamento", "Revisão"] as const;

// ─── Props ────────────────────────────────────────────────────────────────────

interface CreateBroadcastModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  prefill?: BroadcastPrefill;
}

// ─── Agent mode ───────────────────────────────────────────────────────────────

type AgentMode = "none" | "channel_default" | "specific";

// =============================================================================
// Component
// =============================================================================

export function CreateBroadcastModal({
  open,
  onClose,
  onCreated,
  prefill,
}: CreateBroadcastModalProps) {
  // ── Step ──────────────────────────────────────────────────────────────────
  const [step, setStep] = useState(1);

  // ── Global data ───────────────────────────────────────────────────────────
  const [channels, setChannels] = useState<Channel[]>([]);
  const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);

  // ── Step 1: Configuration ─────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [channelId, setChannelId] = useState("");
  const [agentMode, setAgentMode] = useState<AgentMode>("none");
  const [specificAgentId, setSpecificAgentId] = useState("");

  // ── Step 2: Template ──────────────────────────────────────────────────────
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateSearch, setTemplateSearch] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [templateVarValues, setTemplateVarValues] = useState<Record<string, string>>({});
  const [showCreateTemplate, setShowCreateTemplate] = useState(false);

  // ── Step 3: Leads ─────────────────────────────────────────────────────────
  const [leadTab, setLeadTab] = useState<"crm" | "csv">("crm");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [leadsError, setLeadsError] = useState<string | null>(null);
  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const [lastCheckedIndex, setLastCheckedIndex] = useState<number | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);

  // ── Step 4: Post-dispatch action ──────────────────────────────────────────
  const [moveAction, setMoveAction] = useState<"none" | "move">("none");
  const [movePipelineId, setMovePipelineId] = useState("");
  const [moveStageId, setMoveStageId] = useState("");
  const [movePipelines, setMovePipelines] = useState<MovePipeline[]>([]);
  const [moveStages, setMoveStages] = useState<MoveStage[]>([]);
  const [loadingMovePipelines, setLoadingMovePipelines] = useState(false);
  const [loadingMoveStages, setLoadingMoveStages] = useState(false);

  // ── Step 5: Scheduling ────────────────────────────────────────────────────
  const [scheduleMode, setScheduleMode] = useState<"immediate" | "scheduled">("immediate");
  const [scheduleDate, setScheduleDate] = useState(""); // YYYY-MM-DD
  const [scheduleTime, setScheduleTime] = useState(""); // HH:MM

  // ── Saving ────────────────────────────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [createdBroadcastId, setCreatedBroadcastId] = useState<string | null>(null);
  const [showStartDialog, setShowStartDialog] = useState(false);
  const [starting, setStarting] = useState(false);
  const router = useRouter();

  const brtToUtcIso = (date: string, time: string): string => {
    const [year, month, day] = date.split("-").map(Number);
    const [hour, minute] = time.split(":").map(Number);
    // BRT = UTC-3, adiciona 3h para obter UTC
    return new Date(Date.UTC(year, month - 1, day, hour + 3, minute)).toISOString();
  };

  const scheduleIsValid = (): boolean => {
    if (scheduleMode === "immediate") return true;
    if (!scheduleDate || !scheduleTime) return false;
    const utcIso = brtToUtcIso(scheduleDate, scheduleTime);
    return new Date(utcIso) > new Date();
  };

  const selectedChannel = channels.find((c) => c.id === channelId);

  // ─── Reset ────────────────────────────────────────────────────────────────
  const resetForm = useCallback(() => {
    setStep(1);
    setName("");
    setChannelId("");
    setAgentMode("none");
    setSpecificAgentId("");
    setTemplates([]);
    setTemplateSearch("");
    setSelectedTemplate(null);
    setTemplateVarValues({});
    setLeadTab("crm");
    setLeads([]);
    setSelectedLeadIds(new Set());
    setLastCheckedIndex(null);
    setCsvFile(null);
    setMoveAction("none");
    setMovePipelineId("");
    setMoveStageId("");
    setMovePipelines([]);
    setMoveStages([]);
    setScheduleMode("immediate");
    setScheduleDate("");
    setScheduleTime("");
    setCreatedBroadcastId(null);
    setShowStartDialog(false);
    setStarting(false);
  }, []);

  // ─── Load channels + agent profiles on open ─────────────────────────────
  useEffect(() => {
    if (!open) return;
    fetch("/api/channels")
      .then((r) => r.json())
      .then((d) => {
        const meta = (Array.isArray(d) ? d : d.data ?? []).filter(
          (c: Channel) => c.provider === "meta_cloud" && c.is_active
        );
        setChannels(meta);
      })
      .catch(() => setChannels([]));

    fetch("/api/agent-profiles")
      .then((r) => r.json())
      .then((d) => setAgentProfiles(Array.isArray(d) ? d : d.data ?? []))
      .catch(() => setAgentProfiles([]));
  }, [open]);

  // ─── Apply prefill when modal opens ─────────────────────────────────────
  useEffect(() => {
    if (!open || !prefill) return;
    if (prefill.channelId) setChannelId(prefill.channelId);
    if (prefill.leadIds) setSelectedLeadIds(new Set(prefill.leadIds));
    // Jump to step 3 (Leads) for retry flow
    setStep(3);
  }, [open, prefill]);

  // ─── Load templates when channel changes ─────────────────────────────────
  useEffect(() => {
    if (!channelId) {
      setTemplates([]);
      setSelectedTemplate(null);
      return;
    }
    setLoadingTemplates(true);
    setSelectedTemplate(null);
    setTemplateVarValues({});
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false));
  }, [channelId]);

  // ─── After templates load, apply prefill template selection ──────────────
  useEffect(() => {
    if (!prefill?.templateName || templates.length === 0) return;
    const tpl = templates.find(
      (t) => t.name === prefill.templateName && t.language === prefill.templateLanguage
    );
    if (tpl) {
      setSelectedTemplate(tpl);
      const defaults: Record<string, string> = {};
      if (tpl.paramsType !== "none") defaults["__params_type__"] = tpl.paramsType;
      if (tpl.header) defaults["__header_type__"] = tpl.header.type;
      tpl.params.forEach((p) => {
        defaults[p.paramName] =
          prefill.varValues?.[p.paramName] ?? autoSuggestToken(p.example);
      });
      if (prefill.varValues?.["__header_url__"]) {
        defaults["__header_url__"] = prefill.varValues["__header_url__"];
      }
      setTemplateVarValues(defaults);
    }
  }, [prefill, templates]);

  // ESC fecha o modal
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); resetForm(); }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose, resetForm]);

  // Resetar agente quando canal muda para human
  useEffect(() => {
    if (selectedChannel?.mode === "human") {
      setAgentMode("none");
      setSpecificAgentId("");
    }
  }, [channelId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Reload templates after creating a new one ───────────────────────────
  const handleTemplateCreated = useCallback(() => {
    setShowCreateTemplate(false);
    if (!channelId) return;
    setLoadingTemplates(true);
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false));
  }, [channelId]);

  // ─── Select template ──────────────────────────────────────────────────────
  const handleSelectTemplate = (key: string) => {
    if (!key) {
      setSelectedTemplate(null);
      setTemplateVarValues({});
      return;
    }
    const [tname, lang] = key.split("|");
    const tpl = templates.find((t) => t.name === tname && t.language === lang) ?? null;
    setSelectedTemplate(tpl);
    if (tpl) {
      const defaults: Record<string, string> = {};
      if (tpl.paramsType !== "none") defaults["__params_type__"] = tpl.paramsType;
      if (tpl.header) defaults["__header_type__"] = tpl.header.type;
      tpl.params.forEach((p) => {
        defaults[p.paramName] = autoSuggestToken(p.example);
      });
      setTemplateVarValues(defaults);
    } else {
      setTemplateVarValues({});
    }
  };

  // ─── Load leads from CRM ──────────────────────────────────────────────────
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleApplyLeadFilters = useCallback(async (filters: LeadFilters) => {
    // Cancel any in-flight request so stale results never overwrite newer ones
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoadingLeads(true);
    setLeadsError(null);
    setSelectedLeadIds(new Set());

    try {
      const params = new URLSearchParams();
      if (filters.pipelineId) params.set("pipeline_id", filters.pipelineId);
      if (filters.stageId) params.set("stage_id", filters.stageId);
      if (filters.dealCategory) params.set("deal_category", filters.dealCategory);
      if (filters.noDeal) params.set("no_deal", "true");
      if (filters.createdAfter) params.set("created_after", filters.createdAfter);
      if (filters.createdBefore) params.set("created_before", filters.createdBefore);

      const url = `/api/leads?${params.toString()}`;
      const res = await fetch(url, { signal: controller.signal });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        setLeadsError(errBody.error ?? `Erro ${res.status} ao buscar leads.`);
        setLeads([]);
        setLoadingLeads(false);
        return;
      }

      const data = await res.json();
      let result: Lead[] = Array.isArray(data) ? data : [];

      // Client-side filter: search and tags
      if (filters.search) {
        const q = filters.search.toLowerCase();
        result = result.filter(
          (l) =>
            l.name?.toLowerCase().includes(q) ||
            l.phone.includes(q) ||
            l.company?.toLowerCase().includes(q) ||
            l.nome_fantasia?.toLowerCase().includes(q)
        );
      }
      if (filters.tagIds.length > 0) {
        result = result.filter((l) =>
          l.lead_tags?.some((lt) => filters.tagIds.includes(lt.tag_id))
        );
      }

      setLeads(result);
      setLoadingLeads(false);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return; // Newer request is in flight — don't touch state
      }
      setLeads([]);
      setLeadsError("Erro ao buscar leads. Tente novamente.");
      setLoadingLeads(false);
    }
  }, []);

  // Load leads on step 3 mount (initial empty filter)
  useEffect(() => {
    if (step === 3 && leadTab === "crm" && leads.length === 0 && !loadingLeads) {
      handleApplyLeadFilters({
        pipelineId: "",
        stageId: "",
        dealCategory: "",
        tagIds: [],
        noDeal: false,
        createdAfter: "",
        createdBefore: "",
        search: "",
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, leadTab]);

  // Load pipelines when entering step 4
  useEffect(() => {
    if (step !== 4 || movePipelines.length > 0) return;
    setLoadingMovePipelines(true);
    fetch("/api/pipelines")
      .then((r) => r.json())
      .then((d) => setMovePipelines(Array.isArray(d) ? d : []))
      .catch(() => setMovePipelines([]))
      .finally(() => setLoadingMovePipelines(false));
  }, [step, movePipelines.length]);

  // Load stages when a pipeline is selected in step 4
  useEffect(() => {
    if (!movePipelineId) {
      setMoveStages([]);
      setMoveStageId("");
      return;
    }
    setLoadingMoveStages(true);
    fetch(`/api/pipelines/${movePipelineId}/stages`)
      .then((r) => r.json())
      .then((d) => setMoveStages(Array.isArray(d) ? d : []))
      .catch(() => setMoveStages([]))
      .finally(() => setLoadingMoveStages(false));
  }, [movePipelineId]);

  // ─── Select/deselect lead ─────────────────────────────────────────────────
  const toggleLead = (id: string, idx: number, shiftKey: boolean) => {
    if (shiftKey && lastCheckedIndex !== null) {
      const from = Math.min(lastCheckedIndex, idx);
      const to = Math.max(lastCheckedIndex, idx);
      const rangeIds = leads.slice(from, to + 1).map((l) => l.id);
      const selecting = !selectedLeadIds.has(id);
      setSelectedLeadIds((prev) => {
        const next = new Set(prev);
        rangeIds.forEach((rid) => (selecting ? next.add(rid) : next.delete(rid)));
        return next;
      });
    } else {
      setSelectedLeadIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        return next;
      });
    }
    setLastCheckedIndex(idx);
  };

  const selectAllLeads = () => {
    setSelectedLeadIds(new Set(leads.map((l) => l.id)));
    setLastCheckedIndex(null);
  };

  const deselectAllLeads = () => {
    setSelectedLeadIds(new Set());
    setLastCheckedIndex(null);
  };

  // ─── Create broadcast ─────────────────────────────────────────────────────
  const handleCreate = async () => {
    if (!selectedTemplate) return;
    // Guard: se agendado, verificar que ainda está no futuro
    if (scheduleMode === "scheduled" && !scheduleIsValid()) {
      setStep(5);
      return;
    }
    setSaving(true);
    try {
      const agentProfileId =
        agentMode === "specific" ? specificAgentId :
        agentMode === "channel_default" ? (channels.find((c) => c.id === channelId)?.agent_profile_id ?? null) :
        null;

      const res = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          channel_id: channelId || null,
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: Object.keys(templateVarValues).length ? templateVarValues : null,
          agent_profile_id: agentProfileId || null,
          move_to_stage_id: moveAction === "move" && moveStageId ? moveStageId : null,
          scheduled_at:
            scheduleMode === "scheduled" && scheduleDate && scheduleTime
              ? brtToUtcIso(scheduleDate, scheduleTime)
              : null,
        }),
      });
      const broadcast = await res.json();

      if (leadTab === "crm" && selectedLeadIds.size > 0) {
        await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lead_ids: [...selectedLeadIds] }),
        });
      } else if (leadTab === "csv" && csvFile) {
        const formData = new FormData();
        formData.append("file", csvFile);
        const fastApiUrl = process.env.NEXT_PUBLIC_FASTAPI_URL ?? "http://localhost:8000";
        await fetch(`${fastApiUrl}/api/broadcasts/${broadcast.id}/import`, {
          method: "POST",
          body: formData,
        });
      }

      if (scheduleMode === "immediate") {
        setCreatedBroadcastId(broadcast.id);
        setShowStartDialog(true);
      } else {
        onCreated();
        onClose();
        resetForm();
      }
    } finally {
      setSaving(false);
    }
  };

  const handleStartNow = async () => {
    if (!createdBroadcastId) return;
    setStarting(true);
    try {
      await fetch(`/api/broadcasts/${createdBroadcastId}/start`, { method: "POST" });
    } finally {
      setStarting(false);
      setShowStartDialog(false);
      onCreated();
      onClose();
      resetForm();
      router.push(`/campanhas/disparos/${createdBroadcastId}`);
    }
  };

  const handleCancelStart = () => {
    setShowStartDialog(false);
    onCreated();
    onClose();
    resetForm();
  };

  // ─── Step advancement guards ──────────────────────────────────────────────
  const canGoToStep2 = name.trim() !== "" && channelId !== "";
  const canGoToStep3 =
    selectedTemplate !== null &&
    selectedTemplate.params.every(
      (p) => (templateVarValues[p.paramName] ?? "").trim() !== ""
    ) &&
    (
      !selectedTemplate.header ||
      selectedTemplate.header.type === "TEXT" ||
      (templateVarValues["__header_url__"] ?? "").trim() !== ""
    );
  const canGoToStep4 = leadTab === "crm" ? selectedLeadIds.size > 0 : csvFile !== null;
  const canGoToStep5 =
    moveAction === "none" || (moveAction === "move" && moveStageId !== "");
  const canGoToStep6 = scheduleIsValid();

  const canAdvance =
    step === 1 ? canGoToStep2 :
    step === 2 ? canGoToStep3 :
    step === 3 ? canGoToStep4 :
    step === 4 ? canGoToStep5 :
    step === 5 ? canGoToStep6 :
    true;

  // ─── Filtered templates ───────────────────────────────────────────────────
  const filteredTemplates = templates.filter((t) =>
    templateSearch === "" ||
    t.name.toLowerCase().includes(templateSearch.toLowerCase())
  );

  // ─── Resolved agent profile id for review summary ─────────────────────────
  const resolvedAgentName =
    agentMode === "none" ? "Sem agente" :
    agentMode === "channel_default"
      ? (channels.find((c) => c.id === channelId)?.agent_profiles?.name ?? "Agente padrão do canal")
      : (agentProfiles.find((a) => a.id === specificAgentId)?.name ?? "—");

  if (!open) return null;

  // ==========================================================================
  // Render
  // ==========================================================================
  return (
    <>
      {/* ── Main wizard modal ── */}
      <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
        <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-2xl flex flex-col max-h-[90vh]">

          {/* ── Header ── */}
          <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between flex-shrink-0">
            <h2 className="text-[14px] font-normal text-[#111111]">Novo Disparo</h2>
            <button
              onClick={() => { onClose(); resetForm(); }}
              className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors leading-none"
            >
              &times;
            </button>
          </div>

          {/* ── Progress bar ── */}
          <div className="px-6 pt-4 flex-shrink-0">
            <div className="flex items-center gap-0">
              {STEPS.map((label, i) => {
                const stepNum = i + 1;
                const isCompleted = step > stepNum;
                const isCurrent = step === stepNum;
                return (
                  <div key={label} className="flex items-center flex-1 last:flex-none">
                    <div className="flex flex-col items-center gap-1">
                      <div
                        className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-medium transition-colors ${
                          isCompleted
                            ? "bg-[#111111] text-white"
                            : isCurrent
                            ? "bg-[#111111] text-white"
                            : "bg-[#dedbd6] text-[#7b7b78]"
                        }`}
                      >
                        {isCompleted ? "✓" : stepNum}
                      </div>
                      <span
                        className={`text-[10px] uppercase tracking-[0.5px] whitespace-nowrap ${
                          isCurrent ? "text-[#111111]" : "text-[#7b7b78]"
                        }`}
                      >
                        {label}
                      </span>
                    </div>
                    {i < STEPS.length - 1 && (
                      <div
                        className={`flex-1 h-[1px] mb-4 mx-1 transition-colors ${
                          step > stepNum ? "bg-[#111111]" : "bg-[#dedbd6]"
                        }`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Body (scrollable) ── */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">

            {/* ════════════════════════════════════════════════════════════════
                STEP 1 — Configuração
            ════════════════════════════════════════════════════════════════ */}
            {step === 1 && (
              <>
                {/* Name */}
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                    Nome do disparo <span className="text-[#c41c1c]">*</span>
                  </label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Ex: Promo Black Friday"
                    className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none"
                  />
                </div>

                {/* Channel */}
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                    Canal (Meta Cloud) <span className="text-[#c41c1c]">*</span>
                  </label>
                  <select
                    value={channelId}
                    onChange={(e) => setChannelId(e.target.value)}
                    className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                  >
                    <option value="">Selecionar canal...</option>
                    {channels.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.phone})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Agent */}
                {selectedChannel?.mode !== "human" && (
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                      Agente
                    </label>
                    <div className="space-y-2">
                      {(
                        [
                          { value: "none", label: "Sem agente" },
                          { value: "channel_default", label: "Agente padrão do canal" },
                          { value: "specific", label: "Escolher agente específico" },
                        ] as { value: AgentMode; label: string }[]
                      ).map(({ value, label }) => (
                        <label key={value} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="radio"
                            name="agent-mode"
                            value={value}
                            checked={agentMode === value}
                            onChange={() => setAgentMode(value)}
                            className="accent-[#111111]"
                          />
                          <span className="text-[14px] text-[#111111]">{label}</span>
                        </label>
                      ))}
                    </div>

                    {agentMode === "specific" && (
                      <select
                        value={specificAgentId}
                        onChange={(e) => setSpecificAgentId(e.target.value)}
                        className="mt-2 w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                      >
                        <option value="">Selecionar agente...</option>
                        {agentProfiles.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                )}

              </>
            )}

            {/* ════════════════════════════════════════════════════════════════
                STEP 2 — Template
            ════════════════════════════════════════════════════════════════ */}
            {step === 2 && (
              <>
                {/* Search + select */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                      Template{" "}
                      {loadingTemplates && (
                        <span className="normal-case font-normal text-[#7b7b78]">carregando...</span>
                      )}
                    </label>
                    <button
                      type="button"
                      onClick={() => setShowCreateTemplate(true)}
                      className="text-[12px] text-[#111111] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-white hover:border-[#111111] transition-colors"
                    >
                      + Novo template
                    </button>
                  </div>

                  {!channelId ? (
                    <p className="text-[12px] text-[#7b7b78] italic">
                      Nenhum canal selecionado.
                    </p>
                  ) : loadingTemplates ? (
                    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#7b7b78]">
                      Buscando templates...
                    </div>
                  ) : templates.length === 0 ? (
                    <p className="text-[12px] text-[#c41c1c]">
                      Nenhum template aprovado encontrado para este canal.
                    </p>
                  ) : (
                    <>
                      <input
                        value={templateSearch}
                        onChange={(e) => setTemplateSearch(e.target.value)}
                        placeholder="Buscar template..."
                        className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#b0aca6] focus:border-[#111111] focus:outline-none mb-2"
                      />
                      <select
                        value={
                          selectedTemplate
                            ? `${selectedTemplate.name}|${selectedTemplate.language}`
                            : ""
                        }
                        onChange={(e) => handleSelectTemplate(e.target.value)}
                        size={Math.min(filteredTemplates.length + 1, 6)}
                        className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-1 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                      >
                        <option value="">— Selecionar template —</option>
                        {filteredTemplates.map((t) => (
                          <option key={`${t.name}|${t.language}`} value={`${t.name}|${t.language}`}>
                            {t.name} ({t.language})
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                </div>

                {/* Preview card */}
                {selectedTemplate && (
                  <TemplatePreviewCard
                    template={selectedTemplate}
                    varValues={templateVarValues}
                    onVarChange={(param, value) =>
                      setTemplateVarValues((prev) => ({ ...prev, [param]: value }))
                    }
                  />
                )}
              </>
            )}

            {/* ════════════════════════════════════════════════════════════════
                STEP 3 — Leads
            ════════════════════════════════════════════════════════════════ */}
            {step === 3 && (
              <>
                {/* Tabs */}
                <div className="flex border-b border-[#dedbd6]">
                  {(["crm", "csv"] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setLeadTab(tab)}
                      className={`px-4 py-2 text-[14px] font-normal border-b-2 transition-colors ${
                        leadTab === tab
                          ? "border-[#111111] text-[#111111]"
                          : "border-transparent text-[#7b7b78] hover:text-[#111111]"
                      }`}
                    >
                      {tab === "crm" ? "Do CRM" : "Importar CSV"}
                    </button>
                  ))}
                </div>

                {leadTab === "crm" ? (
                  <div className="grid grid-cols-[220px_1fr] gap-4 min-h-[300px]">
                    {/* Filter panel */}
                    <div className="border-r border-[#dedbd6] pr-4 overflow-y-auto max-h-[400px]">
                      <LeadFilterPanel onApply={handleApplyLeadFilters} loading={loadingLeads} />
                    </div>

                    {/* Lead table */}
                    <div className="flex flex-col gap-2">
                      {/* Controls */}
                      <div className="flex items-center justify-between">
                        <span className="text-[12px] text-[#7b7b78]">
                          {loadingLeads
                            ? "Buscando leads..."
                            : `${leads.length} leads encontrados`}
                        </span>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={selectAllLeads}
                            disabled={leads.length === 0}
                            className="text-[12px] text-[#111111] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-white hover:border-[#111111] transition-colors disabled:opacity-40"
                          >
                            Selecionar todos
                          </button>
                          {selectedLeadIds.size > 0 && (
                            <button
                              type="button"
                              onClick={deselectAllLeads}
                              className="text-[12px] text-[#7b7b78] border border-[#dedbd6] px-2 py-0.5 rounded-[4px] bg-white hover:border-[#111111] transition-colors"
                            >
                              Limpar
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Count badge */}
                      <div className="text-[13px] font-medium text-[#111111]">
                        {selectedLeadIds.size > 0 ? (
                          <span className="inline-flex items-center gap-1 bg-[#111111] text-white px-2 py-0.5 rounded-[4px] text-[12px]">
                            {selectedLeadIds.size} leads selecionados
                          </span>
                        ) : (
                          <span className="text-[#b0aca6] text-[12px]">
                            Nenhum lead selecionado
                          </span>
                        )}
                      </div>

                      {/* Table */}
                      <div className="overflow-y-auto max-h-[320px] border border-[#dedbd6] rounded-[6px]">
                        {loadingLeads ? (
                          <div className="p-4 text-[13px] text-[#7b7b78] text-center">
                            Carregando...
                          </div>
                        ) : leadsError ? (
                          <div className="p-4 text-[13px] text-[#c41c1c] text-center">
                            {leadsError}
                          </div>
                        ) : leads.length === 0 ? (
                          <div className="p-4 text-[13px] text-[#7b7b78] text-center">
                            Nenhum lead encontrado. Ajuste os filtros.
                          </div>
                        ) : (
                          <table className="w-full text-left">
                            <thead className="sticky top-0 bg-[#faf9f6] border-b border-[#dedbd6]">
                              <tr>
                                <th className="w-8 px-3 py-2">
                                  <input
                                    type="checkbox"
                                    checked={
                                      leads.length > 0 &&
                                      leads.every((l) => selectedLeadIds.has(l.id))
                                    }
                                    onChange={(e) =>
                                      e.target.checked ? selectAllLeads() : deselectAllLeads()
                                    }
                                    className="accent-[#111111]"
                                  />
                                </th>
                                <th className="px-3 py-2 text-[11px] uppercase tracking-[0.5px] text-[#7b7b78] font-normal">
                                  Nome
                                </th>
                                <th className="px-3 py-2 text-[11px] uppercase tracking-[0.5px] text-[#7b7b78] font-normal">
                                  Telefone
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {leads.map((lead, idx) => (
                                <tr
                                  key={lead.id}
                                  onClick={(e) => toggleLead(lead.id, idx, e.shiftKey)}
                                  className={`cursor-pointer border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6] transition-colors ${
                                    idx % 2 === 0 ? "" : "bg-[#faf9f6]/50"
                                  } ${selectedLeadIds.has(lead.id) ? "bg-[#f0f0ee]" : ""}`}
                                >
                                  <td className="px-3 py-2">
                                    <input
                                      type="checkbox"
                                      checked={selectedLeadIds.has(lead.id)}
                                      onChange={() => {}}
                                      onClick={(e) => { e.stopPropagation(); toggleLead(lead.id, idx, e.shiftKey); }}
                                      className="accent-[#111111]"
                                    />
                                  </td>
                                  <td className="px-3 py-2 text-[13px] text-[#111111] max-w-[140px] truncate">
                                    {lead.name ?? lead.nome_fantasia ?? "—"}
                                  </td>
                                  <td className="px-3 py-2 text-[13px] text-[#7b7b78]">
                                    {lead.phone}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  /* CSV tab */
                  <div className="border-2 border-dashed border-[#dedbd6] rounded-[8px] p-8 text-center space-y-3">
                    <p className="text-[13px] text-[#7b7b78]">
                      Selecione um arquivo CSV com os leads a disparar.
                    </p>
                    <input
                      type="file"
                      accept=".csv"
                      onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                      className="text-[14px] text-[#111111]"
                    />
                    {csvFile && (
                      <p className="text-[12px] text-[#1a7a3a]">
                        Arquivo selecionado: <strong>{csvFile.name}</strong>
                      </p>
                    )}
                  </div>
                )}
              </>
            )}

            {/* ════════════════════════════════════════════════════════════════
                STEP 4 — Ação pós-disparo
            ════════════════════════════════════════════════════════════════ */}
            {step === 4 && (
              <div className="space-y-4">
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Ação pós-disparo
                  </label>
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="move-action"
                        value="none"
                        checked={moveAction === "none"}
                        onChange={() => {
                          setMoveAction("none");
                          setMovePipelineId("");
                          setMoveStageId("");
                        }}
                        className="accent-[#111111]"
                      />
                      <span className="text-[14px] text-[#111111]">Não mover leads</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="move-action"
                        value="move"
                        checked={moveAction === "move"}
                        onChange={() => setMoveAction("move")}
                        className="accent-[#111111]"
                      />
                      <span className="text-[14px] text-[#111111]">Mover para etapa do Kanban</span>
                    </label>
                  </div>
                </div>

                {moveAction === "move" && (
                  <div className="space-y-3 pl-6">
                    <div>
                      <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                        Funil
                      </label>
                      {loadingMovePipelines ? (
                        <div className="text-[13px] text-[#7b7b78]">Carregando funis...</div>
                      ) : (
                        <select
                          value={movePipelineId}
                          onChange={(e) => {
                            setMovePipelineId(e.target.value);
                            setMoveStageId("");
                          }}
                          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        >
                          <option value="">Selecionar funil...</option>
                          {movePipelines.map((p) => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                      )}
                    </div>

                    {movePipelineId && (
                      <div>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                          Etapa de destino
                        </label>
                        {loadingMoveStages ? (
                          <div className="text-[13px] text-[#7b7b78]">Carregando etapas...</div>
                        ) : (
                          <select
                            value={moveStageId}
                            onChange={(e) => setMoveStageId(e.target.value)}
                            className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                          >
                            <option value="">Selecionar etapa...</option>
                            {moveStages.map((s) => (
                              <option key={s.id} value={s.id}>{s.label}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    )}

                    {moveStageId && (
                      <p className="text-[12px] text-[#7b7b78]">
                        Os deals dos leads disparados com sucesso serão movidos para esta etapa.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ════════════════════════════════════════════════════════════════
                STEP 5 — Agendamento
            ════════════════════════════════════════════════════════════════ */}
            {step === 5 && (
              <div className="space-y-5">
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                    Quando disparar?
                  </label>
                  <div className="space-y-2">
                    {(
                      [
                        { value: "immediate" as const, label: "Iniciar imediatamente" },
                        { value: "scheduled" as const, label: "Agendar para depois" },
                      ]
                    ).map(({ value, label }) => (
                      <label key={value} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          name="schedule-mode"
                          value={value}
                          checked={scheduleMode === value}
                          onChange={() => setScheduleMode(value)}
                          className="accent-[#111111]"
                        />
                        <span className="text-[14px] text-[#111111]">{label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {scheduleMode === "scheduled" && (
                  <div className="bg-[#f0ede8] border border-[#dedbd6] rounded-[8px] p-4 space-y-4">
                    <p className="text-[12px] text-[#7b7b78] flex items-center gap-1">
                      🕐 <span>Horário de Brasília (UTC−3)</span>
                    </p>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                          Data
                        </label>
                        <input
                          type="date"
                          value={scheduleDate}
                          min={new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString().slice(0, 10)}
                          onChange={(e) => setScheduleDate(e.target.value)}
                          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                          Horário (BRT)
                        </label>
                        <input
                          type="time"
                          value={scheduleTime}
                          onChange={(e) => setScheduleTime(e.target.value)}
                          className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        />
                      </div>
                    </div>
                    {scheduleDate && scheduleTime && !scheduleIsValid() && (
                      <p className="text-[12px] text-[#c41c1c]">
                        A data/hora deve ser no futuro.
                      </p>
                    )}
                    {scheduleDate && scheduleTime && scheduleIsValid() && (
                      <p className="text-[12px] text-[#0bdf50]">
                        Disparo agendado para{" "}
                        {new Date(brtToUtcIso(scheduleDate, scheduleTime)).toLocaleString("pt-BR", {
                          timeZone: "America/Sao_Paulo",
                          dateStyle: "short",
                          timeStyle: "short",
                        })}{" "}
                        (Horário de Brasília)
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ════════════════════════════════════════════════════════════════
                STEP 6 — Revisão
            ════════════════════════════════════════════════════════════════ */}
            {step === 6 && (
              <div className="space-y-3">
                <h3 className="text-[14px] font-normal text-[#111111]">Revisão do disparo</h3>
                <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 space-y-2 text-[14px]">
                  <p>
                    <span className="text-[#7b7b78]">Nome:</span>{" "}
                    <span className="text-[#111111]">{name}</span>
                  </p>
                  <p>
                    <span className="text-[#7b7b78]">Canal:</span>{" "}
                    <span className="text-[#111111]">
                      {channels.find((c) => c.id === channelId)?.name ?? channelId}
                    </span>
                  </p>
                  <p>
                    <span className="text-[#7b7b78]">Template:</span>{" "}
                    <span className="text-[#111111]">{selectedTemplate?.name}</span>{" "}
                    <span className="text-[#7b7b78]">({selectedTemplate?.language})</span>
                  </p>
                  {selectedTemplate && (selectedTemplate.params.length > 0 || !!templateVarValues["__header_url__"]) && (
                    <div>
                      <span className="text-[#7b7b78]">Variáveis:</span>
                      <ul className="ml-3 mt-1 space-y-0.5">
                        {selectedTemplate.params.map((p) => {
                          const v = templateVarValues[p.paramName] ?? "";
                          return (
                            <li key={p.paramName} className="text-[12px]">
                              <span className="text-[#7b7b78]">
                                {selectedTemplate.paramsType === "positional"
                                  ? `{{${p.index}}}`
                                  : `{{${p.paramName}}}`}
                                :
                              </span>{" "}
                              {v ? (
                                <span className="text-[#111111]">{v}</span>
                              ) : (
                                <em className="text-[#b0aca6]">vazio</em>
                              )}
                            </li>
                          );
                        })}
                        {(templateVarValues["__header_url__"] ?? "") && (
                          <li className="text-[12px]">
                            <span className="text-[#7b7b78]">mídia:</span>{" "}
                            <span className="text-[#111111] truncate">{templateVarValues["__header_url__"]}</span>
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
                  <p>
                    <span className="text-[#7b7b78]">Leads:</span>{" "}
                    <span className="text-[#111111]">
                      {leadTab === "crm"
                        ? `${selectedLeadIds.size} lead${selectedLeadIds.size !== 1 ? "s" : ""} do CRM`
                        : csvFile
                        ? `CSV: ${csvFile.name}`
                        : "—"}
                    </span>
                  </p>
                  <p>
                    <span className="text-[#7b7b78]">Agente:</span>{" "}
                    <span className="text-[#111111]">{resolvedAgentName}</span>
                  </p>
                  <p>
                    <span className="text-[#7b7b78]">Ação pós-disparo:</span>{" "}
                    <span className="text-[#111111]">
                      {moveAction === "none"
                        ? "Não mover leads"
                        : moveStageId
                        ? `Mover para "${moveStages.find((s) => s.id === moveStageId)?.label ?? "—"}" (${movePipelines.find((p) => p.id === movePipelineId)?.name ?? "—"})`
                        : "—"}
                    </span>
                  </p>
                  <p>
                    <span className="text-[#7b7b78]">Agendamento:</span>{" "}
                    <span className="text-[#111111]">
                      {scheduleMode === "immediate"
                        ? "Imediato (iniciar manualmente)"
                        : scheduleDate && scheduleTime
                        ? new Date(brtToUtcIso(scheduleDate, scheduleTime)).toLocaleString("pt-BR", {
                            timeZone: "America/Sao_Paulo",
                            dateStyle: "short",
                            timeStyle: "short",
                          }) + " (BRT)"
                        : "—"}
                    </span>
                  </p>
                </div>
                <p className="text-[12px] text-[#7b7b78]">
                  {scheduleMode === "immediate"
                    ? "O disparo será criado como rascunho. Clique em \"Iniciar\" na página de detalhes para comenzar o envio."
                    : "O disparo será criado e iniciado automaticamente no horário agendado."}
                </p>
              </div>
            )}
          </div>

          {/* ── Footer ── */}
          <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-between flex-shrink-0">
            {step > 1 ? (
              <button
                onClick={() => setStep(step - 1)}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
              >
                Voltar
              </button>
            ) : (
              <div />
            )}

            {step < 6 ? (
              <button
                onClick={() => setStep(step + 1)}
                disabled={!canAdvance}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40"
              >
                Próximo
              </button>
            ) : (
              <button
                onClick={handleCreate}
                disabled={saving}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40"
              >
                {saving ? "Criando..." : "Criar Disparo"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── CreateTemplateModal overlay (stacked above wizard) ── */}
      {showCreateTemplate && (
        <CreateTemplateModal
          channelId={channelId}
          open={showCreateTemplate}
          onClose={() => setShowCreateTemplate(false)}
          onCreated={handleTemplateCreated}
        />
      )}

      {/* ── AlertDialog pós-criação ── */}
      <AlertDialog open={showStartDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disparo criado com sucesso</AlertDialogTitle>
            <AlertDialogDescription>
              Deseja iniciar o disparo agora? Os leads selecionados serão contatados em sequência via Meta Cloud.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelStart}>
              Agora não
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleStartNow} disabled={starting}>
              {starting ? "Iniciando..." : "Iniciar agora"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

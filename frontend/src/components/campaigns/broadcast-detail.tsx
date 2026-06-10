"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { Broadcast, BroadcastLead, BroadcastMetrics, SpamConflict } from "@/lib/types";

interface BroadcastDetailProps {
  broadcastId: string;
}

const statusStyles: Record<string, string> = {
  draft: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  running: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  paused: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20",
  completed: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
  scheduled: "bg-[#65b5ff]/10 text-[#65b5ff] border-[#65b5ff]/20",
  failed: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20",
};

const statusLabels: Record<string, string> = {
  draft: "Rascunho",
  running: "Rodando",
  paused: "Pausado",
  completed: "Completo",
  scheduled: "Agendado",
  failed: "Falhou",
};

const leadStatusStyles: Record<string, string> = {
  pending: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  sent: "bg-[#65b5ff]/10 text-[#65b5ff] border-[#65b5ff]/20",
  delivered: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
  failed: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20",
};

const leadStatusLabels: Record<string, string> = {
  pending: "Pendente",
  sent: "Enviado",
  delivered: "Entregue",
  failed: "Falhou",
};

type LeadStatusFilter = "all" | "sent" | "delivered" | "failed" | "pending";

export function BroadcastDetail({ broadcastId }: BroadcastDetailProps) {
  const router = useRouter();
  const [broadcast, setBroadcast] = useState<Broadcast | null>(null);
  const [leads, setLeads] = useState<BroadcastLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [activeFilter, setActiveFilter] = useState<LeadStatusFilter>("all");
  const [replyMetrics, setReplyMetrics] = useState<BroadcastMetrics | null>(null);
  const [spamConflicts, setSpamConflicts] = useState<SpamConflict[]>([]);
  const [showSpamModal, setShowSpamModal] = useState(false);
  const [selectedConflictIds, setSelectedConflictIds] = useState<Set<string>>(new Set());
  const [modalActionLoading, setModalActionLoading] = useState(false);
  const [showSchedulePicker, setShowSchedulePicker] = useState(false);
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("");
  const [scheduleLoading, setScheduleLoading] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch(`/api/broadcasts/${broadcastId}`).then((r) => r.json()),
      fetch(`/api/broadcasts/${broadcastId}/leads`).then((r) => r.json()),
      fetch(`/api/broadcasts/${broadcastId}/metrics`).then((r) => r.json()),
    ]).then(([broadcastData, leadsData, metricsData]) => {
      setBroadcast(broadcastData as Broadcast);
      setLeads(Array.isArray(leadsData) ? (leadsData as BroadcastLead[]) : []);
      setReplyMetrics(metricsData as BroadcastMetrics);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [broadcastId]);

  const handleStart = async () => {
    if (!broadcast || actionLoading) return;
    setActionLoading(true);
    try {
      const spamRes = await fetch(`/api/broadcasts/${broadcastId}/spam-check`);
      if (!spamRes.ok) {
        console.error("[handleStart] spam-check HTTP error:", spamRes.status, await spamRes.text());
        alert("Erro ao verificar spam. Tente novamente.");
        return;
      }
      const spamData = await spamRes.json();
      const conflicts: SpamConflict[] = spamData.conflicts ?? [];

      if (conflicts.length > 0) {
        setSpamConflicts(conflicts);
        setSelectedConflictIds(new Set(conflicts.map((c) => c.lead_id)));
        setShowSpamModal(true);
        return;
      }

      const startRes = await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      if (!startRes.ok) {
        const body = await startRes.json().catch(() => ({}));
        alert(body.error ?? body.detail ?? "Erro ao iniciar disparo.");
        return;
      }
      setBroadcast({ ...broadcast, status: "running" });
    } finally {
      setActionLoading(false);
    }
  };

  const handleRemoveSelected = async () => {
    if (!broadcast || modalActionLoading || selectedConflictIds.size === 0) return;
    setModalActionLoading(true);
    try {
      const res = await fetch(`/api/broadcasts/${broadcastId}/remove-leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_ids: [...selectedConflictIds] }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(`Erro ao remover leads: ${data.error}`);
        return;
      }
      const startRes = await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setShowSpamModal(false);
      setSpamConflicts([]);
      setSelectedConflictIds(new Set());
      if (startRes.ok) {
        setBroadcast({ ...broadcast, status: "running" });
      } else {
        const body = await startRes.json().catch(() => ({}));
        alert(body.detail ?? "Leads removidos, mas erro ao iniciar o disparo. Tente iniciar manualmente.");
      }
    } finally {
      setModalActionLoading(false);
      setActionLoading(false);
    }
  };

  const handleCreateDraftWithSelected = async () => {
    if (!broadcast || modalActionLoading || selectedConflictIds.size === 0) return;
    setModalActionLoading(true);
    try {
      const resolveRes = await fetch(`/api/broadcasts/${broadcastId}/resolve-spam`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conflict_lead_ids: [...selectedConflictIds] }),
      });
      const resolveData = await resolveRes.json();
      if (!resolveRes.ok) {
        alert(`Erro: ${resolveData.error}`);
        return;
      }
      const startRes = await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setShowSpamModal(false);
      setSpamConflicts([]);
      setSelectedConflictIds(new Set());
      if (startRes.ok) {
        setBroadcast({ ...broadcast, status: "running" });
        alert(`${resolveData.removed_count} lead(s) movidos para o rascunho "${resolveData.new_broadcast_name}"`);
      } else {
        const body = await startRes.json().catch(() => ({}));
        alert(body.detail ?? `${resolveData.removed_count} lead(s) movidos, mas erro ao iniciar o disparo.`);
      }
    } finally {
      setModalActionLoading(false);
      setActionLoading(false);
    }
  };

  const handleDispatchAnyway = async () => {
    if (!broadcast || modalActionLoading) return;
    setModalActionLoading(true);
    try {
      const startRes = await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setShowSpamModal(false);
      setSpamConflicts([]);
      setSelectedConflictIds(new Set());
      if (startRes.ok) {
        setBroadcast({ ...broadcast, status: "running" });
      } else {
        const body = await startRes.json().catch(() => ({}));
        alert(body.detail ?? "Erro ao iniciar o disparo.");
      }
    } finally {
      setModalActionLoading(false);
      setActionLoading(false);
    }
  };

  const handlePause = async () => {
    if (!broadcast || actionLoading) return;
    setActionLoading(true);
    try {
      await fetch(`/api/broadcasts/${broadcastId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "paused" }),
      });
      setBroadcast({ ...broadcast, status: "paused" });
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!broadcast || actionLoading) return;
    if (!confirm(`Excluir disparo "${broadcast.name}"? Esta ação não pode ser desfeita.`)) return;
    setActionLoading(true);
    try {
      await fetch(`/api/broadcasts/${broadcastId}`, { method: "DELETE" });
      router.push("/campanhas?tab=disparos");
    } finally {
      setActionLoading(false);
    }
  };

  const brtToUtcIso = (date: string, time: string): string => {
    const [year, month, day] = date.split("-").map(Number);
    const [hour, minute] = time.split(":").map(Number);
    return new Date(Date.UTC(year, month - 1, day, hour + 3, minute)).toISOString();
  };

  const formatScheduledAtBrt = (isoStr: string): string =>
    new Date(isoStr).toLocaleString("pt-BR", {
      timeZone: "America/Sao_Paulo",
      dateStyle: "short",
      timeStyle: "short",
    });

  const schedulePickerValid = (): boolean => {
    if (!scheduleDate || !scheduleTime) return false;
    return new Date(brtToUtcIso(scheduleDate, scheduleTime)) > new Date();
  };

  const handleScheduleApply = async () => {
    if (!broadcast || !schedulePickerValid() || scheduleLoading) return;
    setScheduleLoading(true);
    try {
      const res = await fetch(`/api/broadcasts/${broadcastId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheduled_at: brtToUtcIso(scheduleDate, scheduleTime) }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(`Erro ao agendar: ${data.error ?? data.detail ?? "Tente novamente."}`);
        return;
      }
      const updated = await res.json();
      setBroadcast({ ...broadcast, status: updated.status, scheduled_at: updated.scheduled_at });
      setShowSchedulePicker(false);
      setScheduleDate("");
      setScheduleTime("");
    } finally {
      setScheduleLoading(false);
    }
  };

  const handleCancelSchedule = async () => {
    if (!broadcast || scheduleLoading) return;
    if (!confirm("Cancelar o agendamento? O disparo voltará para rascunho.")) return;
    setScheduleLoading(true);
    try {
      const res = await fetch(`/api/broadcasts/${broadcastId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scheduled_at: null }),
      });
      if (!res.ok) {
        const data = await res.json();
        alert(`Erro ao cancelar agendamento: ${data.error ?? data.detail ?? "Tente novamente."}`);
        return;
      }
      const updated = await res.json();
      setBroadcast({ ...broadcast, status: updated.status, scheduled_at: null });
      setShowSchedulePicker(false);
    } finally {
      setScheduleLoading(false);
    }
  };

  if (loading || !broadcast) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
          <div className="h-8 w-64 rounded-[4px] animate-pulse bg-[#dedbd6]" />
        </div>
        <div className="flex-1 p-8 bg-[#faf9f6]">
          <div className="grid grid-cols-5 gap-4 mb-8">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="bg-white border border-[#dedbd6] rounded-[8px] p-4 h-24 animate-pulse" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  const pending = broadcast.total_leads - broadcast.sent - broadcast.failed;
  const pendingCount = pending < 0 ? 0 : pending;

  const metrics = [
    { label: "Total", value: broadcast.total_leads, color: "#111111" },
    { label: "Enviado", value: broadcast.sent, color: "#65b5ff" },
    { label: "Entregue", value: broadcast.delivered, color: "#0bdf50" },
    { label: "Falhou", value: broadcast.failed, color: "#c41c1c" },
    { label: "Pendente", value: pendingCount, color: "#7b7b78" },
  ];

  const moveStageLabel = broadcast.move_to_stage
    ? `${broadcast.move_to_stage.pipelines?.name ?? "—"} › ${broadcast.move_to_stage.label}`
    : null;

  const filters: { key: LeadStatusFilter; label: string }[] = [
    { key: "all", label: "Todos" },
    { key: "sent", label: "Enviado" },
    { key: "delivered", label: "Entregue" },
    { key: "failed", label: "Falhou" },
    { key: "pending", label: "Pendente" },
  ];

  const filteredLeads = activeFilter === "all"
    ? leads
    : leads.filter((l) => l.status === activeFilter);

  const formatSeconds = (secs: number | null): string => {
    if (secs == null || secs < 0) return "—";
    if (secs < 60) return "< 1 min";
    if (secs < 3600) return `${Math.round(secs / 60)} min`;
    if (secs < 86400) {
      const h = Math.floor(secs / 3600);
      const m = Math.round((secs % 3600) / 60);
      return m > 0 ? `${h}h ${m}min` : `${h}h`;
    }
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    return h > 0 ? `${d}d ${h}h` : `${d}d`;
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Page header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <Link
            href="/campanhas?tab=disparos"
            className="text-[#7b7b78] hover:text-[#111111] transition-colors text-[14px] flex-shrink-0"
          >
            ← Campanhas
          </Link>
          <span className="text-[#dedbd6] flex-shrink-0">/</span>
          <h1
            style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
            className="text-[32px] font-normal text-[#111111] truncate"
          >
            {broadcast.name}
          </h1>
          <span
            className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border flex-shrink-0 ${
              statusStyles[broadcast.status] ?? statusStyles.draft
            }`}
          >
            {statusLabels[broadcast.status] ?? broadcast.status}
          </span>
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 flex-shrink-0">
          {broadcast.status === "draft" && (
            <>
              <button
                onClick={handleStart}
                disabled={actionLoading}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                ▶ Iniciar
              </button>
              <button
                onClick={() => { setShowSchedulePicker(true); setScheduleDate(""); setScheduleTime(""); }}
                disabled={actionLoading}
                className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                🕐 Agendar
              </button>
              <button
                onClick={handleDelete}
                disabled={actionLoading}
                className="bg-transparent text-[#c41c1c] border border-[#c41c1c]/40 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Excluir
              </button>
            </>
          )}
          {broadcast.status === "scheduled" && broadcast.scheduled_at && (
            <>
              <span className="text-[13px] text-[#7b7b78] flex items-center gap-1">
                🕐 {formatScheduledAtBrt(broadcast.scheduled_at)}{" "}
                <span className="text-[11px]">(Horário de Brasília)</span>
              </span>
              <button
                onClick={() => {
                  const d = new Date(broadcast.scheduled_at!);
                  const brt = new Date(d.getTime() - 3 * 60 * 60 * 1000);
                  setScheduleDate(brt.toISOString().slice(0, 10));
                  setScheduleTime(brt.toISOString().slice(11, 16));
                  setShowSchedulePicker(true);
                }}
                disabled={scheduleLoading}
                className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Reagendar
              </button>
              <button
                onClick={handleCancelSchedule}
                disabled={scheduleLoading}
                className="bg-transparent text-[#c41c1c] border border-[#c41c1c]/40 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Cancelar agendamento
              </button>
            </>
          )}
          {broadcast.status === "running" && (
            <button
              onClick={handlePause}
              disabled={actionLoading}
              className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
            >
              ⏸ Pausar
            </button>
          )}
          {broadcast.status === "paused" && (
            <>
              <button
                onClick={handleStart}
                disabled={actionLoading}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                ▶ Retomar
              </button>
              <button
                onClick={handleDelete}
                disabled={actionLoading}
                className="bg-transparent text-[#c41c1c] border border-[#c41c1c]/40 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Excluir
              </button>
            </>
          )}
        </div>
      </div>

      {/* Schedule picker inline panel */}
      {showSchedulePicker && (
        <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-8 py-4 flex-shrink-0">
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Data
              </label>
              <input
                type="date"
                value={scheduleDate}
                min={new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString().slice(0, 10)}
                onChange={(e) => setScheduleDate(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Horário (Horário de Brasília)
              </label>
              <input
                type="time"
                value={scheduleTime}
                onChange={(e) => setScheduleTime(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <button
              onClick={handleScheduleApply}
              disabled={!schedulePickerValid() || scheduleLoading}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40"
            >
              {scheduleLoading ? "Salvando..." : "Confirmar"}
            </button>
            <button
              onClick={() => setShowSchedulePicker(false)}
              className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
            >
              Cancelar
            </button>
            {scheduleDate && scheduleTime && !schedulePickerValid() && (
              <span className="text-[12px] text-[#c41c1c]">Data/hora deve ser no futuro.</span>
            )}
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 overflow-auto px-8 py-6 bg-[#faf9f6] space-y-6">
        {/* Metric cards */}
        <div className="grid grid-cols-5 gap-4">
          {metrics.map(({ label, value, color }) => (
            <div
              key={label}
              className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-col items-center justify-center text-center"
            >
              <span
                className="text-[36px] font-normal leading-none"
                style={{ color, letterSpacing: "-0.5px" }}
              >
                {value}
              </span>
              <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mt-2">
                {label}
              </span>
            </div>
          ))}
        </div>

        {/* Reply metrics — only visible after dispatch started */}
        {broadcast.status !== "draft" && replyMetrics && (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-col items-center justify-center text-center">
              <span
                className="text-[36px] font-normal leading-none"
                style={{ color: "#111111", letterSpacing: "-0.5px" }}
              >
                {replyMetrics.reply_rate > 0 ? `${Math.round(replyMetrics.reply_rate)}%` : "—"}
              </span>
              <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mt-2">
                Taxa de Resposta
              </span>
              {replyMetrics.replied_count > 0 && (
                <span className="text-[11px] text-[#7b7b78] mt-1">
                  {replyMetrics.replied_count} lead{replyMetrics.replied_count !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-col items-center justify-center text-center">
              <span
                className="text-[36px] font-normal leading-none"
                style={{ color: "#111111", letterSpacing: "-0.5px" }}
              >
                {formatSeconds(replyMetrics.avg_reply_secs)}
              </span>
              <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mt-2">
                Tempo Médio de Resposta
              </span>
              {replyMetrics.median_reply_secs != null && (
                <span className="text-[11px] text-[#7b7b78] mt-1">
                  mediana {formatSeconds(replyMetrics.median_reply_secs)}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Post-dispatch action info */}
        {moveStageLabel && (
          <div className="bg-white border border-[#dedbd6] rounded-[8px] px-5 py-3 flex items-center gap-3">
            <span className="text-[#7b7b78] text-[13px]">Ação pós-disparo:</span>
            <span className="text-[13px] text-[#111111] font-medium">{moveStageLabel}</span>
            <span className="text-[11px] text-[#7b7b78] uppercase tracking-[0.5px] border border-[#dedbd6] rounded-[4px] px-2 py-0.5">
              Mover Kanban
            </span>
          </div>
        )}

        {/* Retry failures banner */}
        {broadcast.failed > 0 && (
          <div className="bg-[#c41c1c]/8 border border-[#c41c1c]/25 rounded-[8px] px-5 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-[#c41c1c] text-[18px]">⚠</span>
              <div>
                <p className="text-[14px] font-medium text-[#c41c1c]">
                  {broadcast.failed} lead{broadcast.failed > 1 ? "s" : ""} com falha de envio
                </p>
                <p className="text-[12px] text-[#c41c1c]/70 mt-0.5">
                  Você pode retentar o envio para os leads que falharam.
                </p>
              </div>
            </div>
            <Link
              href={`/campanhas?tab=disparos&retry=${broadcastId}`}
              className="flex-shrink-0 bg-[#c41c1c] text-white px-[14px] py-2 rounded-[4px] text-[13px] transition-transform hover:scale-110 active:scale-[0.85]"
            >
              ↩ Retentar Falhas
            </Link>
          </div>
        )}

        {/* Tab filter + lead table */}
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
          {/* Filter tabs */}
          <div className="border-b border-[#dedbd6] px-5 flex">
            {filters.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveFilter(key)}
                className={`px-4 py-3 text-[14px] border-b-2 transition-colors ${
                  activeFilter === key
                    ? "border-[#111111] text-[#111111]"
                    : "border-transparent text-[#7b7b78] hover:text-[#111111]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[#dedbd6] bg-[#faf9f6]">
                  {["Nome", "Telefone", "Status", "Enviado em", "Respondeu em", ...(moveStageLabel ? ["Kanban"] : []), "Erro"].map((col) => (
                    <th
                      key={col}
                      className="text-left px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium"
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredLeads.length === 0 ? (
                  <tr>
                    <td colSpan={moveStageLabel ? 7 : 6} className="px-5 py-10 text-center text-[14px] text-[#7b7b78]">
                      Nenhum lead encontrado
                    </td>
                  </tr>
                ) : (
                  filteredLeads.map((lead) => (
                    <tr
                      key={lead.id}
                      className="border-b border-[#dedbd6] last:border-0 hover:bg-[#faf9f6] transition-colors"
                    >
                      <td className="px-5 py-3 text-[14px] text-[#111111]">
                        {lead.leads?.name ?? <span className="text-[#7b7b78]">—</span>}
                      </td>
                      <td className="px-5 py-3 text-[14px] text-[#7b7b78] font-mono text-[13px]">
                        {lead.leads?.phone ?? <span className="text-[#7b7b78]">—</span>}
                      </td>
                      <td className="px-5 py-3">
                        <span
                          className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${
                            leadStatusStyles[lead.status] ?? leadStatusStyles.pending
                          }`}
                        >
                          {leadStatusLabels[lead.status] ?? lead.status}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-[13px] text-[#7b7b78]">
                        {lead.sent_at
                          ? new Date(lead.sent_at).toLocaleString("pt-BR", {
                              day: "2-digit",
                              month: "2-digit",
                              year: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : <span className="text-[#dedbd6]">—</span>}
                      </td>
                      <td className="px-5 py-3 text-[13px] text-[#7b7b78]">
                        {lead.first_replied_at
                          ? new Date(lead.first_replied_at).toLocaleString("pt-BR", {
                              day: "2-digit",
                              month: "2-digit",
                              year: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : <span className="text-[#dedbd6]">—</span>}
                      </td>
                      {moveStageLabel && (
                        <td className="px-5 py-3 text-[13px]">
                          {lead.deal_moved_at ? (
                            <span
                              className="text-[#0bdf50]"
                              title={new Date(lead.deal_moved_at).toLocaleString("pt-BR")}
                            >
                              ✓ Movido
                            </span>
                          ) : lead.status === "sent" || lead.status === "delivered" ? (
                            <span className="text-[#c41c1c]">Não movido</span>
                          ) : (
                            <span className="text-[#dedbd6]">—</span>
                          )}
                        </td>
                      )}
                      <td className="px-5 py-3 text-[13px] text-[#c41c1c] max-w-[280px]">
                        {lead.error_message ? (
                          <span className="truncate block" title={lead.error_message}>
                            {lead.error_message}
                          </span>
                        ) : (
                          <span className="text-[#dedbd6]">—</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {filteredLeads.length > 0 && (
            <div className="px-5 py-3 border-t border-[#dedbd6] bg-[#faf9f6]">
              <span className="text-[12px] text-[#7b7b78]">
                {filteredLeads.length} lead{filteredLeads.length !== 1 ? "s" : ""}
                {activeFilter !== "all" ? ` com status "${leadStatusLabels[activeFilter]}"` : " no total"}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Spam Warning Modal */}
      {showSpamModal && (
        <div
          className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
          onClick={() => {
            if (modalActionLoading) return;
            setShowSpamModal(false);
            setSpamConflicts([]);
            setSelectedConflictIds(new Set());
          }}
        >
          <div
            className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[640px] max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="px-6 py-5 border-b border-[#dedbd6]">
              <h2
                className="text-[20px] font-normal text-[#111111]"
                style={{ letterSpacing: "-0.4px" }}
              >
                Leads disparados recentemente
              </h2>
              <p className="text-[13px] text-[#7b7b78] mt-1">
                {spamConflicts.length} lead(s) abaixo receberam um disparo nas últimas 48h.
              </p>
            </div>

            {/* Contextual toolbar — visible only when ≥1 lead selected */}
            {selectedConflictIds.size > 0 && (
              <div className="px-6 py-3 border-b border-[#dedbd6] bg-[#faf9f6] flex items-center gap-3">
                <span className="text-[13px] text-[#7b7b78] flex-1">
                  {selectedConflictIds.size} selecionado(s)
                </span>
                <button
                  onClick={handleRemoveSelected}
                  disabled={modalActionLoading}
                  className="border border-[#c41c1c]/40 text-[#c41c1c] px-[12px] py-1.5 rounded-[4px] text-[13px] hover:bg-[#c41c1c]/5 disabled:opacity-50 transition-colors"
                >
                  {modalActionLoading ? "Processando..." : "Remover selecionados"}
                </button>
                <button
                  onClick={handleCreateDraftWithSelected}
                  disabled={modalActionLoading}
                  className="bg-[#111111] text-white px-[12px] py-1.5 rounded-[4px] text-[13px] hover:bg-[#333333] disabled:opacity-50 transition-colors"
                >
                  {modalActionLoading ? "Processando..." : "Criar novo disparo com selecionados"}
                </button>
              </div>
            )}

            {/* Table */}
            <div className="overflow-auto flex-1">
              <table className="w-full text-[13px]">
                <thead className="sticky top-0 bg-white border-b border-[#dedbd6]">
                  <tr className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                    <th className="text-left pl-6 pr-3 py-3 font-normal w-10">
                      <input
                        type="checkbox"
                        checked={
                          spamConflicts.length > 0 &&
                          selectedConflictIds.size === spamConflicts.length
                        }
                        onChange={() => {
                          if (selectedConflictIds.size === spamConflicts.length) {
                            setSelectedConflictIds(new Set());
                          } else {
                            setSelectedConflictIds(
                              new Set(spamConflicts.map((c) => c.lead_id))
                            );
                          }
                        }}
                        className="cursor-pointer"
                      />
                    </th>
                    <th className="text-left pr-3 py-3 font-normal">Nome</th>
                    <th className="text-left pr-3 py-3 font-normal">Telefone</th>
                    <th className="text-left pr-3 py-3 font-normal">Último Disparo</th>
                    <th className="text-left pr-6 py-3 font-normal">Enviado em</th>
                  </tr>
                </thead>
                <tbody>
                  {spamConflicts.map((c) => (
                    <tr
                      key={c.lead_id}
                      className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6] transition-colors"
                    >
                      <td className="pl-6 pr-3 py-2.5">
                        <input
                          type="checkbox"
                          checked={selectedConflictIds.has(c.lead_id)}
                          onChange={() => {
                            setSelectedConflictIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(c.lead_id)) next.delete(c.lead_id);
                              else next.add(c.lead_id);
                              return next;
                            });
                          }}
                          className="cursor-pointer"
                        />
                      </td>
                      <td className="pr-3 py-2.5 text-[#111111]">{c.lead_name ?? "—"}</td>
                      <td className="pr-3 py-2.5 text-[#7b7b78] font-mono text-[12px]">
                        {c.lead_phone}
                      </td>
                      <td className="pr-3 py-2.5 text-[#111111] max-w-[160px] truncate">
                        {c.last_broadcast_name}
                      </td>
                      <td className="pr-6 py-2.5 text-[#7b7b78] whitespace-nowrap">
                        {new Date(c.last_sent_at).toLocaleString("pt-BR", {
                          day: "2-digit",
                          month: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowSpamModal(false);
                  setSpamConflicts([]);
                  setSelectedConflictIds(new Set());
                }}
                disabled={modalActionLoading}
                className="border border-[#dedbd6] text-[#313130] px-[14px] py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                onClick={handleDispatchAnyway}
                disabled={modalActionLoading}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] hover:bg-[#333333] disabled:opacity-50 transition-colors"
              >
                {modalActionLoading ? "Processando..." : "Disparar mesmo assim"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

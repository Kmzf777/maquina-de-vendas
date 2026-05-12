"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { Broadcast, BroadcastLead } from "@/lib/types";

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

  useEffect(() => {
    Promise.all([
      fetch(`/api/broadcasts/${broadcastId}`).then((r) => r.json()),
      fetch(`/api/broadcasts/${broadcastId}/leads`).then((r) => r.json()),
    ]).then(([broadcastData, leadsData]) => {
      setBroadcast(broadcastData as Broadcast);
      setLeads(Array.isArray(leadsData) ? (leadsData as BroadcastLead[]) : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [broadcastId]);

  const handleStart = async () => {
    if (!broadcast || actionLoading) return;
    setActionLoading(true);
    try {
      await fetch(`/api/broadcasts/${broadcastId}/start`, { method: "POST" });
      setBroadcast({ ...broadcast, status: "running" });
    } finally {
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
                onClick={handleDelete}
                disabled={actionLoading}
                className="bg-transparent text-[#c41c1c] border border-[#c41c1c]/40 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Excluir
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
                  {["Nome", "Telefone", "Status", "Enviado em", "Erro"].map((col) => (
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
                    <td colSpan={5} className="px-5 py-10 text-center text-[14px] text-[#7b7b78]">
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
    </div>
  );
}

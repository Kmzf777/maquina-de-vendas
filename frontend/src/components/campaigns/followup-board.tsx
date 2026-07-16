"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { objectiveLabel, touchStateLabel } from "@/lib/cadence-display";
import {
  BOARD_STATUSES,
  type BoardJob,
  type BoardStatus,
  STATUS_FILTER_LABELS,
  displayInstant,
  formatBRT,
  isCancellable,
  offsetLabel,
  touchTypeLabel,
} from "@/lib/followup-board";

type DefinitionTouch = {
  sequence: number;
  offset_hours: number;
  jitter_minutes: number[] | null;
  objective: string;
};

type CadenceDefinition = {
  touches: DefinitionTouch[];
  outbound_nudge: DefinitionTouch;
  min_gap_hours: number;
  business_window: { start: string; end: string; days: string; timezone: string };
};

type Summary = {
  pending: number;
  awaiting_reopen: number;
  sent_today: number;
  sent_week: number;
};

type BoardRow = BoardJob & { conversation_id: string | null };

const STATUS_BADGE_STYLES: Record<string, string> = {
  pending: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20",
  awaiting_reopen: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  sent: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
  cancelled: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
};

function KpiCard({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">{label}</p>
      <p className="text-[28px] font-normal text-[#111111] mt-1" style={{ letterSpacing: "-0.5px" }}>
        {value ?? "—"}
      </p>
    </div>
  );
}

function DefinitionStrip({ definition }: { definition: CadenceDefinition | null }) {
  if (!definition) {
    return (
      <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
        <p className="text-[13px] text-[#7b7b78]">Definição da cadência indisponível</p>
      </div>
    );
  }
  const steps: { title: string; offset: string; objective: string }[] = [
    ...definition.touches.map((t) => ({
      title: `T${t.sequence}`,
      offset: offsetLabel(t.offset_hours, t.jitter_minutes),
      objective: objectiveLabel(t.objective),
    })),
  ];
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 style={{ letterSpacing: "-0.3px" }} className="text-[18px] font-medium text-[#111111]">
          Esteira da cadência (motor da Valéria)
        </h3>
        <span className="text-[12px] text-[#7b7b78]">
          janela comercial {definition.business_window.start}–{definition.business_window.end} ({definition.business_window.days}) · gap mínimo {definition.min_gap_hours}h
        </span>
      </div>
      <div className="flex flex-wrap items-stretch gap-2">
        {steps.map((s, i) => (
          <div key={s.title} className="flex items-center gap-2">
            <div className="border border-[#dedbd6] rounded-[6px] px-3 py-2 bg-[#faf9f6] min-w-[130px]">
              <p className="text-[12px] font-medium text-[#111111]">
                {s.title} <span className="text-[#7b7b78] font-normal">· {s.offset}</span>
              </p>
              <p className="text-[12px] text-[#7b7b78] mt-0.5">{s.objective}</p>
            </div>
            {i < steps.length - 1 && <span className="text-[#dedbd6]">→</span>}
          </div>
        ))}
      </div>
      <p className="text-[12px] text-[#7b7b78] mt-3">
        Lead outbound "sim-e-sumiu": T1 é substituído pelo nudge (+
        {definition.outbound_nudge.offset_hours}h, dentro da janela de 24h da Meta). Toque
        que vence com a janela fechada vira template de reabertura e os seguintes se
        dobram nele (aguardando reabertura).
      </p>
    </div>
  );
}

export function FollowupBoard() {
  const router = useRouter();
  const [definition, setDefinition] = useState<CadenceDefinition | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [statusFilter, setStatusFilter] = useState<BoardStatus>("pending");
  const [jobs, setJobs] = useState<BoardRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<BoardRow | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const loadSummary = useCallback(() => {
    fetch("/api/followups/summary")
      .then((r) => r.json())
      .then((d) => setSummary(d.error ? null : d))
      .catch(() => setSummary(null));
  }, []);

  const loadJobs = useCallback((status: BoardStatus) => {
    setJobs(null);
    setLoadError(null);
    fetch(`/api/followups?status=${status}&limit=100`)
      .then((r) => r.json())
      .then((d) => {
        if (Array.isArray(d)) setJobs(d);
        else setLoadError(d.error ?? "Resposta inesperada");
      })
      .catch((e) => setLoadError(String(e)));
  }, []);

  useEffect(() => {
    fetch("/api/cadence/definition")
      .then((r) => r.json())
      .then((d) => setDefinition(d.error ? null : d))
      .catch(() => setDefinition(null));
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    loadJobs(statusFilter);
  }, [statusFilter, loadJobs]);

  const confirmCancel = async () => {
    if (!cancelTarget) return;
    setCancelling(true);
    try {
      const res = await fetch(`/api/followups/${cancelTarget.id}/cancel`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) {
        setToast(`Não foi possível cancelar: ${body.error ?? res.statusText}`);
      } else {
        setToast("Toque cancelado");
        loadJobs(statusFilter);
        loadSummary();
      }
    } catch (e) {
      setToast(`Erro de rede: ${e}`);
    } finally {
      setCancelling(false);
      setCancelTarget(null);
      setTimeout(() => setToast(null), 6000);
    }
  };

  return (
    <div className="space-y-6">
      <DefinitionStrip definition={definition} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
        <KpiCard label="Pendentes" value={summary?.pending ?? null} />
        <KpiCard label="Aguardando reabertura" value={summary?.awaiting_reopen ?? null} />
        <KpiCard label="Enviados hoje" value={summary?.sent_today ?? null} />
        <KpiCard label="Enviados (7 dias)" value={summary?.sent_week ?? null} />
      </div>

      <div className="bg-white border border-[#dedbd6] rounded-[8px]">
        <div className="p-4 border-b border-[#dedbd6] flex flex-wrap items-center gap-2">
          {BOARD_STATUSES.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-[4px] text-[13px] border transition-colors ${
                statusFilter === s
                  ? "bg-[#111111] text-white border-[#111111]"
                  : "bg-transparent text-[#7b7b78] border-[#dedbd6] hover:text-[#111111]"
              }`}
            >
              {STATUS_FILTER_LABELS[s]}
            </button>
          ))}
        </div>

        {loadError && (
          <p className="text-[14px] text-[#c41c1c] p-6">Erro ao carregar: {loadError}</p>
        )}
        {!loadError && jobs === null && (
          <div className="p-6 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-10 rounded-[4px] animate-pulse bg-[#f0ede8]" />
            ))}
          </div>
        )}
        {!loadError && jobs !== null && jobs.length === 0 && (
          <p className="text-[14px] text-[#7b7b78] p-6 text-center">
            Nenhum toque {STATUS_FILTER_LABELS[statusFilter].toLowerCase()}
          </p>
        )}
        {!loadError && jobs !== null && jobs.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] border-b border-[#dedbd6]">
                  <th className="px-4 py-3 font-medium">Lead</th>
                  <th className="px-4 py-3 font-medium">Toque</th>
                  <th className="px-4 py-3 font-medium">Objetivo</th>
                  <th className="px-4 py-3 font-medium">Situação</th>
                  <th className="px-4 py-3 font-medium">Quando (BRT)</th>
                  <th className="px-4 py-3 font-medium text-right">Ação</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className="border-b border-[#f0ede8] last:border-0 hover:bg-[#faf9f6]">
                    <td className="px-4 py-3">
                      <button
                        onClick={() => j.lead_id && router.push(`/conversas?lead_id=${j.lead_id}`)}
                        className="text-[14px] text-[#111111] hover:underline text-left"
                        title="Abrir conversa"
                      >
                        {j.lead_name || j.lead_phone || "—"}
                      </button>
                      {j.lead_name && j.lead_phone && (
                        <p className="text-[12px] text-[#7b7b78]">{j.lead_phone}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[14px] text-[#111111]">{touchTypeLabel(j)}</td>
                    <td className="px-4 py-3 text-[13px] text-[#7b7b78]">{objectiveLabel(j.objetivo)}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${STATUS_BADGE_STYLES[j.status] ?? STATUS_BADGE_STYLES.cancelled}`}
                      >
                        {touchStateLabel(j)}
                      </span>
                      {j.status === "cancelled" && j.cancel_reason && (
                        <p className="text-[11px] text-[#7b7b78] mt-1">{j.cancel_reason}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[13px] text-[#7b7b78]">{formatBRT(displayInstant(j))}</td>
                    <td className="px-4 py-3 text-right">
                      {isCancellable(j) && (
                        <button
                          onClick={() => setCancelTarget(j)}
                          className="text-[13px] text-[#c41c1c] border border-[#c41c1c]/30 px-3 py-1 rounded-[4px] hover:bg-[#c41c1c]/5 transition-colors"
                        >
                          Cancelar
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {cancelTarget && (
        <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-md p-6">
            <h2 className="text-[16px] font-medium text-[#111111] mb-2">Cancelar toque?</h2>
            <p className="text-[14px] text-[#7b7b78] mb-4">
              {touchTypeLabel(cancelTarget)} de{" "}
              <span className="text-[#111111]">
                {cancelTarget.lead_name || cancelTarget.lead_phone || "lead"}
              </span>{" "}
              agendado para {formatBRT(displayInstant(cancelTarget))} não será enviado. Essa
              ação não pode ser desfeita.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setCancelTarget(null)}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px]"
              >
                Voltar
              </button>
              <button
                onClick={confirmCancel}
                disabled={cancelling}
                className="bg-[#c41c1c] text-white px-[14px] py-2 rounded-[4px] text-[14px] disabled:opacity-50"
              >
                {cancelling ? "Cancelando..." : "Cancelar toque"}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#111111] text-white text-[14px] px-4 py-3 rounded-[6px] shadow-lg flex items-center gap-3">
          <span>{toast}</span>
          <button onClick={() => setToast(null)} className="text-white/60 hover:text-white leading-none text-lg">
            &times;
          </button>
        </div>
      )}
    </div>
  );
}

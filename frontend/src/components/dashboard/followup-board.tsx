"use client";

import type { DashboardFollowups } from "./types";
import { fmtDateTime, fmtInt } from "./format";

/**
 * Bloco "Esteira de Follow-up": agendados × executados hoje (com badge de
 * vencidos pendentes), quebra por job_type e linha de retornos agendados.
 * Este bloco ignora o seletor de período (sempre "hoje" / snapshot).
 */
export function FollowupBoard({ data }: { data: DashboardFollowups }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5">
      <div className="flex flex-wrap items-start gap-x-10 gap-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1.5">
            Agendados hoje
          </p>
          <p
            className="text-[32px] font-normal leading-none text-[#111111]"
            style={{ letterSpacing: "-1px" }}
          >
            {fmtInt(data.scheduled_today)}
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1.5">
            Executados hoje
          </p>
          <p
            className="text-[32px] font-normal leading-none text-[#111111]"
            style={{ letterSpacing: "-1px" }}
          >
            {fmtInt(data.sent_today)}
          </p>
        </div>
        {data.overdue_pending > 0 && (
          <span className="inline-flex items-center gap-1.5 self-center rounded-full bg-[#c41c1c] text-white text-[12px] px-3 py-1">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path
                d="M6 1L11 10H1L6 1z"
                stroke="currentColor"
                strokeWidth="1.3"
                strokeLinejoin="round"
              />
              <path d="M6 4.5v2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <circle cx="6" cy="8.7" r="0.7" fill="currentColor" />
            </svg>
            {fmtInt(data.overdue_pending)} vencido{data.overdue_pending === 1 ? "" : "s"} pendente
            {data.overdue_pending === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {data.by_type.length > 0 && (
        <div className="mt-5 border border-[#f0ede8] rounded-[6px] overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-[#f0ede8] text-[#7b7b78] text-[11px] uppercase tracking-[0.4px]">
                <th className="text-left font-normal px-3 py-2">Tipo</th>
                <th className="text-right font-normal px-3 py-2">Agendados</th>
                <th className="text-right font-normal px-3 py-2">Enviados</th>
              </tr>
            </thead>
            <tbody>
              {data.by_type.map((row) => (
                <tr key={row.job_type} className="border-b border-[#f0ede8] last:border-0">
                  <td className="px-3 py-2 text-[#111111]">{row.job_type}</td>
                  <td className="px-3 py-2 text-right text-[#111111]">{fmtInt(row.scheduled)}</td>
                  <td className="px-3 py-2 text-right text-[#111111]">{fmtInt(row.sent)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 pt-3 border-t border-[#f0ede8] text-[13px] text-[#111111]">
        Retornos agendados: {fmtInt(data.returns_pending)} pendente
        {data.returns_pending === 1 ? "" : "s"}
        <span className="text-[#7b7b78]">
          {" "}
          · próximo {data.next_return_at ? fmtDateTime(data.next_return_at) : "—"}
        </span>
      </p>
    </div>
  );
}

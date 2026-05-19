"use client";

import { useState, useEffect } from "react";
import type { LeadBroadcastEntry } from "@/lib/types";

interface LeadBroadcastHistoryProps {
  leadId: string;
}

const messageStatusStyles: Record<string, string> = {
  pending: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]",
  sent: "bg-[#65b5ff]/10 text-[#65b5ff] border-[#65b5ff]/20",
  delivered: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20",
  failed: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20",
};

const messageStatusLabels: Record<string, string> = {
  pending: "Pendente",
  sent: "Enviado",
  delivered: "Entregue",
  failed: "Falhou",
};

export function LeadBroadcastHistory({ leadId }: LeadBroadcastHistoryProps) {
  const [entries, setEntries] = useState<LeadBroadcastEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/leads/${leadId}/broadcasts`)
      .then((r) => r.json())
      .then((data) => {
        setEntries(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [leadId]);

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1].map((i) => (
          <div key={i} className="h-10 rounded-[4px] bg-[#f0ede8] animate-pulse" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-[12px] text-[#7b7b78]">Nenhum disparo recebido</p>
    );
  }

  return (
    <div className="space-y-0">
      {entries.map((entry) => (
        <div
          key={entry.id}
          className="flex items-center justify-between py-2 border-b border-[#f0ede8] last:border-0"
        >
          <div className="min-w-0 flex-1 mr-3">
            <p className="text-[13px] text-[#111111] truncate">{entry.broadcast_name}</p>
            {entry.sent_at && (
              <p className="text-[11px] text-[#7b7b78]">
                {new Date(entry.sent_at).toLocaleString("pt-BR", {
                  day: "2-digit",
                  month: "2-digit",
                  year: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <span
              className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-1.5 py-0.5 rounded-[4px] border ${
                messageStatusStyles[entry.message_status] ?? messageStatusStyles.pending
              }`}
            >
              {messageStatusLabels[entry.message_status] ?? entry.message_status}
            </span>
            {entry.first_replied_at && (
              <span className="inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-1.5 py-0.5 rounded-[4px] border bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20">
                Respondeu
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

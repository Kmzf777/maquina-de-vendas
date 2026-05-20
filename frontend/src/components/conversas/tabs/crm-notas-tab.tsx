"use client";

import { useState, useEffect } from "react";
import type { LeadNote, LeadEvent } from "@/lib/types";

interface CrmNotasTabProps {
  leadId: string;
}

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

export function CrmNotasTab({ leadId }: CrmNotasTabProps) {
  const [notes, setNotes] = useState<LeadNote[]>([]);
  const [events, setEvents] = useState<LeadEvent[]>([]);
  const [newNote, setNewNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`/api/leads/${leadId}/notes`).then((r) => r.json()),
      fetch(`/api/leads/${leadId}/events`).then((r) => r.json()),
    ]).then(([notesData, eventsData]) => {
      setNotes(Array.isArray(notesData) ? notesData : []);
      setEvents(Array.isArray(eventsData) ? eventsData : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [leadId]);

  async function handleAddNote() {
    if (!newNote.trim()) return;
    setSaving(true);
    const res = await fetch(`/api/leads/${leadId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author: "Rafael", content: newNote.trim() }),
    });
    if (res.ok) {
      const note = await res.json();
      setNotes((prev) => [note, ...prev]);
      setNewNote("");
    }
    setSaving(false);
  }

  const timeline = [
    ...notes.map((n) => ({ type: "note" as const, data: n, date: n.created_at })),
    ...events.map((e) => ({ type: "event" as const, data: e, date: e.created_at })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  return (
    <div className="p-4 space-y-4">
      <div className="flex gap-2">
        <input
          value={newNote}
          onChange={(e) => setNewNote(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAddNote()}
          placeholder="Adicionar uma nota..."
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
        />
        <button
          onClick={handleAddNote}
          disabled={saving}
          className="bg-[#111111] text-white px-3 py-2 rounded-[4px] text-[13px] hover:bg-[#333] transition-colors disabled:opacity-50"
        >
          Salvar
        </button>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-[8px] bg-[#f0ede8] animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="space-y-2.5">
          {timeline.map((item) => (
            <div
              key={`${item.type}-${item.data.id}`}
              className={`rounded-[8px] p-3.5 border border-[#dedbd6] ${
                item.type === "note" ? "bg-white" : "bg-[#faf9f6]"
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
      )}
    </div>
  );
}

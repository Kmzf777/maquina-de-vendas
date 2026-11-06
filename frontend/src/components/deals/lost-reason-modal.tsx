"use client";

import { useState } from "react";
import {
  LOST_REASONS,
  LOST_COMPETITOR_MAX,
  buildLostReason,
  validateLostReason,
  type LostReasonCode,
  type LostReasonValue,
} from "@/lib/lost-reason";

interface LostReasonModalProps {
  onConfirm: (value: LostReasonValue) => void | Promise<void>;
  onCancel: () => void;
}

const fieldClass =
  "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full";

/**
 * Motivo da perda (F4): o motivo sai de uma lista fechada e é obrigatório; o concorrente
 * é obrigatório quando o lead comprou de outro; a observação continua livre.
 */
export function LostReasonModal({ onConfirm, onCancel }: LostReasonModalProps) {
  const [code, setCode] = useState("");
  const [competitor, setCompetitor] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleConfirm() {
    const err = validateLostReason(code, competitor);
    if (err) {
      setError(err);
      return;
    }
    setSaving(true);
    try {
      await onConfirm(buildLostReason(code as LostReasonCode, competitor, note));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-[60] flex items-center justify-center p-4" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="lost-reason-title"
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[400px] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="lost-reason-title" className="text-[16px] font-normal text-[#111111] mb-1" style={{ letterSpacing: '-0.48px', lineHeight: '1.00' }}>Motivo da perda</h3>
        <p className="text-[13px] text-[#7b7b78] mb-4">Por que essa oportunidade foi perdida?</p>

        <label htmlFor="lost-reason-code" className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Motivo *</label>
        <select
          id="lost-reason-code"
          value={code}
          onChange={(e) => { setCode(e.target.value); setError(null); }}
          className={fieldClass}
        >
          <option value="">Escolha o motivo...</option>
          {LOST_REASONS.map((r) => (
            <option key={r.code} value={r.code}>{r.label}</option>
          ))}
        </select>

        {code === "comprou_outro" && (
          <div className="mt-3">
            <label htmlFor="lost-competitor" className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">Comprou de quem? *</label>
            <input
              id="lost-competitor"
              value={competitor}
              maxLength={LOST_COMPETITOR_MAX}
              onChange={(e) => { setCompetitor(e.target.value); setError(null); }}
              placeholder="Ex: Orfeu, torrefação da região, distribuidor..."
              className={fieldClass}
            />
          </div>
        )}

        <label htmlFor="lost-note" className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1 mt-3">Observação</label>
        <textarea
          id="lost-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Detalhes que ajudam a entender a perda (opcional)"
          className={`${fieldClass} resize-none h-20`}
        />

        {error && <p role="alert" className="text-[12px] text-red-600 mt-2">{error}</p>}

        <div className="flex gap-2 mt-4 justify-end">
          <button onClick={onCancel} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">Cancelar</button>
          <button
            onClick={handleConfirm}
            disabled={saving}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
          >
            {saving ? "Salvando..." : "Confirmar"}
          </button>
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";

interface LostReasonModalProps {
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export function LostReasonModal({ onConfirm, onCancel }: LostReasonModalProps) {
  const [reason, setReason] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onCancel}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="relative bg-white rounded-2xl p-6 w-full max-w-[400px] shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[16px] font-semibold text-[#1f1f1f] mb-1">Motivo da perda</h3>
        <p className="text-[13px] text-[#5f6368] mb-4">Por que essa oportunidade foi perdida?</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Ex: Preco alto, concorrente, sem resposta..."
          className="w-full text-[13px] rounded-xl px-4 py-3 border border-[#e5e5dc] outline-none focus:border-[#c8cc8e] resize-none h-24"
        />
        <div className="flex gap-2 mt-4 justify-end">
          <button onClick={onCancel} className="px-4 py-2 rounded-lg border border-[#e5e5dc] bg-white text-[13px] text-[#5f6368] hover:bg-[#f6f7ed]">Cancelar</button>
          <button onClick={() => onConfirm(reason)} className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333]">Confirmar</button>
        </div>
      </div>
    </div>
  );
}

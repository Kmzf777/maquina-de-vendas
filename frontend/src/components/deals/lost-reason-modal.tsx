"use client";

import { useState } from "react";

interface LostReasonModalProps {
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export function LostReasonModal({ onConfirm, onCancel }: LostReasonModalProps) {
  const [reason, setReason] = useState("");

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onCancel}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-[400px] p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[16px] font-normal text-[#111111] mb-1" style={{ letterSpacing: '-0.48px', lineHeight: '1.00' }}>Motivo da perda</h3>
        <p className="text-[13px] text-[#7b7b78] mb-4">Por que essa oportunidade foi perdida?</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Ex: Preco alto, concorrente, sem resposta..."
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full resize-none h-24"
        />
        <div className="flex gap-2 mt-4 justify-end">
          <button onClick={onCancel} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">Cancelar</button>
          <button onClick={() => onConfirm(reason)} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">Confirmar</button>
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";

interface PipelineCreateModalProps {
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
}

export function PipelineCreateModal({ onClose, onCreate }: PipelineCreateModalProps) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onCreate(name.trim());
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-sm p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[18px] font-normal text-[#111111] mb-4" style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}>
          Novo Funil
        </h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome do Funil *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex: Funil Atacado"
              autoFocus
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
            />
            <p className="text-[11px] text-[#7b7b78] mt-1.5">O funil será criado com os stages padrão (Novo, Contato, Proposta, Negociação, Fechado Ganho, Perdido).</p>
          </div>
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" onClick={onClose} className="border border-[#dedbd6] text-[#313130] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] transition-colors">
              Cancelar
            </button>
            <button type="submit" disabled={saving || !name.trim()} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Funil"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

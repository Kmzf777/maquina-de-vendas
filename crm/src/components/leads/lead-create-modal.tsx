"use client";

import { useState } from "react";
import { AGENT_STAGES, LEAD_CHANNELS } from "@/lib/constants";

interface LeadCreateModalProps {
  onClose: () => void;
  onCreate: (data: Record<string, string>) => Promise<{ error?: string }>;
}

export function LeadCreateModal({ onClose, onCreate }: LeadCreateModalProps) {
  const [form, setForm] = useState({
    name: "",
    phone: "",
    email: "",
    instagram: "",
    company: "",
    cnpj: "",
    stage: "secretaria",
    channel: "manual",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.phone.trim()) {
      setError("Nome e telefone sao obrigatorios.");
      return;
    }
    setSaving(true);
    const result = await onCreate(form);
    setSaving(false);
    if (result.error) {
      setError(result.error);
    } else {
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-16" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div
        className="relative bg-white rounded-2xl w-full max-w-[500px] overflow-hidden shadow-[0_25px_50px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-5 border-b border-[#f3f3f0] flex justify-between items-center">
          <h3 className="text-[18px] font-semibold text-[#1f1f1f]">Novo Lead</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-lg border border-[#e5e5dc] flex items-center justify-center text-[#9ca3af] hover:text-[#1f1f1f]">
            x
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6">
          <div className="space-y-3">
            {/* Required */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Nome *</label>
                <input
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                  placeholder="Nome do lead"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Telefone *</label>
                <input
                  value={form.phone}
                  onChange={(e) => update("phone", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                  placeholder="+55 11 99999-9999"
                />
              </div>
            </div>

            {/* Optional */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Email</label>
                <input
                  value={form.email}
                  onChange={(e) => update("email", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Instagram</label>
                <input
                  value={form.instagram}
                  onChange={(e) => update("instagram", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Empresa</label>
                <input
                  value={form.company}
                  onChange={(e) => update("company", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">CNPJ</label>
                <input
                  value={form.cnpj}
                  onChange={(e) => update("cnpj", e.target.value)}
                  className="w-full text-[14px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none focus:border-[#c8cc8e]"
                />
              </div>
            </div>

            {/* Selects */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Stage</label>
                <select
                  value={form.stage}
                  onChange={(e) => update("stage", e.target.value)}
                  className="w-full text-[13px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                >
                  {AGENT_STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[11px] text-[#b0b0b0] uppercase block mb-1">Canal</label>
                <select
                  value={form.channel}
                  onChange={(e) => update("channel", e.target.value)}
                  className="w-full text-[13px] px-3 py-2 rounded-lg border border-[#e5e5dc] outline-none bg-white"
                >
                  {LEAD_CHANNELS.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {error && (
            <p className="text-[13px] text-[#ef4444] mt-3">{error}</p>
          )}

          <div className="flex justify-end mt-5">
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2.5 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Lead"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

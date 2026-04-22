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
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-6">
          <h3
            className="text-[24px] font-normal text-[#111111]"
            style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
          >
            Novo Lead
          </h3>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-[4px] border border-[#dedbd6] flex items-center justify-center text-[#7b7b78] hover:text-[#111111] hover:border-[#111111] transition-colors"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="space-y-3">
            {/* Required */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome *</label>
                <input
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="Nome do lead"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Telefone *</label>
                <input
                  value={form.phone}
                  onChange={(e) => update("phone", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="+55 11 99999-9999"
                />
              </div>
            </div>

            {/* Optional */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Email</label>
                <input
                  value={form.email}
                  onChange={(e) => update("email", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Instagram</label>
                <input
                  value={form.instagram}
                  onChange={(e) => update("instagram", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Empresa</label>
                <input
                  value={form.company}
                  onChange={(e) => update("company", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">CNPJ</label>
                <input
                  value={form.cnpj}
                  onChange={(e) => update("cnpj", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
            </div>

            {/* Selects */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Stage</label>
                <select
                  value={form.stage}
                  onChange={(e) => update("stage", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  {AGENT_STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Canal</label>
                <select
                  value={form.channel}
                  onChange={(e) => update("channel", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  {LEAD_CHANNELS.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {error && (
            <p className="text-[13px] text-[#c41c1c] mt-3">{error}</p>
          )}

          <div className="flex justify-end mt-5">
            <button
              type="submit"
              disabled={saving}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Lead"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

interface QuickAddLeadProps {
  stage: string;
  humanControl?: boolean;
}

export function QuickAddLead({ stage, humanControl = false }: QuickAddLeadProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");
  const [saving, setSaving] = useState(false);
  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!phone.trim()) return;
    setSaving(true);

    await supabase.from("leads").insert({
      name: name.trim() || null,
      phone: phone.trim(),
      company: company.trim() || null,
      stage,
      human_control: humanControl,
      status: "active",
      channel: "manual",
    });

    setName("");
    setPhone("");
    setCompany("");
    setOpen(false);
    setSaving(false);
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full text-center py-2 text-[12px] text-[#9ca3af] hover:text-[#5f6368] border border-dashed border-[#d4d4c8] hover:border-[#c8cc8e] rounded-[10px] transition-colors mt-2"
      >
        + Adicionar lead
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-[#e5e5dc] rounded-xl p-3 space-y-2">
      <input
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        placeholder="Telefone *"
        className="input-field w-full text-[12px] rounded-lg px-3 py-1.5"
        required
      />
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Nome"
        className="input-field w-full text-[12px] rounded-lg px-3 py-1.5"
      />
      <input
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        placeholder="Empresa"
        className="input-field w-full text-[12px] rounded-lg px-3 py-1.5"
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="btn-primary flex-1 py-1.5 rounded-lg text-[12px] font-medium disabled:opacity-50"
        >
          {saving ? "..." : "Criar"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="btn-secondary flex-1 py-1.5 rounded-lg text-[12px] font-medium"
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}

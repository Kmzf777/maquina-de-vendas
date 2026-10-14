"use client";

import { useState } from "react";

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
  const [erro, setErro] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErro("");
    if (!phone.trim()) return;
    setSaving(true);

    // Pela API (não direto no Supabase): ela normaliza o telefone e acha o lead
    // já cadastrado em qualquer formato antigo do número (cartão b747da43).
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.trim() || null,
        phone: phone.trim(),
        company: company.trim() || null,
        stage,
        human_control: humanControl,
        channel: "manual",
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setErro(err.error || "Erro ao criar lead");
      setSaving(false);
      return;
    }

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
        className="w-full text-center py-2 text-[12px] text-[#7b7b78] hover:text-[#111111] border border-dashed border-[#dedbd6] hover:border-[#111111] rounded-[8px] transition-colors mt-2"
      >
        + Adicionar lead
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-3 space-y-2">
      <input
        value={phone}
        onChange={(e) => setPhone(e.target.value)}
        placeholder="Telefone *"
        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[12px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
        required
      />
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Nome"
        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[12px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
      />
      <input
        value={company}
        onChange={(e) => setCompany(e.target.value)}
        placeholder="Empresa"
        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[12px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
      />
      {erro && <p className="text-[11px] text-[#b42318]" role="alert">{erro}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="flex-1 bg-[#111111] text-white py-1.5 rounded-[4px] text-[12px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
        >
          {saving ? "..." : "Criar"}
        </button>
        <button
          type="button"
          onClick={() => {
            setErro("");
            setOpen(false);
          }}
          className="flex-1 bg-transparent text-[#111111] border border-[#111111] py-1.5 rounded-[4px] text-[12px] transition-transform hover:scale-110 active:scale-[0.85]"
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}

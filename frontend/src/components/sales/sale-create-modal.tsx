"use client";

import { useState, useEffect } from "react";
import type { TeamUser } from "@/lib/types";

interface LeadDeal {
  id: string;
  title: string;
  pipeline_stages?: { is_protected: boolean } | null;
}

interface SaleCreateModalProps {
  leadId: string;
  conversationId?: string | null;
  currentUserEmail?: string;
  onClose: () => void;
  onCreated: () => void;
}

export function SaleCreateModal({
  leadId,
  conversationId,
  currentUserEmail,
  onClose,
  onCreated,
}: SaleCreateModalProps) {
  const [product, setProduct] = useState("");
  const [value, setValue] = useState("");
  const [soldAt, setSoldAt] = useState(new Date().toISOString().slice(0, 10));
  const [soldBy, setSoldBy] = useState(currentUserEmail ?? "");
  const [dealId, setDealId] = useState("");
  const [notes, setNotes] = useState("");
  const [users, setUsers] = useState<TeamUser[]>([]);
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/users")
      .then((r) => r.json())
      .then((data) => setUsers(Array.isArray(data) ? data : []));
    fetch(`/api/leads/${leadId}/deals`)
      .then((r) => r.json())
      .then((data) =>
        setDeals(
          (Array.isArray(data) ? data : []).filter(
            (d: LeadDeal) => !d.pipeline_stages?.is_protected
          )
        )
      );
  }, [leadId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!product.trim() || !value) {
      setError("Produto e valor são obrigatórios");
      return;
    }
    setSaving(true);
    setError(null);
    const res = await fetch("/api/sales", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lead_id: leadId,
        conversation_id: conversationId || null,
        product: product.trim(),
        value: parseFloat(value),
        sold_at: new Date(soldAt + "T12:00:00").toISOString(),
        sold_by: soldBy || null,
        deal_id: dealId || null,
        notes: notes.trim() || null,
      }),
    });
    if (!res.ok) {
      const d = await res.json();
      setError(d.error ?? "Erro ao salvar venda");
      setSaving(false);
      return;
    }
    onCreated();
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-white rounded-[8px] border border-[#dedbd6] w-full max-w-md mx-4 shadow-lg">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#dedbd6]">
          <h2 className="text-[15px] font-medium text-[#111111]">Registrar Venda</h2>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Produto / Serviço *
            </label>
            <input
              type="text"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              placeholder="Ex: Café especial 5kg"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Valor (R$) *
            </label>
            <input
              type="number"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="0,00"
              min="0"
              step="0.01"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Data da Venda
            </label>
            <input
              type="date"
              value={soldAt}
              onChange={(e) => setSoldAt(e.target.value)}
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            />
          </div>
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Vendedor
            </label>
            <select
              value={soldBy}
              onChange={(e) => setSoldBy(e.target.value)}
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
            >
              <option value="">Nenhum</option>
              {users.map((u) => (
                <option key={u.id} value={u.email}>
                  {u.name || u.email}
                </option>
              ))}
            </select>
          </div>
          {deals.length > 0 && (
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
                Vincular a Deal (opcional)
              </label>
              <select
                value={dealId}
                onChange={(e) => setDealId(e.target.value)}
                className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
              >
                <option value="">Nenhum</option>
                {deals.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title}
                  </option>
                ))}
              </select>
              {dealId && (
                <p className="text-[11px] text-[#7b7b78] mt-1">
                  O deal será movido para Fechado Ganho automaticamente.
                </p>
              )}
            </div>
          )}
          <div>
            <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
              Observação
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Observações opcionais"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none resize-none"
            />
          </div>
          {error && <p className="text-[12px] text-red-600">{error}</p>}
          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 text-[13px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 py-2 text-[13px] font-medium bg-[#111111] text-white rounded-[4px] hover:bg-[#222222] transition-colors disabled:opacity-50"
            >
              {saving ? "Salvando..." : "Registrar Venda"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

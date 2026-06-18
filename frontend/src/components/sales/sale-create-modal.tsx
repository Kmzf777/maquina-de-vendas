"use client";

import { useState, useEffect } from "react";
import type { TeamUser, Sale } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface LeadDeal {
  id: string;
  title: string;
  pipeline_stages?: { is_protected: boolean } | null;
}

interface Pipeline {
  id: string;
  name: string;
}

interface LeadOption {
  id: string;
  name: string | null;
  phone: string;
}

interface SaleCreateModalProps {
  leadId?: string;
  pickLead?: boolean;
  lockedDealId?: string;
  lockedDealTitle?: string;
  conversationId?: string | null;
  currentUserEmail?: string;
  editingSale?: Sale | null;
  onClose: () => void;
  onSaved: () => void;
}

const fieldLabel = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1";
const fieldInput =
  "w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0";

export function SaleCreateModal({
  leadId,
  pickLead,
  lockedDealId,
  lockedDealTitle,
  conversationId,
  currentUserEmail,
  editingSale,
  onClose,
  onSaved,
}: SaleCreateModalProps) {
  const isEditing = !!editingSale;

  const [selectedLeadId, setSelectedLeadId] = useState(
    editingSale?.lead_id ?? leadId ?? ""
  );
  const [product, setProduct] = useState(editingSale?.product ?? "");
  const [value, setValue] = useState(
    editingSale ? String(editingSale.value) : ""
  );
  const [soldAt, setSoldAt] = useState(
    (editingSale?.sold_at ?? new Date().toISOString()).slice(0, 10)
  );
  const [soldBy, setSoldBy] = useState(
    editingSale?.sold_by ?? currentUserEmail ?? ""
  );
  const [dealId, setDealId] = useState(lockedDealId ?? "");
  const [creatingDeal, setCreatingDeal] = useState(false);
  const [newDealTitle, setNewDealTitle] = useState("");
  const [newDealPipeline, setNewDealPipeline] = useState("");
  const [notes, setNotes] = useState(editingSale?.notes ?? "");

  const [users, setUsers] = useState<TeamUser[]>([]);
  const [leads, setLeads] = useState<LeadOption[]>([]);
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── initial data fetches ─────────────────────────────────────────────────
  useEffect(() => {
    fetch("/api/users")
      .then((r) => r.json())
      .then((d) => setUsers(Array.isArray(d) ? d : []));

    if (pickLead && !isEditing) {
      fetch("/api/leads")
        .then((r) => r.json())
        .then((d) => {
          const arr = Array.isArray(d) ? d : (d?.data ?? []);
          setLeads(arr);
        });
    }

    if (!isEditing && !lockedDealId) {
      fetch("/api/pipelines")
        .then((r) => r.json())
        .then((d) => setPipelines(Array.isArray(d) ? d : []));
    }
  }, [pickLead, isEditing, lockedDealId]);

  // ── fetch deals when selectedLeadId changes ──────────────────────────────
  useEffect(() => {
    if (isEditing || lockedDealId || !selectedLeadId) return;
    fetch(`/api/leads/${selectedLeadId}/deals`)
      .then((r) => r.json())
      .then((d) =>
        setDeals(
          (Array.isArray(d) ? d : []).filter(
            (x: LeadDeal) => !x.pipeline_stages?.is_protected
          )
        )
      );
  }, [selectedLeadId, isEditing, lockedDealId]);

  // ── submit ───────────────────────────────────────────────────────────────
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!product.trim() || !value) {
      setError("Produto e valor são obrigatórios");
      return;
    }

    if (isEditing) {
      setSaving(true);
      setError(null);
      const res = await fetch(`/api/sales/${editingSale!.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: product.trim(),
          value: parseFloat(value),
          sold_at: new Date(soldAt + "T12:00:00").toISOString(),
          sold_by: soldBy && soldBy !== "__none__" ? soldBy : null,
          notes: notes.trim() || null,
        }),
      });
      if (!res.ok) {
        const msg = res.headers.get("content-type")?.includes("json")
          ? (await res.json().catch(() => ({}))).error
          : null;
        setError(msg ?? "Erro ao salvar venda");
        setSaving(false);
        return;
      }
      onSaved();
      onClose();
      return;
    }

    if (!selectedLeadId) {
      setError("Selecione o lead");
      return;
    }

    const linkExisting = !!dealId && !creatingDeal;
    const linkNew =
      creatingDeal && !!newDealTitle.trim() && !!newDealPipeline;

    if (!lockedDealId && !linkExisting && !linkNew) {
      setError("Vincule a um deal existente ou crie um novo deal");
      return;
    }

    setSaving(true);
    setError(null);

    const payload: Record<string, unknown> = {
      lead_id: selectedLeadId,
      conversation_id: conversationId || null,
      product: product.trim(),
      value: parseFloat(value),
      sold_at: new Date(soldAt + "T12:00:00").toISOString(),
      sold_by: soldBy && soldBy !== "__none__" ? soldBy : null,
      notes: notes.trim() || null,
    };

    if (lockedDealId) {
      payload.deal_id = lockedDealId;
    } else if (linkExisting) {
      payload.deal_id = dealId;
    } else {
      payload.new_deal = {
        title: newDealTitle.trim(),
        pipeline_id: newDealPipeline,
      };
    }

    const res = await fetch("/api/sales", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const msg = res.headers.get("content-type")?.includes("json")
        ? (await res.json().catch(() => ({}))).error
        : null;
      setError(msg ?? "Erro ao salvar venda");
      setSaving(false);
      return;
    }
    onSaved();
    onClose();
  }

  // ── helpers ───────────────────────────────────────────────────────────────
  const resolvedLeadId = selectedLeadId || leadId || "";

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent
        showCloseButton={false}
        className="bg-white border border-[#dedbd6] rounded-[8px] p-0 w-full max-w-md shadow-lg gap-0"
      >
        {/* Header */}
        <DialogHeader className="flex-row items-center justify-between px-5 py-4 border-b border-[#dedbd6] mb-0 gap-0">
          <DialogTitle className="text-[15px] font-medium text-[#111111]">
            {isEditing ? "Editar Venda" : "Registrar Venda"}
          </DialogTitle>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar"
            className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </DialogHeader>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">

          {/* Lead selector — only in pickLead mode and not editing */}
          {pickLead && !isEditing && (
            <div>
              <label className={fieldLabel}>Lead *</label>
              <Select
                value={resolvedLeadId || undefined}
                onValueChange={(v) => {
                  setSelectedLeadId(v);
                  setDealId("");
                  setCreatingDeal(false);
                  setNewDealTitle("");
                  setNewDealPipeline("");
                }}
              >
                <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                  <SelectValue placeholder="Selecione o lead" />
                </SelectTrigger>
                <SelectContent position="popper">
                  {leads.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      {l.name ?? l.phone}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Product */}
          <div>
            <label className={fieldLabel}>Produto / Serviço *</label>
            <Input
              type="text"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              placeholder="Ex: Café especial 5kg"
              className={fieldInput}
              required
            />
          </div>

          {/* Value */}
          <div>
            <label className={fieldLabel}>Valor (R$) *</label>
            <Input
              type="number"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="0,00"
              min="0"
              step="0.01"
              className={fieldInput}
              required
            />
          </div>

          {/* Sale date */}
          <div>
            <label className={fieldLabel}>Data da Venda</label>
            <Input
              type="date"
              value={soldAt}
              onChange={(e) => setSoldAt(e.target.value)}
              className={fieldInput}
            />
          </div>

          {/* Sold by */}
          <div>
            <label className={fieldLabel}>Vendedor</label>
            <Select value={soldBy || undefined} onValueChange={setSoldBy}>
              <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                <SelectValue placeholder="Nenhum" />
              </SelectTrigger>
              <SelectContent position="popper">
                <SelectItem value="__none__">Nenhum</SelectItem>
                {users.map((u) => (
                  <SelectItem key={u.id} value={u.email}>
                    {u.name || u.email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Deal block — hidden in edit mode */}
          {!isEditing && (
            <div>
              <label className={fieldLabel}>Deal{!lockedDealId ? " *" : ""}</label>

              {/* Locked deal — read-only */}
              {lockedDealId ? (
                <div className="w-full bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111]">
                  {lockedDealTitle ?? lockedDealId}
                </div>
              ) : (
                <>
                  {/* Existing deal selector (when not creating a new one) */}
                  {!creatingDeal && (
                    <>
                      <Select
                        value={dealId || undefined}
                        onValueChange={(v) => {
                          if (v === "__new__") {
                            setDealId("");
                            setCreatingDeal(true);
                          } else {
                            setDealId(v);
                          }
                        }}
                      >
                        <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                          <SelectValue placeholder="Selecione ou crie um deal" />
                        </SelectTrigger>
                        <SelectContent position="popper">
                          {deals.map((d) => (
                            <SelectItem key={d.id} value={d.id}>
                              {d.title}
                            </SelectItem>
                          ))}
                          <SelectItem value="__new__">
                            + Criar novo deal
                          </SelectItem>
                        </SelectContent>
                      </Select>
                      {dealId && dealId !== "__new__" && (
                        <p className="text-[11px] text-[#7b7b78] mt-1">
                          O deal será movido para Fechado Ganho automaticamente.
                        </p>
                      )}
                    </>
                  )}

                  {/* Inline new deal form */}
                  {creatingDeal && (
                    <div className="space-y-3 mt-1 p-3 bg-[#faf9f6] border border-[#dedbd6] rounded-[4px]">
                      <div>
                        <label className={fieldLabel}>Título do Deal *</label>
                        <Input
                          type="text"
                          value={newDealTitle}
                          onChange={(e) => setNewDealTitle(e.target.value)}
                          placeholder="Ex: Proposta Café 5kg"
                          className={fieldInput}
                        />
                      </div>
                      <div>
                        <label className={fieldLabel}>Funil *</label>
                        <Select
                          value={newDealPipeline || undefined}
                          onValueChange={setNewDealPipeline}
                        >
                          <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                            <SelectValue placeholder="Selecione o funil" />
                          </SelectTrigger>
                          <SelectContent position="popper">
                            {pipelines.map((p) => (
                              <SelectItem key={p.id} value={p.id}>
                                {p.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setCreatingDeal(false);
                          setNewDealTitle("");
                          setNewDealPipeline("");
                        }}
                        className="text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors underline underline-offset-2"
                      >
                        Cancelar novo deal
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Notes */}
          <div>
            <label className={fieldLabel}>Observação</label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Observações opcionais"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0 resize-none min-h-0"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-[12px] text-red-600">{error}</p>
          )}

          {/* Actions */}
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
              className="flex-1 py-2 text-[13px] font-medium text-white rounded-[4px] transition-colors bg-[#1f9d57] hover:bg-[#1b8a4c] disabled:bg-[#7b7b78]"
            >
              {saving ? "Salvando..." : isEditing ? "Salvar" : "Registrar Venda"}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

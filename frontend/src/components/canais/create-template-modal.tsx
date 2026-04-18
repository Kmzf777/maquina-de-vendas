"use client";

import { useState, useEffect } from "react";

interface Channel {
  id: string;
  name: string;
  provider: string;
  is_active: boolean;
}

interface CreateTemplateModalProps {
  channelId?: string;
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

type ModalStep = "form" | "review";

type ButtonItem = { id: string; text: string };

const EMPTY_FORM = {
  name: "",
  language: "pt_BR",
  category: "UTILITY" as "UTILITY" | "MARKETING",
  bodyText: "",
};

export function CreateTemplateModal({ channelId, open, onClose, onCreated }: CreateTemplateModalProps) {
  const [step, setStep] = useState<ModalStep>("form");
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [pendingTemplateId, setPendingTemplateId] = useState<string | null>(null);
  const [suggestedCategory, setSuggestedCategory] = useState<string | null>(null);

  // Channel selection (used when no channelId prop is provided)
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [buttons, setButtons] = useState<ButtonItem[]>([]);

  useEffect(() => {
    if (!open || channelId) return;
    fetch("/api/channels")
      .then((r) => r.json())
      .then((d) => {
        const meta = (Array.isArray(d) ? d : d.data || []).filter(
          (c: Channel) => c.provider === "meta_cloud" && c.is_active
        );
        setChannels(meta);
        if (meta.length === 1) setSelectedChannelId(meta[0].id);
      })
      .catch(() => setChannels([]));
  }, [open, channelId]);

  if (!open) return null;

  const activeChannelId = channelId ?? selectedChannelId;

  const addButton = () => {
    setButtons(prev =>
      prev.length < 3 ? [...prev, { id: crypto.randomUUID(), text: "" }] : prev
    );
  };

  const updateButton = (id: string, value: string) => {
    const sanitized = value.replace(/[{}]/g, "");
    setButtons(prev =>
      prev.map(b => b.id === id ? { ...b, text: sanitized } : b)
    );
  };

  const removeButton = (id: string) => {
    setButtons(prev => prev.filter(b => b.id !== id));
  };

  const resetAndClose = () => {
    setStep("form");
    setForm(EMPTY_FORM);
    setButtons([]);
    setError(null);
    setPendingTemplateId(null);
    setSuggestedCategory(null);
    setSelectedChannelId("");
    onClose();
  };

  const handleSubmit = async () => {
    if (!activeChannelId) {
      setError("Selecione um canal.");
      return;
    }
    if (!form.name.trim() || !form.bodyText.trim()) {
      setError("Nome e texto do corpo são obrigatórios.");
      return;
    }

    const validTexts = buttons.map(b => b.text.trim()).filter(Boolean);

    if (new Set(validTexts).size !== validTexts.length) {
      setError("Botões não podem ter textos duplicados.");
      return;
    }

    const VARIABLE_RE = /\{\{\d+\}\}/;
    if (validTexts.some(t => VARIABLE_RE.test(t))) {
      setError("Botões não podem conter variáveis como {{1}}.");
      return;
    }

    setSaving(true);
    setError(null);

    const body = {
      name: form.name.trim(),
      language: form.language,
      category: form.category,
      components: [
        { type: "BODY", text: form.bodyText.trim() },
        ...(validTexts.length > 0
          ? [{ type: "BUTTONS", buttons: validTexts.map(text => ({ type: "QUICK_REPLY", text })) }]
          : []),
      ],
    };

    try {
      const res = await fetch(`/api/channels/${activeChannelId}/templates`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (res.status === 201) {
        onCreated();
        resetAndClose();
        return;
      }

      if (res.status === 202) {
        setPendingTemplateId(data.template?.id ?? null);
        setSuggestedCategory(data.suggested_category ?? null);
        setStep("review");
        return;
      }

      setError(data?.detail || data?.error || "Erro ao criar template.");
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };

  const handleConfirm = async () => {
    if (!pendingTemplateId) return;
    setSaving(true);
    setError(null);

    try {
      const res = await fetch(`/api/channels/${activeChannelId}/templates/${pendingTemplateId}/confirm`, {
        method: "POST",
      });

      if (res.ok) {
        onCreated();
        resetAndClose();
        return;
      }

      const data = await res.json();
      setError(data?.detail || data?.error || "Erro ao confirmar template.");
    } catch {
      setError("Erro de conexão. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    if (!pendingTemplateId) { resetAndClose(); return; }
    setSaving(true);
    setError(null);

    try {
      await fetch(`/api/channels/${activeChannelId}/templates/${pendingTemplateId}`, {
        method: "DELETE",
      });
    } catch { /* ignore */ }

    setSaving(false);
    resetAndClose();
  };

  return (
    <div
      className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
      onClick={resetAndClose}
    >
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg max-h-[90vh] overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-[14px] font-normal text-[#111111]">
            {step === "form" ? "Criar Template WhatsApp" : "Revisão de Categoria"}
          </h2>
          <button
            onClick={resetAndClose}
            className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors"
          >
            &times;
          </button>
        </div>

        {step === "form" && (
          <div className="space-y-4">
            {/* Canal selector — only shown when no channelId prop */}
            {!channelId && (
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Canal (Meta Cloud)
                </label>
                <select
                  value={selectedChannelId}
                  onChange={(e) => setSelectedChannelId(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="">Selecione um canal</option>
                  {channels.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                {channels.length === 0 && (
                  <p className="text-[11px] text-[#7b7b78] mt-1">Nenhum canal Meta Cloud ativo encontrado.</p>
                )}
              </div>
            )}

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Nome do Template
              </label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase().replace(/\s/g, "_") })}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                placeholder="ex: order_update_v1"
              />
              <p className="text-[11px] text-[#7b7b78] mt-1">Apenas letras minúsculas, números e underscores.</p>
            </div>

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Idioma
              </label>
              <select
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="pt_BR">Português (Brasil)</option>
                <option value="en_US">English (US)</option>
                <option value="es">Español</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Categoria
              </label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as "UTILITY" | "MARKETING" })}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="UTILITY">UTILITY — Atualizações transacionais</option>
                <option value="MARKETING">MARKETING — Promoções e ofertas</option>
              </select>
            </div>

            <div>
              <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Texto do Corpo (BODY)
              </label>
              <textarea
                value={form.bodyText}
                onChange={(e) => setForm({ ...form, bodyText: e.target.value })}
                rows={4}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full resize-none"
                placeholder="Olá {{1}}, seu pedido foi atualizado."
              />
              <p className="text-[11px] text-[#7b7b78] mt-1">Use &#123;&#123;1&#125;&#125;, &#123;&#123;2&#125;&#125;, etc. para variáveis.</p>
            </div>

            {error && (
              <p className="text-[12px] text-[#c41c1c]">{error}</p>
            )}

            <div className="flex justify-end gap-3 mt-2">
              <button
                onClick={resetAndClose}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
              >
                Cancelar
              </button>
              <button
                onClick={handleSubmit}
                disabled={saving || !form.name.trim() || !form.bodyText.trim() || !activeChannelId}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                {saving ? "Enviando..." : "Criar Template"}
              </button>
            </div>
          </div>
        )}

        {step === "review" && (
          <div className="space-y-4">
            <div className="p-4 bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]">
              <p className="text-[14px] text-[#111111] mb-2">
                A Meta reclassificou seu template.
              </p>
              <p className="text-[14px] text-[#7b7b78]">
                Categoria solicitada: <span className="text-[#111111]">{form.category}</span>
              </p>
              <p className="text-[14px] text-[#7b7b78]">
                Categoria sugerida pela Meta: <span className="text-[#111111] font-medium">{suggestedCategory}</span>
              </p>
              <p className="text-[13px] text-[#7b7b78] mt-3">
                Confirmar aceita a nova categoria. Cancelar descarta o template.
              </p>
            </div>

            {error && (
              <p className="text-[12px] text-[#c41c1c]">{error}</p>
            )}

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setStep("form")}
                disabled={saving}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-50"
              >
                Voltar
              </button>
              <button
                onClick={handleConfirm}
                disabled={saving}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                {saving ? "Confirmando..." : "Confirmar Categoria"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

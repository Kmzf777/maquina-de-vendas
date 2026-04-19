"use client";

import { useState, useEffect, useRef } from "react";
import type { Channel } from "@/lib/types";

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  buttons: Array<{ type: string; text: string }>;
  params: string[];
}

interface SavedPhone {
  id: string;
  phone: string;
  label: string | null;
}

interface QuickSendModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
}

const DYNAMIC_VARS: Record<string, string> = {
  primeiro_nome: "{{first_name}}",
  first_name: "{{first_name}}",
  nome: "{{first_name}}",
  name: "{{first_name}}",
};

function defaultValue(paramName: string): string {
  return DYNAMIC_VARS[paramName.toLowerCase()] ?? "";
}

function normalizePhone(raw: string): string {
  return raw.replace(/\D/g, "");
}

function isValidPhone(normalized: string): boolean {
  return normalized.length >= 12 && normalized.length <= 13;
}

function renderInteractiveBody(
  body: string,
  values: Record<string, string>,
  onChange: (varName: string, value: string) => void
) {
  return body.split(/(\{\{[^}]+\}\})/g).map((part, i) => {
    const match = part.match(/^\{\{([^}]+)\}\}$/);
    if (match) {
      const varName = match[1];
      const value = values[varName] ?? "";
      const isEmpty = value.trim() === "";
      return (
        <input
          key={i}
          type="text"
          value={value}
          onChange={(e) => onChange(varName, e.target.value)}
          placeholder={varName}
          size={Math.max((value || varName).length + 1, 5)}
          className={`inline border-0 border-b-2 bg-transparent focus:outline-none text-[13px] px-0.5 mx-0.5 align-baseline transition-colors ${
            isEmpty
              ? "border-[#c41c1c]/60 placeholder:text-[#c41c1c]/50 text-[#c41c1c]"
              : "border-[#111111] text-[#111111] font-medium"
          }`}
        />
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export function QuickSendModal({ open, onClose, onSuccess }: QuickSendModalProps) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [templateVarValues, setTemplateVarValues] = useState<Record<string, string>>({});
  const [phones, setPhones] = useState<string[]>([""]);
  const [savedPhones, setSavedPhones] = useState<SavedPhone[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const phoneKeysRef = useRef<number[]>([0]);
  const nextKeyRef = useRef(1);

  useEffect(() => {
    if (!open) return;
    fetch("/api/channels")
      .then((r) => r.json())
      .then((d) => {
        const metaChannels = (Array.isArray(d) ? d : d.data || []).filter(
          (c: Channel) => c.provider === "meta_cloud" && c.is_active
        );
        setChannels(metaChannels);
      })
      .catch(() => {});
    fetch("/api/quick-send-phones")
      .then((r) => r.json())
      .then((d) => setSavedPhones(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!channelId) {
      setTemplates([]);
      setSelectedTemplate(null);
      return;
    }
    setLoadingTemplates(true);
    setSelectedTemplate(null);
    setTemplateVarValues({});
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false));
  }, [channelId]);

  const handleSelectTemplate = (key: string) => {
    if (!key) {
      setSelectedTemplate(null);
      setTemplateVarValues({});
      return;
    }
    const [tname, lang] = key.split("|");
    const tpl = templates.find((t) => t.name === tname && t.language === lang) ?? null;
    setSelectedTemplate(tpl);
    if (tpl) {
      const bodyVars = (tpl.body.match(/\{\{([^}]+)\}\}/g) || []).map((m) =>
        m.replace(/^\{\{|\}\}$/g, "")
      );
      const allVars = [...new Set([...tpl.params, ...bodyVars])];
      const defaults: Record<string, string> = {};
      allVars.forEach((p) => {
        defaults[p] = defaultValue(p);
      });
      setTemplateVarValues(defaults);
    }
  };

  const updatePhone = (i: number, val: string) =>
    setPhones((prev) => prev.map((p, idx) => (idx === i ? val : p)));

  const removePhone = (i: number) => {
    phoneKeysRef.current = phoneKeysRef.current.filter((_, idx) => idx !== i);
    setPhones((prev) => prev.filter((_, idx) => idx !== i));
  };

  const addSavedPhone = (phone: string) => {
    setPhones((prev) => {
      if (prev.includes(phone)) return prev;
      const emptyIdx = prev.findIndex((p) => p === "");
      if (emptyIdx >= 0) {
        return prev.map((p, idx) => (idx === emptyIdx ? phone : p));
      }
      phoneKeysRef.current = [...phoneKeysRef.current, nextKeyRef.current++];
      return [...prev, phone];
    });
  };

  const savePhone = async (raw: string) => {
    const phone = normalizePhone(raw);
    if (!isValidPhone(phone)) return;
    if (savedPhones.some((s) => s.phone === phone)) return;
    const res = await fetch("/api/quick-send-phones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone }),
    });
    if (res.ok) {
      const saved: SavedPhone = await res.json();
      setSavedPhones((prev) => [saved, ...prev]);
    }
  };

  const validPhones = phones
    .map(normalizePhone)
    .filter(isValidPhone)
    .filter((p, i, arr) => arr.indexOf(p) === i);

  const bodyVars = selectedTemplate
    ? [...new Set(
        (selectedTemplate.body.match(/\{\{([^}]+)\}\}/g) || []).map((m) =>
          m.replace(/^\{\{|\}\}$/g, "")
        )
      )]
    : [];
  const allTemplateVars = [...new Set([...(selectedTemplate?.params ?? []), ...bodyVars])];
  const allVarsFilled =
    !selectedTemplate ||
    allTemplateVars.length === 0 ||
    allTemplateVars.every((p) => (templateVarValues[p] ?? "").trim() !== "");

  const canSend = channelId !== "" && selectedTemplate !== null && validPhones.length > 0 && allVarsFilled;

  const handleSend = async () => {
    if (!selectedTemplate || !canSend) return;
    setSending(true);
    setError(null);

    try {
      const now = new Date();
      const dateStr =
        now.toLocaleDateString("pt-BR") +
        " " +
        now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      const broadcastName = `Disparo Rápido — ${selectedTemplate.name} — ${dateStr}`;

      const bRes = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: broadcastName,
          channel_id: channelId,
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: Object.keys(templateVarValues).length
            ? templateVarValues
            : null,
          send_interval_min: 0,
          send_interval_max: 0,
        }),
      });
      if (!bRes.ok) throw new Error("Erro ao criar disparo");
      const broadcast: { id: string } = await bRes.json();

      const leadIds: string[] = [];
      for (const phone of validPhones) {
        const lRes = await fetch("/api/leads/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phone }),
        });
        if (!lRes.ok) throw new Error(`Erro ao resolver lead para ${phone}`);
        const lead: { id: string } = await lRes.json();
        leadIds.push(lead.id);
      }

      const aRes = await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_ids: leadIds }),
      });
      if (!aRes.ok) throw new Error("Erro ao associar leads ao disparo");

      const sRes = await fetch(`/api/broadcasts/${broadcast.id}/start`, { method: "POST" });
      if (!sRes.ok) throw new Error("Erro ao iniciar disparo");

      onSuccess(validPhones.length);
      handleClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setSending(false);
    }
  };

  const handleClose = () => {
    setChannelId("");
    setTemplates([]);
    setSelectedTemplate(null);
    setTemplateVarValues({});
    phoneKeysRef.current = [nextKeyRef.current++];
    setPhones([""]);
    setError(null);
    onClose();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg max-h-[85vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between">
          <h2 className="text-[14px] font-normal text-[#111111]">Disparo Rápido</h2>
          <button
            onClick={handleClose}
            className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors"
          >
            &times;
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
              Instância
            </label>
            <select
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
            >
              <option value="">Selecionar instância...</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.phone})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
              Template
              {loadingTemplates && (
                <span className="ml-2 text-[#7b7b78] normal-case font-normal">
                  carregando...
                </span>
              )}
            </label>
            {!channelId ? (
              <p className="text-[12px] text-[#7b7b78] italic">
                Selecione uma instância para ver os templates disponíveis
              </p>
            ) : loadingTemplates ? (
              <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#7b7b78]">
                Buscando templates...
              </div>
            ) : templates.length === 0 ? (
              <p className="text-[12px] text-[#c41c1c]">
                Nenhum template aprovado encontrado para esta instância
              </p>
            ) : (
              <select
                value={
                  selectedTemplate
                    ? `${selectedTemplate.name}|${selectedTemplate.language}`
                    : ""
                }
                onChange={(e) => handleSelectTemplate(e.target.value)}
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
              >
                <option value="">Selecionar template...</option>
                {templates.map((t) => (
                  <option
                    key={`${t.name}|${t.language}`}
                    value={`${t.name}|${t.language}`}
                  >
                    {t.name} ({t.language}){t.category ? ` · ${t.category}` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>

          {selectedTemplate && selectedTemplate.body && (
            <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 space-y-2">
              <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                Preview — preencha as variáveis diretamente no texto
                {allTemplateVars.length > 0 && (
                  <span className="ml-1 normal-case font-normal text-[#c41c1c]">
                    ({allTemplateVars.filter((p) => (templateVarValues[p] ?? "").trim() === "").length} pendente
                    {allTemplateVars.filter((p) => (templateVarValues[p] ?? "").trim() === "").length !== 1 ? "s" : ""})
                  </span>
                )}
              </p>
              <div className="bg-white border border-[#dedbd6] rounded-[6px] px-4 py-3 text-[13px] text-[#111111] leading-relaxed whitespace-pre-wrap">
                {renderInteractiveBody(
                  selectedTemplate.body,
                  templateVarValues,
                  (varName, value) =>
                    setTemplateVarValues((prev) => ({ ...prev, [varName]: value }))
                )}
              </div>
              {selectedTemplate.buttons.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {selectedTemplate.buttons.map((btn, i) => (
                    <span
                      key={i}
                      className="text-[12px] border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[#7b7b78] bg-white"
                    >
                      {btn.text}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          <div>
            <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
              Números de Destino
            </label>
            <div className="space-y-2">
              {phones.map((phone, i) => {
                const normalized = normalizePhone(phone);
                const alreadySaved = savedPhones.some((s) => s.phone === normalized);
                return (
                  <div key={phoneKeysRef.current[i]} className="flex gap-2 items-center">
                    <input
                      value={phone}
                      onChange={(e) => updatePhone(i, e.target.value)}
                      placeholder="5534996652412"
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
                    />
                    <button
                      onClick={() => savePhone(phone)}
                      disabled={!isValidPhone(normalized) || alreadySaved}
                      className="text-[12px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] px-2 py-1.5 hover:border-[#111111] hover:text-[#111111] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                    >
                      {alreadySaved ? "Salvo" : "Salvar"}
                    </button>
                    {phones.length > 1 && (
                      <button
                        onClick={() => removePhone(i)}
                        className="text-[#7b7b78] hover:text-[#c41c1c] transition-colors flex-shrink-0 text-lg leading-none"
                      >
                        &times;
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
            <button
              onClick={() => {
                phoneKeysRef.current = [...phoneKeysRef.current, nextKeyRef.current++];
                setPhones((prev) => [...prev, ""]);
              }}
              className="mt-2 text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors"
            >
              + Adicionar número
            </button>
          </div>

          {savedPhones.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
                Números salvos
              </p>
              <div className="flex flex-wrap gap-2">
                {savedPhones.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => addSavedPhone(s.phone)}
                    className="text-[12px] bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] px-2 py-1 hover:border-[#111111] transition-colors"
                  >
                    {s.phone}
                  </button>
                ))}
              </div>
            </div>
          )}

          {error && (
            <p className="text-[13px] text-[#c41c1c] bg-[#c41c1c]/5 border border-[#c41c1c]/20 rounded-[6px] px-3 py-2">
              {error}
            </p>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-end gap-2">
          <button
            onClick={handleClose}
            className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
          >
            Cancelar
          </button>
          <button
            onClick={handleSend}
            disabled={!canSend || sending}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
          >
            {sending ? "Enviando..." : "Enviar →"}
          </button>
        </div>
      </div>
    </div>
  );
}

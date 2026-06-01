"use client";

import React from "react";
import { useState, useEffect } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const API_BASE = "";

interface LpWebhookSettings {
  channel_id: string;
  template_name: string;
  language_code: string;
  delay_minutes: number;
}

interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: string;
  is_active: boolean;
}

interface TemplateParam {
  index: number;
  paramName: string;
  example: string;
}

interface TemplateHeader {
  type: "TEXT" | "IMAGE" | "VIDEO" | "DOCUMENT";
  text?: string;
  example?: string;
}

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body?: string;
  params?: TemplateParam[];
  paramsType?: "positional" | "named" | "none";
  header?: TemplateHeader | null;
  footer?: string | null;
  buttons?: { type: string; text: string }[];
}

// ─── Category badge config ─────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  marketing:      { label: "Marketing",      color: "#c2590a", bg: "#fff3e8" },
  utility:        { label: "Utilidade",       color: "#1d5fa8", bg: "#e8f1fc" },
  authentication: { label: "Autenticação",    color: "#6b27a8", bg: "#f2eafc" },
};

// ─── Inline template preview ───────────────────────────────────────────────────

function TemplateInlinePreview({ template }: { template: MetaTemplate }) {
  const cat =
    CATEGORY_CONFIG[template.category?.toLowerCase()] ?? CATEGORY_CONFIG.utility;

  const renderBody = () => {
    if (!template.body) return null;
    const raw = template.body;
    const segments = raw.split(/(\{\{[\w]+\}\})/g);
    return segments.map((seg, i) => {
      if (/^\{\{[\w]+\}\}$/.test(seg)) {
        return (
          <span
            key={i}
            className="inline-flex items-center px-1 rounded text-[12px] font-medium text-[#7a5a00] bg-[#fff8e0]"
          >
            {seg}
          </span>
        );
      }
      return <React.Fragment key={i}>{seg}</React.Fragment>;
    });
  };

  const hasMediaHeader = template.header != null && template.header.type !== "TEXT";

  return (
    <div className="mt-3 border border-[#dedbd6] rounded-[8px] overflow-hidden bg-[#faf9f6]">
      {/* Category + name bar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[#faf9f6] border-b border-[#dedbd6]">
        {template.category && (
          <span
            className="text-[10px] font-semibold uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]"
            style={{ color: cat.color, backgroundColor: cat.bg }}
          >
            {cat.label}
          </span>
        )}
        <span className="text-[12px] text-[#7b7b78] truncate">{template.name}</span>
        <span className="text-[10px] text-[#b0aca6] ml-auto">{template.language}</span>
      </div>

      {/* WhatsApp bubble */}
      <div className="px-3 py-2.5 bg-[#ece5dd]">
        <div className="max-w-[85%] bg-white rounded-[8px] rounded-tl-none shadow-sm overflow-hidden">
          {/* Media header placeholder */}
          {hasMediaHeader && (
            <div className="w-full h-14 bg-[#d0ccc5] flex items-center justify-center border-b border-[#e0dbd4]">
              <span className="text-[11px] text-[#7b7b78] uppercase tracking-[0.5px]">
                {template.header!.type === "IMAGE"
                  ? "Imagem"
                  : template.header!.type === "VIDEO"
                  ? "Vídeo"
                  : "Documento"}
              </span>
            </div>
          )}

          {/* Text header */}
          {template.header?.type === "TEXT" && template.header.text && (
            <div className="px-3 pt-2.5 pb-0.5">
              <p className="text-[13px] font-semibold text-[#111111] leading-snug">
                {template.header.text}
              </p>
            </div>
          )}

          {/* Body */}
          {template.body && (
            <div className="px-3 py-2.5">
              <p className="text-[13px] text-[#111111] leading-relaxed whitespace-pre-wrap">
                {renderBody()}
              </p>
            </div>
          )}

          {/* Footer */}
          {template.footer && (
            <div className="px-3 pb-2 -mt-1">
              <p className="text-[11px] text-[#7b7b78] italic">{template.footer}</p>
            </div>
          )}

          {/* Timestamp stub */}
          <div className="flex justify-end px-3 pb-1.5 -mt-0.5">
            <span className="text-[10px] text-[#b0aca6]">agora</span>
          </div>
        </div>
      </div>

      {/* Buttons row */}
      {template.buttons && template.buttons.length > 0 && (
        <div className="bg-[#ece5dd] border-t border-[#d9d3c9] px-3 pb-2.5 pt-0 flex flex-wrap gap-1.5">
          {template.buttons.map((btn, i) => (
            <div
              key={i}
              className="max-w-[85%] bg-white rounded-[6px] shadow-sm px-3 py-1.5 text-center w-full"
            >
              <span className="text-[12px] text-[#1d8cdb] font-medium">{btn.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Tab ────────────────────────────────────────────────────────────────

export function LpWebhookTab() {
  const [settings, setSettings] = useState<LpWebhookSettings>({
    channel_id: "",
    template_name: "",
    language_code: "pt_BR",
    delay_minutes: 15,
  });
  const [channels, setChannels] = useState<Channel[]>([]);
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateLoadError, setTemplateLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/lp-webhook/settings`).then((r) => r.json()),
      fetch(`${API_BASE}/api/channels`).then((r) => r.json()),
    ])
      .then(([settingsData, channelsData]) => {
        setSettings({
          channel_id: settingsData.channel_id ?? "",
          template_name: settingsData.template_name ?? "",
          language_code: settingsData.language_code ?? "pt_BR",
          delay_minutes: settingsData.delay_minutes ?? 15,
        });
        setChannels(Array.isArray(channelsData) ? channelsData : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // Busca templates quando o canal muda
  useEffect(() => {
    if (!settings.channel_id) {
      setTemplates([]);
      return;
    }
    setLoadingTemplates(true);
    setTemplateLoadError(null);
    fetch(`${API_BASE}/api/channels/${settings.channel_id}/templates`)
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "Erro ao carregar templates");
        return d;
      })
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .catch((err) => {
        setTemplates([]);
        setTemplateLoadError(err instanceof Error ? err.message : "Erro ao carregar templates");
      })
      .finally(() => setLoadingTemplates(false));
  }, [settings.channel_id]);

  const handleTemplateSelect = (value: string) => {
    const [name, language] = value.split("|");
    setSettings((prev) => ({
      ...prev,
      template_name: name,
      language_code: language,
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`${API_BASE}/api/lp-webhook/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      console.error("Failed to save lp-webhook settings:", e);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] h-16 animate-pulse"
          />
        ))}
      </div>
    );
  }

  const selectedTemplateKey =
    settings.template_name && settings.language_code
      ? `${settings.template_name}|${settings.language_code}`
      : "";

  const selectedTemplate = templates.find(
    (t) => `${t.name}|${t.language}` === selectedTemplateKey
  ) ?? null;

  return (
    <div className="space-y-6">
      <p className="text-[14px] text-[#7b7b78]">
        Configure o canal e o template usado para disparar mensagens automaticas
        quando um lead chega pela landing page.
      </p>

      {/* Main settings card */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
        {/* Channel select */}
        <div className="space-y-1.5">
          <Label
            htmlFor="lp-channel"
            className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]"
          >
            Canal (número da Valéria)
          </Label>
          <Select
            value={settings.channel_id}
            onValueChange={(val) =>
              setSettings((prev) => ({ ...prev, channel_id: val, template_name: "", language_code: "pt_BR" }))
            }
          >
            <SelectTrigger
              id="lp-channel"
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full h-auto"
            >
              <SelectValue placeholder="Selecione um canal..." />
            </SelectTrigger>
            <SelectContent>
              {channels.length === 0 ? (
                <SelectItem value="__none__" disabled>
                  Nenhum canal disponivel
                </SelectItem>
              ) : (
                channels.map((ch) => (
                  <SelectItem key={ch.id} value={ch.id}>
                    {ch.name} — {ch.phone}
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        </div>

        {/* Template select */}
        <div className="space-y-1.5">
          <Label
            htmlFor="lp-template"
            className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]"
          >
            Nome do Template
            {loadingTemplates && (
              <span className="ml-2 normal-case font-normal text-[#7b7b78]">
                carregando...
              </span>
            )}
          </Label>
          {!settings.channel_id ? (
            <p className="text-[12px] text-[#7b7b78] italic">
              Selecione um canal para ver os templates disponíveis
            </p>
          ) : templateLoadError ? (
            <p className="text-[12px] text-[#c41c1c]">{templateLoadError}</p>
          ) : (
            <Select
              value={selectedTemplateKey}
              onValueChange={handleTemplateSelect}
              disabled={loadingTemplates}
            >
              <SelectTrigger
                id="lp-template"
                className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full h-auto"
              >
                <SelectValue
                  placeholder={
                    loadingTemplates ? "Buscando templates..." : "Selecionar template..."
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {templates.length === 0 ? (
                  <SelectItem value="__none__" disabled>
                    Nenhum template aprovado encontrado
                  </SelectItem>
                ) : (
                  templates.map((t) => (
                    <SelectItem key={`${t.name}|${t.language}`} value={`${t.name}|${t.language}`}>
                      {t.name} ({t.language}){t.category ? ` · ${t.category}` : ""}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          )}

          {/* Inline preview — shown only when a template is selected */}
          {selectedTemplate && <TemplateInlinePreview template={selectedTemplate} />}
        </div>

        {/* Language code + Delay — side by side */}
        <div className="flex gap-4">
          <div className="flex-1 space-y-1.5">
            <Label
              htmlFor="lp-language"
              className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]"
            >
              Idioma do Template
            </Label>
            <Input
              id="lp-language"
              type="text"
              placeholder="pt_BR"
              value={settings.language_code}
              onChange={(e) =>
                setSettings((prev) => ({
                  ...prev,
                  language_code: e.target.value,
                }))
              }
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
            />
          </div>

          <div className="flex-1 space-y-1.5">
            <Label
              htmlFor="lp-delay"
              className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]"
            >
              Delay (minutos)
            </Label>
            <Input
              id="lp-delay"
              type="number"
              min={1}
              max={1440}
              value={settings.delay_minutes}
              onChange={(e) =>
                setSettings((prev) => ({
                  ...prev,
                  delay_minutes: parseInt(e.target.value, 10) || 1,
                }))
              }
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
            />
          </div>
        </div>

        {/* Save row */}
        <div className="flex items-center gap-4 pt-1">
          <Button
            onClick={handleSave}
            disabled={saving}
            className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50 h-auto"
          >
            {saving ? "Salvando..." : "Salvar"}
          </Button>
          {saved && (
            <span className="text-[13px] text-[#7b7b78]">
              Configurações salvas.
            </span>
          )}
        </div>
      </div>

      {/* Read-only endpoint URL */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
          Endpoint para a Landing Page
        </p>
        <p className="text-[13px] text-[#7b7b78] mb-3">
          Configure este URL no formulario da sua landing page como destino do
          webhook.
        </p>
        <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 flex items-center justify-between gap-2">
          <code className="text-[13px] text-[#111111] font-mono select-all break-all">
            POST https://crm.canastrainteligencia.com/webhook/landing-page
          </code>
        </div>
      </div>
    </div>
  );
}

"use client";

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

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
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

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
import type { TemplatePreset } from "@/lib/types";

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

// ─── Template Presets Section ───────────────────────────────────────────────

interface PresetEditState {
  name: string;
  template_name: string;
  variables: string; // JSON string edited in textarea
}

function emptyPresetEdit(): PresetEditState {
  return { name: "", template_name: "", variables: "{}" };
}

function presetToEditState(p: TemplatePreset): PresetEditState {
  return {
    name: p.name,
    template_name: p.template_name,
    variables: JSON.stringify(p.variables ?? {}, null, 2),
  };
}

function VariablesDisplay({ variables }: { variables: Record<string, unknown> }) {
  const entries = Object.entries(variables);
  if (entries.length === 0) return <span className="text-[#7b7b78] italic">sem variáveis</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="inline-flex items-center gap-1 bg-white border border-[#dedbd6] rounded-[4px] px-2 py-0.5 text-[12px] text-[#111111]"
        >
          <span className="text-[#7b7b78]">{k}:</span>
          <span className="font-mono">{String(v)}</span>
        </span>
      ))}
    </span>
  );
}

function PresetsSection() {
  const [presets, setPresets] = useState<TemplatePreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editState, setEditState] = useState<PresetEditState>(emptyPresetEdit());
  const [showCreate, setShowCreate] = useState(false);
  const [createState, setCreateState] = useState<PresetEditState>(emptyPresetEdit());
  const [savingId, setSavingId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [variablesError, setVariablesError] = useState<string | null>(null);
  const [createVariablesError, setCreateVariablesError] = useState<string | null>(null);

  useEffect(() => {
    loadPresets();
  }, []);

  async function loadPresets() {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/template-presets`);
      if (res.ok) setPresets(await res.json());
    } finally {
      setLoading(false);
    }
  }

  function startEdit(preset: TemplatePreset) {
    setEditingId(preset.id);
    setEditState(presetToEditState(preset));
    setVariablesError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setVariablesError(null);
  }

  async function handleSaveEdit(id: string) {
    let parsedVars: Record<string, unknown>;
    try {
      parsedVars = JSON.parse(editState.variables);
    } catch {
      setVariablesError("JSON inválido. Corrija antes de salvar.");
      return;
    }
    setSavingId(id);
    try {
      const res = await fetch(`${API_BASE}/api/template-presets/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: editState.name.trim(),
          template_name: editState.template_name.trim(),
          variables: parsedVars,
        }),
      });
      if (res.ok) {
        setEditingId(null);
        await loadPresets();
      }
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Excluir este preset? Esta ação não pode ser desfeita.")) return;
    await fetch(`${API_BASE}/api/template-presets/${id}`, { method: "DELETE" });
    await loadPresets();
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    let parsedVars: Record<string, unknown>;
    try {
      parsedVars = JSON.parse(createState.variables);
    } catch {
      setCreateVariablesError("JSON inválido. Corrija antes de salvar.");
      return;
    }
    setCreating(true);
    try {
      const res = await fetch(`${API_BASE}/api/template-presets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: createState.name.trim(),
          template_name: createState.template_name.trim(),
          variables: parsedVars,
        }),
      });
      if (res.ok) {
        setShowCreate(false);
        setCreateState(emptyPresetEdit());
        setCreateVariablesError(null);
        await loadPresets();
      }
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Templates Cadastrados
          </p>
          <p className="text-[13px] text-[#7b7b78] mt-0.5">
            Presets de template com variáveis pré-configuradas para uso nos disparos.
          </p>
        </div>
        <button
          onClick={() => { setShowCreate(true); setCreateState(emptyPresetEdit()); setCreateVariablesError(null); }}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] whitespace-nowrap"
        >
          + Novo Preset
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <form
          onSubmit={handleCreate}
          className="mb-4 p-4 bg-white border border-[#dedbd6] rounded-[8px] space-y-3"
        >
          <p className="text-[12px] font-medium text-[#111111] uppercase tracking-[0.5px]">Novo preset</p>
          <div className="space-y-1.5">
            <Label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
              Nome do Preset
            </Label>
            <Input
              type="text"
              placeholder="ex: Boas-vindas LP Atacado"
              value={createState.name}
              onChange={(e) => setCreateState((p) => ({ ...p, name: e.target.value }))}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
              autoFocus
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
              Nome do Template (Meta)
            </Label>
            <Input
              type="text"
              placeholder="ex: boas_vindas_lp"
              value={createState.template_name}
              onChange={(e) => setCreateState((p) => ({ ...p, template_name: e.target.value }))}
              className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
              Variáveis (JSON)
            </Label>
            <textarea
              value={createState.variables}
              onChange={(e) => { setCreateState((p) => ({ ...p, variables: e.target.value })); setCreateVariablesError(null); }}
              rows={4}
              className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] font-mono focus:border-[#111111] focus:outline-none resize-y"
              placeholder='{"1": "João", "2": "produto"}'
            />
            {createVariablesError && (
              <p className="text-[12px] text-[#c41c1c]">{createVariablesError}</p>
            )}
          </div>
          <div className="flex gap-2 pt-1">
            <Button
              type="submit"
              disabled={creating}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50 h-auto"
            >
              {creating ? "Salvando..." : "Salvar"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => { setShowCreate(false); setCreateVariablesError(null); }}
              className="border-[#dedbd6] text-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] h-auto hover:bg-[#faf9f6]"
            >
              Cancelar
            </Button>
          </div>
        </form>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-14 bg-[#dedbd6] rounded-[6px] animate-pulse" />
          ))}
        </div>
      )}

      {/* Empty */}
      {!loading && presets.length === 0 && (
        <div className="py-8 text-center">
          <p className="text-[14px] text-[#7b7b78]">Nenhum preset cadastrado.</p>
          <button
            onClick={() => setShowCreate(true)}
            className="mt-2 text-[13px] text-[#111111] underline"
          >
            Criar primeiro preset
          </button>
        </div>
      )}

      {/* Preset list */}
      {!loading && presets.length > 0 && (
        <div className="space-y-2">
          {presets.map((preset) =>
            editingId === preset.id ? (
              // ── Edit mode ──────────────────────────────────────────────────
              <div
                key={preset.id}
                className="p-4 bg-white border border-[#111111] rounded-[8px] space-y-3"
              >
                <div className="space-y-1.5">
                  <Label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                    Nome do Preset
                  </Label>
                  <Input
                    type="text"
                    value={editState.name}
                    onChange={(e) => setEditState((p) => ({ ...p, name: e.target.value }))}
                    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                    Nome do Template (Meta)
                  </Label>
                  <Input
                    type="text"
                    value={editState.template_name}
                    onChange={(e) => setEditState((p) => ({ ...p, template_name: e.target.value }))}
                    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                    Variáveis (JSON)
                  </Label>
                  <textarea
                    value={editState.variables}
                    onChange={(e) => { setEditState((p) => ({ ...p, variables: e.target.value })); setVariablesError(null); }}
                    rows={4}
                    className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] font-mono focus:border-[#111111] focus:outline-none resize-y"
                  />
                  {variablesError && (
                    <p className="text-[12px] text-[#c41c1c]">{variablesError}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button
                    onClick={() => handleSaveEdit(preset.id)}
                    disabled={savingId === preset.id}
                    className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50 h-auto"
                  >
                    {savingId === preset.id ? "Salvando..." : "Salvar"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={cancelEdit}
                    className="border-[#dedbd6] text-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] h-auto hover:bg-[#faf9f6]"
                  >
                    Cancelar
                  </Button>
                </div>
              </div>
            ) : (
              // ── View mode ──────────────────────────────────────────────────
              <div
                key={preset.id}
                className="flex items-start gap-3 py-3 px-4 bg-white border border-[#dedbd6] rounded-[8px] group"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-[14px] text-[#111111] font-medium truncate">{preset.name}</p>
                  <p className="text-[12px] text-[#7b7b78] font-mono mt-0.5 truncate">{preset.template_name}</p>
                  <div className="mt-1.5 text-[12px]">
                    <VariablesDisplay variables={preset.variables ?? {}} />
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 mt-0.5">
                  <button
                    onClick={() => startEdit(preset)}
                    className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#faf9f6] transition-colors"
                    title="Editar"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                  <button
                    onClick={() => handleDelete(preset.id)}
                    className="p-2 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] transition-colors"
                    title="Excluir"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              </div>
            )
          )}
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
              setSettings((prev) => ({ ...prev, channel_id: val }))
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

        {/* Template name */}
        <div className="space-y-1.5">
          <Label
            htmlFor="lp-template"
            className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]"
          >
            Nome do Template
          </Label>
          <Input
            id="lp-template"
            type="text"
            placeholder="ex: boas_vindas_lp"
            value={settings.template_name}
            onChange={(e) =>
              setSettings((prev) => ({ ...prev, template_name: e.target.value }))
            }
            className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none h-auto"
          />
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

      {/* Template presets */}
      <PresetsSection />

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

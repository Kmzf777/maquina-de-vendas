"use client";

import { useState, useEffect } from "react";
import type { Channel, AgentProfile } from "@/lib/types";
import { LeadSelector } from "@/components/lead-selector";

interface MetaTemplate {
  name: string;
  language: string;
  params: string[];
}

interface CreateBroadcastModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

// Variables that get auto-resolved from the lead record at send time.
const DYNAMIC_VARS: Record<string, string> = {
  primeiro_nome: "{{first_name}}",
  first_name: "{{first_name}}",
  nome: "{{first_name}}",
  name: "{{first_name}}",
};

function defaultValue(paramName: string): string {
  return DYNAMIC_VARS[paramName.toLowerCase()] ?? "";
}

export function CreateBroadcastModal({ open, onClose, onCreated }: CreateBroadcastModalProps) {
  const [step, setStep] = useState(1);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [agentProfiles, setAgentProfiles] = useState<AgentProfile[]>([]);
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [channelId, setChannelId] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [templateVarValues, setTemplateVarValues] = useState<Record<string, string>>({});
  const [agentProfileId, setAgentProfileId] = useState("");
  const [intervalMin, setIntervalMin] = useState(3);
  const [intervalMax, setIntervalMax] = useState(8);

  const [selectedLeadIds, setSelectedLeadIds] = useState<Set<string>>(new Set());
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [leadTab, setLeadTab] = useState<"crm" | "csv">("crm");

  useEffect(() => {
    if (!open) return;
    fetch("/api/channels").then((r) => r.json()).then((d) => {
      const metaChannels = (Array.isArray(d) ? d : d.data || []).filter(
        (c: Channel) => c.provider === "meta_cloud" && c.is_active
      );
      setChannels(metaChannels);
    });
    fetch("/api/agent-profiles").then((r) => r.json()).then((d) =>
      setAgentProfiles(Array.isArray(d) ? d : d.data || [])
    );
  }, [open]);

  useEffect(() => {
    if (!channelId) { setTemplates([]); setSelectedTemplate(null); return; }
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
    if (!key) { setSelectedTemplate(null); setTemplateVarValues({}); return; }
    const [tname, lang] = key.split("|");
    const tpl = templates.find((t) => t.name === tname && t.language === lang) ?? null;
    setSelectedTemplate(tpl);
    if (tpl) {
      const defaults: Record<string, string> = {};
      tpl.params.forEach((p) => { defaults[p] = defaultValue(p); });
      setTemplateVarValues(defaults);
    } else {
      setTemplateVarValues({});
    }
  };

  const handleCreate = async () => {
    if (!selectedTemplate) return;
    setSaving(true);
    try {
      const res = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          channel_id: channelId || null,
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: Object.keys(templateVarValues).length ? templateVarValues : null,
          agent_profile_id: agentProfileId || null,
          send_interval_min: intervalMin,
          send_interval_max: intervalMax,
        }),
      });
      const broadcast = await res.json();

      if (leadTab === "crm" && selectedLeadIds.size) {
        await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lead_ids: [...selectedLeadIds] }),
        });
      } else if (leadTab === "csv" && csvFile) {
        const formData = new FormData();
        formData.append("file", csvFile);
        const fastApiUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
        await fetch(`${fastApiUrl}/api/broadcasts/${broadcast.id}/import`, {
          method: "POST",
          body: formData,
        });
      }

      onCreated();
      onClose();
      resetForm();
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setStep(1);
    setName("");
    setChannelId("");
    setSelectedTemplate(null);
    setTemplates([]);
    setTemplateVarValues({});
    setAgentProfileId("");
    setSelectedLeadIds(new Set());
    setCsvFile(null);
  };

  const canAdvance =
    step === 1
      ? name.trim() !== "" && channelId !== "" && selectedTemplate !== null
      : true;

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        <div className="bg-[#1f1f1f] text-white px-6 py-4 rounded-t-2xl flex items-center justify-between">
          <h2 className="text-[16px] font-semibold">Novo Disparo — Passo {step}/3</h2>
          <button onClick={() => { onClose(); resetForm(); }} className="text-[#9ca3af] hover:text-white text-xl">&times;</button>
        </div>

        <div className="p-6 space-y-4">
          {step === 1 && (
            <>
              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Nome do disparo</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                  placeholder="Ex: Promo Black Friday"
                />
              </div>

              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Canal (Meta Cloud)</label>
                <select
                  value={channelId}
                  onChange={(e) => setChannelId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                >
                  <option value="">Selecionar canal...</option>
                  {channels.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.phone})</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">
                  Template
                  {loadingTemplates && <span className="ml-2 text-[#9ca3af] normal-case font-normal">carregando...</span>}
                </label>
                {!channelId ? (
                  <p className="text-[12px] text-[#9ca3af] italic">Selecione um canal para ver os templates disponíveis</p>
                ) : loadingTemplates ? (
                  <div className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px] text-[#9ca3af]">Buscando templates...</div>
                ) : templates.length === 0 ? (
                  <p className="text-[12px] text-red-500">Nenhum template aprovado encontrado para este canal</p>
                ) : (
                  <select
                    value={selectedTemplate ? `${selectedTemplate.name}|${selectedTemplate.language}` : ""}
                    onChange={(e) => handleSelectTemplate(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                  >
                    <option value="">Selecionar template...</option>
                    {templates.map((t) => (
                      <option key={`${t.name}|${t.language}`} value={`${t.name}|${t.language}`}>
                        {t.name} ({t.language})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {selectedTemplate && selectedTemplate.params.length > 0 && (
                <div className="bg-[#f6f7ed] rounded-xl p-4 space-y-3">
                  <p className="text-[12px] text-[#5f6368] uppercase tracking-wider font-medium">Variáveis do template</p>
                  <p className="text-[11px] text-[#9ca3af]">
                    Use <code className="bg-white px-1 rounded">{"{{first_name}}"}</code> para preencher com o nome do lead automaticamente.
                  </p>
                  {selectedTemplate.params.map((param) => (
                    <div key={param}>
                      <label className="text-[12px] text-[#5f6368] block mb-1">{param}</label>
                      <input
                        value={templateVarValues[param] ?? ""}
                        onChange={(e) =>
                          setTemplateVarValues((prev) => ({ ...prev, [param]: e.target.value }))
                        }
                        className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                        placeholder={`Valor para ${param}`}
                      />
                    </div>
                  ))}
                </div>
              )}

              <div>
                <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Agente</label>
                <select
                  value={agentProfileId}
                  onChange={(e) => setAgentProfileId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]"
                >
                  <option value="">Agente padrão do canal</option>
                  {agentProfiles.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Intervalo min (s)</label>
                  <input type="number" value={intervalMin} onChange={(e) => setIntervalMin(Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
                </div>
                <div>
                  <label className="text-[12px] text-[#5f6368] uppercase tracking-wider block mb-1">Intervalo max (s)</label>
                  <input type="number" value={intervalMax} onChange={(e) => setIntervalMax(Number(e.target.value))} className="w-full px-3 py-2 rounded-lg border border-[#e5e5dc] text-[13px]" />
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="flex gap-2 mb-4">
                <button onClick={() => setLeadTab("crm")} className={`px-3 py-1.5 rounded-lg text-[12px] font-medium ${leadTab === "crm" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] bg-[#f4f4f0]"}`}>Do CRM</button>
                <button onClick={() => setLeadTab("csv")} className={`px-3 py-1.5 rounded-lg text-[12px] font-medium ${leadTab === "csv" ? "bg-[#1f1f1f] text-white" : "text-[#5f6368] bg-[#f4f4f0]"}`}>Importar CSV</button>
              </div>
              {leadTab === "crm" ? (
                <LeadSelector selectedIds={selectedLeadIds} onSelectionChange={setSelectedLeadIds} />
              ) : (
                <div className="border-2 border-dashed border-[#e5e5dc] rounded-xl p-8 text-center">
                  <input type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} className="text-[13px]" />
                  {csvFile && <p className="text-[12px] text-[#2d6a3f] mt-2">Arquivo: {csvFile.name}</p>}
                </div>
              )}
              <p className="text-[12px] text-[#5f6368]">
                {leadTab === "crm" ? `${selectedLeadIds.size} leads selecionados` : csvFile ? "CSV pronto para envio" : "Nenhum arquivo selecionado"}
              </p>
            </>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <h3 className="text-[14px] font-semibold text-[#1f1f1f]">Revisão do disparo</h3>
              <div className="bg-[#f6f7ed] rounded-xl p-4 space-y-2 text-[13px]">
                <p><span className="text-[#5f6368]">Nome:</span> <strong>{name}</strong></p>
                <p><span className="text-[#5f6368]">Template:</span> <strong>{selectedTemplate?.name}</strong> <span className="text-[#5f6368]">({selectedTemplate?.language})</span></p>
                {Object.keys(templateVarValues).length > 0 && (
                  <div>
                    <span className="text-[#5f6368]">Variáveis:</span>
                    <ul className="ml-3 mt-1 space-y-0.5">
                      {Object.entries(templateVarValues).map(([k, v]) => (
                        <li key={k} className="text-[12px]"><span className="text-[#9ca3af]">{k}:</span> <strong>{v || <em className="text-[#9ca3af]">vazio</em>}</strong></li>
                      ))}
                    </ul>
                  </div>
                )}
                <p><span className="text-[#5f6368]">Leads:</span> <strong>{leadTab === "crm" ? selectedLeadIds.size : "CSV"}</strong></p>
                <p><span className="text-[#5f6368]">Intervalo:</span> <strong>{intervalMin}-{intervalMax}s</strong></p>
                {agentProfileId && <p><span className="text-[#5f6368]">Agente:</span> <strong>{agentProfiles.find((a) => a.id === agentProfileId)?.name}</strong></p>}
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#e5e5dc] flex justify-between">
          {step > 1 ? (
            <button onClick={() => setStep(step - 1)} className="px-4 py-2 rounded-lg text-[13px] font-medium text-[#5f6368] hover:bg-[#f6f7ed]">Voltar</button>
          ) : <div />}
          {step < 3 ? (
            <button onClick={() => setStep(step + 1)} disabled={!canAdvance} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50">Próximo</button>
          ) : (
            <button onClick={handleCreate} disabled={saving} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-[#1f1f1f] text-white hover:bg-[#333] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Disparo"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

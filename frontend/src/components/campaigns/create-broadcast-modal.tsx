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
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-2xl max-h-[85vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-[#dedbd6] flex items-center justify-between">
          <h2 className="text-[14px] font-normal text-[#111111]">Novo Disparo — Passo {step}/3</h2>
          <button onClick={() => { onClose(); resetForm(); }} className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors">&times;</button>
        </div>

        <div className="p-6 space-y-4">
          {step === 1 && (
            <>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome do disparo</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="Ex: Promo Black Friday"
                />
              </div>

              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Canal (Meta Cloud)</label>
                <select
                  value={channelId}
                  onChange={(e) => setChannelId(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="">Selecionar canal...</option>
                  {channels.map((c) => (
                    <option key={c.id} value={c.id}>{c.name} ({c.phone})</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Template
                  {loadingTemplates && <span className="ml-2 text-[#7b7b78] normal-case font-normal">carregando...</span>}
                </label>
                {!channelId ? (
                  <p className="text-[12px] text-[#7b7b78] italic">Selecione um canal para ver os templates disponíveis</p>
                ) : loadingTemplates ? (
                  <div className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#7b7b78]">Buscando templates...</div>
                ) : templates.length === 0 ? (
                  <p className="text-[12px] text-[#c41c1c]">Nenhum template aprovado encontrado para este canal</p>
                ) : (
                  <select
                    value={selectedTemplate ? `${selectedTemplate.name}|${selectedTemplate.language}` : ""}
                    onChange={(e) => handleSelectTemplate(e.target.value)}
                    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
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
                <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 space-y-3">
                  <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Variáveis do template</p>
                  <p className="text-[12px] text-[#7b7b78]">
                    Use <code className="bg-white px-1 rounded border border-[#dedbd6]">{"{{first_name}}"}</code> para preencher com o nome do lead automaticamente.
                  </p>
                  {selectedTemplate.params.map((param) => (
                    <div key={param}>
                      <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">{param}</label>
                      <input
                        value={templateVarValues[param] ?? ""}
                        onChange={(e) =>
                          setTemplateVarValues((prev) => ({ ...prev, [param]: e.target.value }))
                        }
                        className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                        placeholder={`Valor para ${param}`}
                      />
                    </div>
                  ))}
                </div>
              )}

              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Agente</label>
                <select
                  value={agentProfileId}
                  onChange={(e) => setAgentProfileId(e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="">Agente padrão do canal</option>
                  {agentProfiles.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Intervalo min (s)</label>
                  <input type="number" value={intervalMin} onChange={(e) => setIntervalMin(Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
                </div>
                <div>
                  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Intervalo max (s)</label>
                  <input type="number" value={intervalMax} onChange={(e) => setIntervalMax(Number(e.target.value))} className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full" />
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="flex border-b border-[#dedbd6] mb-4">
                <button
                  onClick={() => setLeadTab("crm")}
                  className={leadTab === "crm"
                    ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
                    : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
                >
                  Do CRM
                </button>
                <button
                  onClick={() => setLeadTab("csv")}
                  className={leadTab === "csv"
                    ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
                    : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
                >
                  Importar CSV
                </button>
              </div>
              {leadTab === "crm" ? (
                <LeadSelector selectedIds={selectedLeadIds} onSelectionChange={setSelectedLeadIds} />
              ) : (
                <div className="border-2 border-dashed border-[#dedbd6] rounded-[8px] p-8 text-center">
                  <input type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} className="text-[14px]" />
                  {csvFile && <p className="text-[12px] text-[#0bdf50] mt-2">Arquivo: {csvFile.name}</p>}
                </div>
              )}
              <p className="text-[12px] text-[#7b7b78]">
                {leadTab === "crm" ? `${selectedLeadIds.size} leads selecionados` : csvFile ? "CSV pronto para envio" : "Nenhum arquivo selecionado"}
              </p>
            </>
          )}

          {step === 3 && (
            <div className="space-y-3">
              <h3 className="text-[14px] font-normal text-[#111111]">Revisão do disparo</h3>
              <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4 space-y-2 text-[14px]">
                <p><span className="text-[#7b7b78]">Nome:</span> <strong className="font-normal text-[#111111]">{name}</strong></p>
                <p><span className="text-[#7b7b78]">Template:</span> <strong className="font-normal text-[#111111]">{selectedTemplate?.name}</strong> <span className="text-[#7b7b78]">({selectedTemplate?.language})</span></p>
                {Object.keys(templateVarValues).length > 0 && (
                  <div>
                    <span className="text-[#7b7b78]">Variáveis:</span>
                    <ul className="ml-3 mt-1 space-y-0.5">
                      {Object.entries(templateVarValues).map(([k, v]) => (
                        <li key={k} className="text-[12px]"><span className="text-[#7b7b78]">{k}:</span> <span className="text-[#111111]">{v || <em className="text-[#7b7b78]">vazio</em>}</span></li>
                      ))}
                    </ul>
                  </div>
                )}
                <p><span className="text-[#7b7b78]">Leads:</span> <span className="text-[#111111]">{leadTab === "crm" ? selectedLeadIds.size : "CSV"}</span></p>
                <p><span className="text-[#7b7b78]">Intervalo:</span> <span className="text-[#111111]">{intervalMin}-{intervalMax}s</span></p>
                {agentProfileId && <p><span className="text-[#7b7b78]">Agente:</span> <span className="text-[#111111]">{agentProfiles.find((a) => a.id === agentProfileId)?.name}</span></p>}
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#dedbd6] flex justify-between">
          {step > 1 ? (
            <button onClick={() => setStep(step - 1)} className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">Voltar</button>
          ) : <div />}
          {step < 3 ? (
            <button onClick={() => setStep(step + 1)} disabled={!canAdvance} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50">Próximo</button>
          ) : (
            <button onClick={handleCreate} disabled={saving} className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50">
              {saving ? "Criando..." : "Criar Disparo"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

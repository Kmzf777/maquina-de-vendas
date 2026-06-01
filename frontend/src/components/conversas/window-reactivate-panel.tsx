"use client";

import { useState, useEffect } from "react";
import type { Conversation } from "@/lib/types";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: { index: number; paramName: string; example: string }[];
  paramsType: "positional" | "named" | "none";
}

// Mirrors _LEAD_FIELD_TOKENS in backend/app/broadcast/worker.py
const LEAD_RESOLVERS: Record<string, (l: { name?: string | null; phone?: string; company?: string | null }) => string> = {
  primeiro_nome: (l) => (l.name ?? "").split(" ")[0],
  nome_completo: (l) => l.name ?? "",
  telefone: (l) => l.phone ?? "",
  empresa: (l) => l.company ?? "",
  first_name: (l) => (l.name ?? "").split(" ")[0],
  lead_name: (l) => l.name ?? "",
  phone: (l) => l.phone ?? "",
};

function resolveBody(
  body: string,
  params: MetaTemplate["params"],
  lead: { name?: string | null; phone?: string; company?: string | null },
  inputs: Record<string, string>
): string {
  let text = body;
  for (const param of params) {
    const value =
      LEAD_RESOLVERS[param.paramName]?.(lead) ||
      inputs[param.paramName] ||
      (param.example ? `[${param.example}]` : `{{${param.paramName}}}`);
    text = text.replaceAll(`{{${param.paramName}}}`, value);
    text = text.replaceAll(`{{${param.index}}}`, value);
  }
  return text;
}

interface CampaignEnrollmentLocal {
  id: string;
  campaign_id: string;
  status: string;
  next_execute_at: string | null;
  campaigns?: { id: string; name: string } | null;
}

interface Campaign {
  id: string;
  name: string;
  status: string;
}

interface WindowReactivatePanelProps {
  conversation: Conversation;
  onClose: () => void;
}

export function WindowReactivatePanel({ conversation, onClose }: WindowReactivatePanelProps) {
  const lead = conversation.leads;
  const channelId = conversation.channel_id;
  const provider = conversation.channels?.provider;

  const [loading, setLoading] = useState(true);
  const [activeEnrollment, setActiveEnrollment] = useState<CampaignEnrollmentLocal | null>(null);

  // Template send state
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templateLoadError, setTemplateLoadError] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [templateInputs, setTemplateInputs] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [sendSuccess, setSendSuccess] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  // Campaign enroll state
  const [showCadencePicker, setShowCadencePicker] = useState(false);
  const [cadences, setCadences] = useState<Campaign[]>([]);
  const [loadingCadences, setLoadingCadences] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollSuccess, setEnrollSuccess] = useState(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);

  // Load active enrollment on mount
  useEffect(() => {
    if (!lead?.id) return;
    fetch(`/api/leads/${lead.id}/campaign-enrollments`)
      .then((r) => r.json())
      .then((data: CampaignEnrollmentLocal[]) => {
        const active = Array.isArray(data) ? data.find((e) => e.status === "active") : null;
        setActiveEnrollment(active ?? null);
      })
      .catch(() => setActiveEnrollment(null))
      .finally(() => setLoading(false));
  }, [lead?.id]);

  // Load templates when picker opens
  useEffect(() => {
    if (!showTemplatePicker || !channelId || provider !== "meta_cloud") return;
    setLoadingTemplates(true);
    setTemplateLoadError(null);
    fetch(`/api/channels/${channelId}/templates`)
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || "Erro ao carregar templates");
        return d;
      })
      .then((data) => setTemplates(Array.isArray(data) ? data : []))
      .catch((err) => {
        setTemplates([]);
        setTemplateLoadError(err instanceof Error ? err.message : "Erro ao carregar templates");
      })
      .finally(() => setLoadingTemplates(false));
  }, [showTemplatePicker, channelId, provider]);

  // Load active campaigns when picker opens
  useEffect(() => {
    if (!showCadencePicker) return;
    setLoadingCadences(true);
    fetch("/api/campaigns")
      .then((r) => r.json())
      .then((data: Campaign[]) => setCadences((Array.isArray(data) ? data : []).filter((c) => c.status === "active")))
      .catch(() => setCadences([]))
      .finally(() => setLoadingCadences(false));
  }, [showCadencePicker]);

  async function handleSendTemplate() {
    if (!selectedTemplate || !conversation.id) return;
    setSending(true);
    setSendError(null);

    const leadData = lead ?? {};
    const previewText = resolveBody(selectedTemplate.body, selectedTemplate.params, leadData, templateInputs);

    let templateVariables: Record<string, string> | null = null;
    if (selectedTemplate.params.length > 0) {
      templateVariables = {};
      if (selectedTemplate.paramsType === "positional") {
        templateVariables["__params_type__"] = "positional";
      }
      for (const p of selectedTemplate.params) {
        templateVariables[p.paramName] =
          LEAD_RESOLVERS[p.paramName]?.(leadData) || templateInputs[p.paramName] || p.example || "";
      }
    }

    try {
      const res = await fetch(`/api/conversations/${conversation.id}/send-template`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: templateVariables,
          template_body: previewText,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Erro ao enviar template");
      }
      setSendSuccess(true);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setSending(false);
    }
  }

  async function handleEnrollCadence(campaignId: string) {
    if (!lead?.id) return;
    setEnrolling(true);
    try {
      const res = await fetch(`/api/campaigns/${campaignId}/enrollments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_id: lead.id }),
      });
      if (!res.ok) throw new Error("Erro ao inscrever lead na campanha");
      const enrollment: CampaignEnrollmentLocal = await res.json();
      setActiveEnrollment(enrollment);
      setEnrollSuccess(true);
      setShowCadencePicker(false);
    } catch (e) {
      setEnrollError(e instanceof Error ? e.message : "Erro ao adicionar à campanha");
    } finally {
      setEnrolling(false);
    }
  }

  function formatNextSend(iso: string | null): string {
    if (!iso) return "em breve";
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  if (loading) {
    return (
      <div className="border-t border-[#dedbd6] bg-[#faf9f6] px-4 py-3 text-[13px] text-[#7b7b78]">
        Carregando opções...
      </div>
    );
  }

  // If lead already has active cadence
  if (activeEnrollment) {
    return (
      <div className="border-t border-[#dedbd6] bg-[#faf9f6] px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-[13px] text-[#111111] font-medium">
              Em campanha: {activeEnrollment.campaigns?.name ?? "—"}
            </p>
            <p className="text-[12px] text-[#7b7b78] mt-0.5">
              Próxima execução: {formatNextSend(activeEnrollment.next_execute_at)}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-[#7b7b78] hover:text-[#111111] text-xs px-2 py-1 rounded border border-[#dedbd6] transition-colors"
          >
            Fechar
          </button>
        </div>
      </div>
    );
  }

  // Template send success state
  if (sendSuccess) {
    return (
      <div className="border-t border-[#dedbd6] bg-[#faf9f6] px-4 py-3">
        <p className="text-[13px] text-[#111111]">
          Template enviado. Aguardando resposta do cliente para reabrir a janela.
        </p>
        <button
          onClick={onClose}
          className="mt-2 text-[12px] text-[#7b7b78] hover:text-[#111111] underline"
        >
          Fechar
        </button>
      </div>
    );
  }

  return (
    <div className="border-t border-[#dedbd6] bg-[#faf9f6] px-4 py-3 space-y-3">
      <WhatsappWindowIndicator
        expiresAt={conversation.whatsapp_window_expires_at}
        variant="header"
      />
      {!showTemplatePicker && !showCadencePicker && (
        <div className="flex gap-2">
          {provider === "meta_cloud" && (
            <button
              onClick={() => setShowTemplatePicker(true)}
              className="flex-1 bg-[#111111] text-white text-[13px] px-3 py-2 rounded-[4px] hover:opacity-90 transition-opacity"
            >
              Enviar template agora
            </button>
          )}
          <button
            onClick={() => setShowCadencePicker(true)}
            className="flex-1 border border-[#dedbd6] text-[#111111] text-[13px] px-3 py-2 rounded-[4px] hover:bg-[#dedbd6]/30 transition-colors"
          >
            Adicionar à campanha
          </button>
        </div>
      )}

      {/* Template picker */}
      {showTemplatePicker && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[12px] uppercase tracking-[0.6px] text-[#7b7b78]">Template</p>
            <button onClick={() => { setShowTemplatePicker(false); setSelectedTemplate(null); setTemplateInputs({}); }} className="text-[#7b7b78] hover:text-[#111111] text-xs">← Voltar</button>
          </div>
          {loadingTemplates ? (
            <p className="text-[13px] text-[#7b7b78]">Buscando templates...</p>
          ) : templateLoadError ? (
            <p className="text-[13px] text-[#c41c1c]">{templateLoadError}</p>
          ) : templates.length === 0 ? (
            <p className="text-[13px] text-[#c41c1c]">Nenhum template aprovado encontrado.</p>
          ) : (
            <select
              value={selectedTemplate ? `${selectedTemplate.name}|${selectedTemplate.language}` : ""}
              onChange={(e) => {
                const [name, lang] = e.target.value.split("|");
                const t = templates.find((t) => t.name === name && t.language === lang) ?? null;
                setSelectedTemplate(t);
                setTemplateInputs({});
              }}
              className="w-full bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
            >
              <option value="">Selecionar template...</option>
              {templates.map((t) => (
                <option key={`${t.name}|${t.language}`} value={`${t.name}|${t.language}`}>
                  {t.name} ({t.language}){t.category ? ` · ${t.category}` : ""}
                </option>
              ))}
            </select>
          )}
          {selectedTemplate && (() => {
            const leadData = lead ?? {};
            const manualParams = selectedTemplate.params.filter((p) => !LEAD_RESOLVERS[p.paramName]);
            const previewText = resolveBody(selectedTemplate.body, selectedTemplate.params, leadData, templateInputs);
            return (
              <div className="space-y-2">
                {manualParams.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[11px] text-[#7b7b78]">Preencha as variáveis:</p>
                    {manualParams.map((p) => (
                      <div key={p.paramName} className="flex items-center gap-2">
                        <span className="text-[12px] text-[#7b7b78] w-24 shrink-0">{p.paramName}</span>
                        <input
                          type="text"
                          value={templateInputs[p.paramName] ?? ""}
                          onChange={(e) => setTemplateInputs((prev) => ({ ...prev, [p.paramName]: e.target.value }))}
                          placeholder={p.example || "..."}
                          className="flex-1 bg-white border border-[#dedbd6] rounded-[4px] px-2 py-1 text-[12px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        />
                      </div>
                    ))}
                  </div>
                )}
                {previewText && (
                  <div className="bg-[#f0ede8] rounded-[6px] p-2">
                    <p className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Como vai ficar</p>
                    <div className="bg-white border border-[#dedbd6] rounded-[8px] rounded-tl-none px-2.5 py-1.5 max-w-[90%]">
                      <p className="text-[12px] text-[#111111] whitespace-pre-wrap leading-relaxed">
                        {previewText}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
          {sendError && <p className="text-[12px] text-[#c41c1c]">{sendError}</p>}
          {selectedTemplate && (
            <button
              onClick={handleSendTemplate}
              disabled={sending}
              className="w-full bg-[#111111] text-white text-[13px] px-3 py-2 rounded-[4px] disabled:opacity-40 hover:opacity-90 transition-opacity"
            >
              {sending ? "Enviando..." : "Confirmar envio"}
            </button>
          )}
        </div>
      )}

      {/* Cadence picker */}
      {showCadencePicker && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[12px] uppercase tracking-[0.6px] text-[#7b7b78]">Campanha</p>
            <button onClick={() => setShowCadencePicker(false)} className="text-[#7b7b78] hover:text-[#111111] text-xs">← Voltar</button>
          </div>
          {loadingCadences ? (
            <p className="text-[13px] text-[#7b7b78]">Buscando campanhas...</p>
          ) : cadences.length === 0 ? (
            <p className="text-[13px] text-[#7b7b78]">Nenhuma campanha ativa encontrada.</p>
          ) : (
            <div className="space-y-1">
              {cadences.map((c) => (
                <button
                  key={c.id}
                  onClick={() => handleEnrollCadence(c.id)}
                  disabled={enrolling}
                  className="w-full text-left border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[13px] text-[#111111] hover:bg-[#dedbd6]/30 transition-colors disabled:opacity-40"
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}
          {enrollError && <p className="text-[12px] text-[#c41c1c]">{enrollError}</p>}
        </div>
      )}
    </div>
  );
}

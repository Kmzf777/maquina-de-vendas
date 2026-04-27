"use client";

import { useState, useEffect } from "react";
import type { Conversation } from "@/lib/types";

interface MetaTemplate {
  name: string;
  language: string;
  category: string;
  body: string;
  params: string[];
}

interface CadenceEnrollment {
  id: string;
  cadence_id: string;
  status: string;
  next_send_at: string | null;
  cadences?: { id: string; name: string } | null;
}

interface Cadence {
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
  const [activeEnrollment, setActiveEnrollment] = useState<CadenceEnrollment | null>(null);

  // Template send state
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [templates, setTemplates] = useState<MetaTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<MetaTemplate | null>(null);
  const [sending, setSending] = useState(false);
  const [sendSuccess, setSendSuccess] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  // Cadence enroll state
  const [showCadencePicker, setShowCadencePicker] = useState(false);
  const [cadences, setCadences] = useState<Cadence[]>([]);
  const [loadingCadences, setLoadingCadences] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollSuccess, setEnrollSuccess] = useState(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);

  // Load active enrollment on mount
  useEffect(() => {
    if (!lead?.id) return;
    fetch(`/api/leads/${lead.id}/cadence-enrollments?status=active&limit=1`)
      .then((r) => r.json())
      .then((data: CadenceEnrollment[]) => setActiveEnrollment(data[0] ?? null))
      .catch(() => setActiveEnrollment(null))
      .finally(() => setLoading(false));
  }, [lead?.id]);

  // Load templates when picker opens
  useEffect(() => {
    if (!showTemplatePicker || !channelId || provider !== "meta_cloud") return;
    setLoadingTemplates(true);
    fetch(`/api/channels/${channelId}/templates`)
      .then((r) => r.json())
      .then((data) => setTemplates(Array.isArray(data) ? data : []))
      .catch(() => setTemplates([]))
      .finally(() => setLoadingTemplates(false));
  }, [showTemplatePicker, channelId, provider]);

  // Load active cadences when picker opens
  // /api/cadences returns all cadences — filter active ones client-side
  useEffect(() => {
    if (!showCadencePicker) return;
    setLoadingCadences(true);
    fetch("/api/cadences")
      .then((r) => r.json())
      .then((data: Cadence[]) => setCadences((Array.isArray(data) ? data : []).filter((c) => c.status === "active")))
      .catch(() => setCadences([]))
      .finally(() => setLoadingCadences(false));
  }, [showCadencePicker]);

  async function handleSendTemplate() {
    if (!selectedTemplate || !lead?.phone || !channelId) return;
    setSending(true);
    setSendError(null);
    try {
      const dateStr = new Date().toLocaleDateString("pt-BR");
      const broadcastName = `Reativação — ${selectedTemplate.name} — ${dateStr}`;

      const bRes = await fetch("/api/broadcasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: broadcastName,
          channel_id: channelId,
          template_name: selectedTemplate.name,
          template_language_code: selectedTemplate.language,
          template_variables: null,
          send_interval_min: 0,
          send_interval_max: 0,
        }),
      });
      if (!bRes.ok) throw new Error("Erro ao criar disparo");
      const broadcast: { id: string } = await bRes.json();

      const lRes = await fetch("/api/leads/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: lead.phone }),
      });
      if (!lRes.ok) throw new Error("Erro ao resolver lead");
      const leadResolved: { id: string } = await lRes.json();

      const aRes = await fetch(`/api/broadcasts/${broadcast.id}/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_ids: [leadResolved.id] }),
      });
      if (!aRes.ok) throw new Error("Erro ao associar lead ao disparo");

      const sRes = await fetch(`/api/broadcasts/${broadcast.id}/start`, { method: "POST" });
      if (!sRes.ok) throw new Error("Erro ao iniciar disparo");

      setSendSuccess(true);
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setSending(false);
    }
  }

  async function handleEnrollCadence(cadenceId: string) {
    if (!lead?.id) return;
    setEnrolling(true);
    try {
      const res = await fetch(`/api/cadences/${cadenceId}/enrollments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lead_id: lead.id }),
      });
      if (!res.ok) throw new Error("Erro ao enrolar lead na cadência");
      const enrollment: CadenceEnrollment = await res.json();
      setActiveEnrollment(enrollment);
      setEnrollSuccess(true);
      setShowCadencePicker(false);
    } catch (e) {
      setEnrollError(e instanceof Error ? e.message : "Erro ao adicionar à cadência");
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
              Em cadência: {activeEnrollment.cadences?.name ?? "—"}
            </p>
            <p className="text-[12px] text-[#7b7b78] mt-0.5">
              Próximo envio: {formatNextSend(activeEnrollment.next_send_at)}
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
            Adicionar à cadência
          </button>
        </div>
      )}

      {/* Template picker */}
      {showTemplatePicker && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[12px] uppercase tracking-[0.6px] text-[#7b7b78]">Template</p>
            <button onClick={() => { setShowTemplatePicker(false); setSelectedTemplate(null); }} className="text-[#7b7b78] hover:text-[#111111] text-xs">← Voltar</button>
          </div>
          {loadingTemplates ? (
            <p className="text-[13px] text-[#7b7b78]">Buscando templates...</p>
          ) : templates.length === 0 ? (
            <p className="text-[13px] text-[#c41c1c]">Nenhum template aprovado encontrado.</p>
          ) : (
            <select
              value={selectedTemplate ? `${selectedTemplate.name}|${selectedTemplate.language}` : ""}
              onChange={(e) => {
                const [name, lang] = e.target.value.split("|");
                setSelectedTemplate(templates.find((t) => t.name === name && t.language === lang) ?? null);
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
            <p className="text-[12px] uppercase tracking-[0.6px] text-[#7b7b78]">Cadência</p>
            <button onClick={() => setShowCadencePicker(false)} className="text-[#7b7b78] hover:text-[#111111] text-xs">← Voltar</button>
          </div>
          {loadingCadences ? (
            <p className="text-[13px] text-[#7b7b78]">Buscando cadências...</p>
          ) : cadences.length === 0 ? (
            <p className="text-[13px] text-[#7b7b78]">Nenhuma cadência ativa encontrada.</p>
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

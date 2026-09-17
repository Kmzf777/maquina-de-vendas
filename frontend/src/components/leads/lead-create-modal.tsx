"use client";

import { useMemo, useState } from "react";
import { AGENT_STAGES, LEAD_CHANNELS } from "@/lib/constants";
import { StageTargetPicker } from "@/components/deals/stage-target-picker";
import type { Pipeline } from "@/lib/types";

interface LeadCreateModalProps {
  /** Funis disponiveis. Ausente ou vazio: a secao "Funil (opcional)" nao renderiza. */
  pipelines?: Pipeline[];
  onClose: () => void;
  onCreate: (payload: {
    lead: Record<string, string>;
    funnel: { pipeline_id: string; stage_id: string } | null;
  }) => Promise<{ error?: string }>;
}

// O StageTargetPicker renderiza `pipelines.map(...)` sem opcao vazia, porque nos dois
// lugares onde ja e usado (/vendas e o modal de mover em massa) o funil e obrigatorio.
// Aqui ele e opcional, e mexer no picker mudaria o comportamento daqueles dois. Entao
// injetamos um item sentinela de id "" no inicio da lista: escolhe-lo deixa o
// pipelineId vazio, estado que o proprio picker ja trata (nao busca etapas e mantem a
// etapa em "").
const SEM_FUNIL: Pipeline = {
  id: "",
  name: "Nenhum (nao criar card)",
  order_index: -1,
  owner_user_id: null,
  is_universal: true,
  created_at: "",
  updated_at: "",
};

export function LeadCreateModal({ pipelines, onClose, onCreate }: LeadCreateModalProps) {
  const [form, setForm] = useState({
    name: "",
    phone: "",
    email: "",
    instagram: "",
    company: "",
    cnpj: "",
    stage: "secretaria",
    channel: "manual",
  });
  const [pipelineId, setPipelineId] = useState("");
  const [stageId, setStageId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const mostrarFunil = (pipelines?.length ?? 0) > 0;
  const opcoesFunil = useMemo(() => [SEM_FUNIL, ...(pipelines ?? [])], [pipelines]);
  // Funil escolhido sem etapa nao pode criar o lead "esquecendo" o funil em silencio:
  // o submit fica travado ate a etapa ser escolhida (ou o funil voltar para "Nenhum").
  const funilIncompleto = mostrarFunil && Boolean(pipelineId) && !stageId;

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.phone.trim()) {
      setError("Nome e telefone sao obrigatorios.");
      return;
    }
    if (funilIncompleto) {
      setError("Escolha a etapa do funil.");
      return;
    }
    const funnel =
      mostrarFunil && pipelineId && stageId
        ? { pipeline_id: pipelineId, stage_id: stageId }
        : null;
    setSaving(true);
    const result = await onCreate({ lead: form, funnel });
    setSaving(false);
    if (result.error) {
      setError(result.error);
    } else {
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-6">
          <h3
            className="text-[24px] font-normal text-[#111111]"
            style={{ letterSpacing: "-0.48px", lineHeight: "1.00" }}
          >
            Novo Lead
          </h3>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-[4px] border border-[#dedbd6] flex items-center justify-center text-[#7b7b78] hover:text-[#111111] hover:border-[#111111] transition-colors"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="space-y-3">
            {/* Required */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome *</label>
                <input
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="Nome do lead"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Telefone *</label>
                <input
                  value={form.phone}
                  onChange={(e) => update("phone", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="+55 11 99999-9999"
                />
              </div>
            </div>

            {/* Optional */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Email</label>
                <input
                  value={form.email}
                  onChange={(e) => update("email", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Instagram</label>
                <input
                  value={form.instagram}
                  onChange={(e) => update("instagram", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Empresa</label>
                <input
                  value={form.company}
                  onChange={(e) => update("company", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">CNPJ</label>
                <input
                  value={form.cnpj}
                  onChange={(e) => update("cnpj", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                />
              </div>
            </div>

            {/* Selects */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Stage</label>
                <select
                  value={form.stage}
                  onChange={(e) => update("stage", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  {AGENT_STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Canal</label>
                <select
                  value={form.channel}
                  onChange={(e) => update("channel", e.target.value)}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  {LEAD_CHANNELS.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Funil e opcional: sem ele o lead nasce fora do Kanban, como hoje. */}
          {mostrarFunil && (
            <div className="border-t border-[#dedbd6] pt-4 mt-4">
              <span className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                Funil (opcional)
              </span>
              <p className="text-[12px] text-[#7b7b78] mb-3">
                Escolha um funil para o lead ja nascer com um card no Kanban.
              </p>
              <StageTargetPicker
                pipelines={opcoesFunil}
                pipelineId={pipelineId}
                stageId={stageId}
                localPipelineId={null}
                localStages={[]}
                currentStageId={null}
                autoSelectFirstStage={false}
                disabled={saving}
                onChange={(nextPipelineId, nextStageId) => {
                  setPipelineId(nextPipelineId);
                  setStageId(nextStageId);
                  setError("");
                }}
              />
              {funilIncompleto && (
                <p className="text-[12px] text-[#7a5a00] bg-[#fff8e0] border border-[#eadfb4] rounded-[6px] px-3 py-2 mt-3">
                  Escolha a etapa do funil.
                </p>
              )}
            </div>
          )}

          {error && (
            <p className="text-[13px] text-[#c41c1c] mt-3">{error}</p>
          )}

          <div className="flex justify-end mt-5">
            <button
              type="submit"
              disabled={saving || funilIncompleto}
              className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
            >
              {saving ? "Criando..." : "Criar Lead"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

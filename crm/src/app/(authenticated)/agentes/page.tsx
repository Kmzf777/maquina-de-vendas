"use client";

import { useState, useEffect, useCallback } from "react";

const AVAILABLE_TOOLS = [
  { key: "salvar_nome", label: "Salvar Nome" },
  { key: "mudar_stage", label: "Mudar Stage" },
  { key: "encaminhar_humano", label: "Encaminhar Humano" },
  { key: "enviar_fotos", label: "Enviar Fotos" },
];

interface Stage {
  name: string;
  model: string;
  prompt: string;
  tools: string[];
}

interface AgentProfile {
  id: string;
  name: string;
  model: string;
  base_prompt: string;
  stages: Stage[];
  channels_count?: number;
}

type FormData = {
  name: string;
  model: string;
  base_prompt: string;
  stages: Stage[];
};

const EMPTY_STAGE: Stage = {
  name: "",
  model: "",
  prompt: "",
  tools: [],
};

const EMPTY_FORM: FormData = {
  name: "",
  model: "gpt-4.1",
  base_prompt: "",
  stages: [{ ...EMPTY_STAGE }],
};

export default function AgentesPage() {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/agent-profiles");
      if (res.ok) {
        const data = await res.json();
        setProfiles(Array.isArray(data) ? data : data.profiles ?? []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function openNew() {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, stages: [{ ...EMPTY_STAGE }] });
    setError(null);
    setShowForm(true);
  }

  function openEdit(p: AgentProfile) {
    setEditingId(p.id);
    setError(null);
    // Convert stages dict (from DB) to array (for form)
    const stagesObj = p.stages as unknown;
    let stagesArr: Stage[] = [{ ...EMPTY_STAGE }];
    if (stagesObj && typeof stagesObj === "object" && !Array.isArray(stagesObj)) {
      // Dict format: { "secretaria": { prompt, model, tools } }
      stagesArr = Object.entries(stagesObj as Record<string, { prompt?: string; model?: string; tools?: string[] }>).map(
        ([name, s]) => ({
          name,
          model: s.model ?? "",
          prompt: s.prompt ?? "",
          tools: s.tools ?? [],
        })
      );
    } else if (Array.isArray(stagesObj) && stagesObj.length > 0) {
      stagesArr = (stagesObj as Stage[]).map((s) => ({
        name: s.name ?? "",
        model: s.model ?? "",
        prompt: s.prompt ?? "",
        tools: s.tools ?? [],
      }));
    }
    setForm({
      name: p.name,
      model: p.model ?? "gpt-4.1",
      base_prompt: p.base_prompt ?? "",
      stages: stagesArr.length > 0 ? stagesArr : [{ ...EMPTY_STAGE }],
    });
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingId(null);
    setForm({ ...EMPTY_FORM, stages: [{ ...EMPTY_STAGE }] });
    setError(null);
  }

  function updateStage(idx: number, key: keyof Stage, value: string | string[]) {
    setForm((prev) => {
      const stages = [...prev.stages];
      stages[idx] = { ...stages[idx], [key]: value };
      return { ...prev, stages };
    });
  }

  function toggleTool(idx: number, tool: string) {
    setForm((prev) => {
      const stages = [...prev.stages];
      const current = stages[idx].tools ?? [];
      stages[idx] = {
        ...stages[idx],
        tools: current.includes(tool)
          ? current.filter((t) => t !== tool)
          : [...current, tool],
      };
      return { ...prev, stages };
    });
  }

  function addStage() {
    setForm((prev) => ({ ...prev, stages: [...prev.stages, { ...EMPTY_STAGE }] }));
  }

  function removeStage(idx: number) {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.filter((_, i) => i !== idx),
    }));
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setError("Nome do perfil e obrigatorio.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Convert stages array to dict keyed by stage name (backend expects Record<string, StageConfig>)
      const stagesDict: Record<string, { prompt: string; model: string; tools: string[] }> = {};
      for (const s of form.stages) {
        if (s.name.trim()) {
          stagesDict[s.name.trim()] = {
            prompt: s.prompt,
            model: s.model || form.model,
            tools: s.tools,
          };
        }
      }
      const payload = {
        name: form.name,
        model: form.model,
        base_prompt: form.base_prompt,
        stages: stagesDict,
      };
      const url = editingId ? `/api/agent-profiles/${editingId}` : "/api/agent-profiles";
      const method = editingId ? "PUT" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error ?? "Erro ao salvar perfil.");
        return;
      }
      await fetchData();
      closeForm();
    } catch {
      setError("Erro de conexao.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Deseja remover este perfil?")) return;
    setDeletingId(id);
    try {
      await fetch(`/api/agent-profiles/${id}`, { method: "DELETE" });
      await fetchData();
    } finally {
      setDeletingId(null);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-48 rounded-xl animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-[28px] font-bold leading-tight text-[#1f1f1f]">Perfis de Agente</h1>
          <p className="text-[14px] mt-1 text-[#5f6368]">Configure os perfis de IA para seus canais</p>
        </div>
        <button
          onClick={openNew}
          className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors flex items-center gap-1.5"
        >
          <span className="text-[16px] leading-none">+</span>
          Novo Perfil
        </button>
      </div>

      {/* Cards Grid */}
      {profiles.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#e8e8e8] text-center py-16">
          <svg className="w-10 h-10 mx-auto mb-3 text-[#d1d5db]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21M6.75 19.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z" />
          </svg>
          <p className="text-[14px] text-[#9ca3af]">Nenhum perfil criado ainda.</p>
          <button onClick={openNew} className="mt-3 px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium">
            Criar primeiro perfil
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {profiles.map((p) => (
            <div key={p.id} className="bg-white rounded-xl border border-[#e8e8e8] p-5 flex flex-col gap-3">
              {/* Card Header */}
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-[15px] font-semibold text-[#1f1f1f]">{p.name}</h3>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#f6f7ed] text-[#5f6368] border border-[#e5e5dc] font-medium">
                    {p.model ?? "gpt-4.1"}
                  </span>
                </div>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => openEdit(p)}
                    className="px-2.5 py-1.5 rounded-lg text-[12px] font-medium bg-[#f6f7ed] text-[#1f1f1f] hover:bg-[#eceee0] transition-colors"
                  >
                    Editar
                  </button>
                  <button
                    onClick={() => handleDelete(p.id)}
                    disabled={deletingId === p.id}
                    className="px-2.5 py-1.5 rounded-lg text-[12px] font-medium bg-red-50 text-red-600 hover:bg-red-100 transition-colors disabled:opacity-50"
                  >
                    {deletingId === p.id ? "..." : "X"}
                  </button>
                </div>
              </div>

              {/* Base Prompt Preview */}
              {p.base_prompt && (
                <p className="text-[12px] text-[#8a8a8a] line-clamp-2 leading-relaxed">
                  {p.base_prompt}
                </p>
              )}

              {/* Stages */}
              {p.stages && p.stages.length > 0 && (
                <div>
                  <p className="text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide mb-2">
                    Stages ({p.stages.length})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {p.stages.map((s, i) => (
                      <span
                        key={i}
                        className="text-[11px] px-2 py-0.5 rounded-full bg-[#f0f4ff] text-[#4a6cf7] border border-[#dde4fe] font-medium"
                      >
                        {s.name || `Stage ${i + 1}`}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Channels using this profile */}
              <div className="mt-auto pt-2 border-t border-[#f3f4f6]">
                <p className="text-[11px] text-[#9ca3af]">
                  {p.channels_count ?? 0} canal(is) usando este perfil
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal / Form */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={closeForm} />
          <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-5 border-b border-[#e8e8e8] flex items-center justify-between sticky top-0 bg-white z-10">
              <h2 className="text-[16px] font-semibold text-[#1f1f1f]">
                {editingId ? "Editar Perfil" : "Novo Perfil de Agente"}
              </h2>
              <button onClick={closeForm} className="text-[#8a8a8a] hover:text-[#1f1f1f]">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="px-6 py-5 space-y-5">
              {error && (
                <div className="px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-700">
                  {error}
                </div>
              )}

              {/* Name */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Nome do Perfil</label>
                <input
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                  placeholder="Ex: Assistente de Vendas"
                  value={form.name}
                  onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                />
              </div>

              {/* Model */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Modelo Base</label>
                <input
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                  placeholder="gpt-4.1"
                  value={form.model}
                  onChange={(e) => setForm((prev) => ({ ...prev, model: e.target.value }))}
                />
              </div>

              {/* Base Prompt */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Prompt Base</label>
                <textarea
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20 resize-none"
                  rows={5}
                  placeholder="Voce e um assistente de vendas da empresa X. Seu objetivo e qualificar leads e apresentar nossos produtos..."
                  value={form.base_prompt}
                  onChange={(e) => setForm((prev) => ({ ...prev, base_prompt: e.target.value }))}
                />
              </div>

              {/* Stages */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Stages</label>
                  <button
                    onClick={addStage}
                    className="text-[12px] font-medium text-[#1f1f1f] flex items-center gap-1 hover:opacity-70 transition-opacity"
                  >
                    <span className="text-[14px]">+</span> Adicionar Stage
                  </button>
                </div>

                <div className="space-y-4">
                  {form.stages.map((stage, idx) => (
                    <div key={idx} className="bg-[#f6f7ed] rounded-xl p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-[12px] font-semibold text-[#1f1f1f]">Stage {idx + 1}</span>
                        {form.stages.length > 1 && (
                          <button
                            onClick={() => removeStage(idx)}
                            className="text-[11px] text-red-500 hover:text-red-700 font-medium"
                          >
                            Remover
                          </button>
                        )}
                      </div>

                      {/* Stage Name */}
                      <div>
                        <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1 font-medium tracking-wide">Nome do Stage</label>
                        <input
                          className="w-full bg-white border border-[#e8e8e8] rounded-lg text-[13px] px-3 py-2 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                          placeholder="Ex: qualificacao"
                          value={stage.name}
                          onChange={(e) => updateStage(idx, "name", e.target.value)}
                        />
                      </div>

                      {/* Stage Model */}
                      <div>
                        <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1 font-medium tracking-wide">Modelo</label>
                        <input
                          className="w-full bg-white border border-[#e8e8e8] rounded-lg text-[13px] px-3 py-2 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                          placeholder="gpt-4.1 (vazio = usa modelo base)"
                          value={stage.model}
                          onChange={(e) => updateStage(idx, "model", e.target.value)}
                        />
                      </div>

                      {/* Stage Prompt */}
                      <div>
                        <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1 font-medium tracking-wide">Prompt do Stage</label>
                        <textarea
                          className="w-full bg-white border border-[#e8e8e8] rounded-lg text-[13px] px-3 py-2 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20 resize-none"
                          rows={3}
                          placeholder="Instrucoes especificas para este stage..."
                          value={stage.prompt}
                          onChange={(e) => updateStage(idx, "prompt", e.target.value)}
                        />
                      </div>

                      {/* Tools */}
                      <div>
                        <label className="block text-[11px] text-[#8a8a8a] uppercase mb-2 font-medium tracking-wide">Ferramentas</label>
                        <div className="flex flex-wrap gap-2">
                          {AVAILABLE_TOOLS.map((tool) => {
                            const active = (stage.tools ?? []).includes(tool.key);
                            return (
                              <button
                                key={tool.key}
                                type="button"
                                onClick={() => toggleTool(idx, tool.key)}
                                className={`text-[12px] px-2.5 py-1 rounded-full border font-medium transition-all ${
                                  active
                                    ? "bg-[#1f1f1f] text-white border-[#1f1f1f]"
                                    : "bg-white text-[#5f6368] border-[#e8e8e8] hover:border-[#1f1f1f]"
                                }`}
                              >
                                {tool.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-[#e8e8e8] flex justify-end gap-2.5 sticky bottom-0 bg-white">
              <button
                onClick={closeForm}
                className="px-4 py-2 rounded-lg border border-[#e8e8e8] text-[13px] font-medium text-[#5f6368] hover:bg-[#f6f7ed] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors disabled:opacity-50"
              >
                {saving ? "Salvando..." : editingId ? "Salvar alteracoes" : "Criar perfil"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

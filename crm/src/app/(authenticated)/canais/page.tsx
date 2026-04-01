"use client";

import { useState, useEffect, useCallback } from "react";

interface AgentProfile {
  id: string;
  name: string;
}

interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profile?: AgentProfile | null;
  is_active: boolean;
}

type FormData = {
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  agent_profile_id: string;
  // meta_cloud fields
  phone_number_id: string;
  access_token: string;
  app_secret: string;
  verify_token: string;
  // evolution fields
  api_url: string;
  api_key: string;
  instance: string;
};

const EMPTY_FORM: FormData = {
  name: "",
  phone: "",
  provider: "meta_cloud",
  agent_profile_id: "",
  phone_number_id: "",
  access_token: "",
  app_secret: "",
  verify_token: "",
  api_url: "",
  api_key: "",
  instance: "",
};

export default function CanaisPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
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
      const [chRes, prRes] = await Promise.all([
        fetch("/api/channels"),
        fetch("/api/agent-profiles"),
      ]);
      if (chRes.ok) {
        const data = await chRes.json();
        setChannels(Array.isArray(data) ? data : data.channels ?? []);
      }
      if (prRes.ok) {
        const data = await prRes.json();
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
    setForm(EMPTY_FORM);
    setError(null);
    setShowForm(true);
  }

  function openEdit(ch: Channel) {
    setEditingId(ch.id);
    setError(null);
    const cfg = ch.provider_config || {};
    setForm({
      name: ch.name,
      phone: ch.phone,
      provider: ch.provider,
      agent_profile_id: ch.agent_profile_id ?? "",
      phone_number_id: cfg.phone_number_id ?? "",
      access_token: cfg.access_token ?? "",
      app_secret: cfg.app_secret ?? "",
      verify_token: cfg.verify_token ?? "",
      api_url: cfg.api_url ?? "",
      api_key: cfg.api_key ?? "",
      instance: cfg.instance ?? "",
    });
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError(null);
  }

  function buildPayload() {
    const provider_config: Record<string, string> =
      form.provider === "meta_cloud"
        ? {
            phone_number_id: form.phone_number_id,
            access_token: form.access_token,
            app_secret: form.app_secret,
            verify_token: form.verify_token,
          }
        : {
            api_url: form.api_url,
            api_key: form.api_key,
            instance: form.instance,
          };
    return {
      name: form.name,
      phone: form.phone,
      provider: form.provider,
      provider_config,
      agent_profile_id: form.agent_profile_id || null,
    };
  }

  async function handleSave() {
    if (!form.name.trim() || !form.phone.trim()) {
      setError("Nome e telefone sao obrigatorios.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = buildPayload();
      const url = editingId ? `/api/channels/${editingId}` : "/api/channels";
      const method = editingId ? "PUT" : "POST";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        setError(err.error ?? "Erro ao salvar canal.");
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
    if (!confirm("Deseja remover este canal?")) return;
    setDeletingId(id);
    try {
      await fetch(`/api/channels/${id}`, { method: "DELETE" });
      await fetchData();
    } finally {
      setDeletingId(null);
    }
  }

  async function handleToggle(ch: Channel) {
    await fetch(`/api/channels/${ch.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...ch, is_active: !ch.is_active }),
    });
    await fetchData();
  }

  function getWebhookUrl(ch: Channel): string {
    if (ch.provider === "meta_cloud") {
      return `Configure no Meta: POST ${typeof window !== "undefined" ? window.location.origin : ""}/webhook/meta`;
    }
    const backendUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
    return `Configure na Evolution: POST ${backendUrl}/webhook/evolution/${ch.id}`;
  }

  const f = (key: keyof FormData) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>
  ) => setForm((prev) => ({ ...prev, [key]: e.target.value }));

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
        <div className="h-64 rounded-xl animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-[28px] font-bold leading-tight text-[#1f1f1f]">Canais</h1>
          <p className="text-[14px] mt-1 text-[#5f6368]">Gerencie os canais de comunicacao do WhatsApp</p>
        </div>
        <button
          onClick={openNew}
          className="px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium hover:bg-[#333] transition-colors flex items-center gap-1.5"
        >
          <span className="text-[16px] leading-none">+</span>
          Novo Canal
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-[#e8e8e8] overflow-hidden">
        {channels.length === 0 ? (
          <div className="text-center py-16">
            <svg className="w-10 h-10 mx-auto mb-3 text-[#d1d5db]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3" />
            </svg>
            <p className="text-[14px] text-[#9ca3af]">Nenhum canal cadastrado ainda.</p>
            <button onClick={openNew} className="mt-3 px-4 py-2 rounded-lg bg-[#1f1f1f] text-white text-[13px] font-medium">
              Criar primeiro canal
            </button>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#e8e8e8]">
                <th className="text-left px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Nome</th>
                <th className="text-left px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Telefone</th>
                <th className="text-left px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Provider</th>
                <th className="text-left px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Agente</th>
                <th className="text-left px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Webhook</th>
                <th className="text-left px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Status</th>
                <th className="text-right px-5 py-3 text-[11px] text-[#8a8a8a] uppercase font-medium tracking-wide">Acoes</th>
              </tr>
            </thead>
            <tbody>
              {channels.map((ch, i) => (
                <tr
                  key={ch.id}
                  className={`border-b border-[#f3f4f6] last:border-0 ${i % 2 === 0 ? "" : "bg-[#fafaf7]"}`}
                >
                  <td className="px-5 py-3.5 text-[13px] font-medium text-[#1f1f1f]">{ch.name}</td>
                  <td className="px-5 py-3.5 text-[13px] text-[#5f6368]">{ch.phone}</td>
                  <td className="px-5 py-3.5">
                    {ch.provider === "meta_cloud" ? (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-green-50 text-green-700 border border-green-200 font-medium">
                        Meta Cloud
                      </span>
                    ) : (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 font-medium">
                        Evolution
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-[13px] text-[#5f6368]">
                    {ch.agent_profile?.name ?? (
                      <span className="text-[#9ca3af] italic">Humano</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 max-w-[200px]">
                    <span
                      className="text-[11px] text-[#8a8a8a] truncate block cursor-pointer hover:text-[#1f1f1f]"
                      title={getWebhookUrl(ch)}
                      onClick={() => navigator.clipboard?.writeText(getWebhookUrl(ch))}
                    >
                      {getWebhookUrl(ch)}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <button
                      onClick={() => handleToggle(ch)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                        ch.is_active ? "bg-[#4ade80]" : "bg-[#d1d5db]"
                      }`}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                          ch.is_active ? "translate-x-[18px]" : "translate-x-[2px]"
                        }`}
                      />
                    </button>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => openEdit(ch)}
                        className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-[#f6f7ed] text-[#1f1f1f] hover:bg-[#eceee0] transition-colors"
                      >
                        Editar
                      </button>
                      <button
                        onClick={() => handleDelete(ch.id)}
                        disabled={deletingId === ch.id}
                        className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-red-50 text-red-600 hover:bg-red-100 transition-colors disabled:opacity-50"
                      >
                        {deletingId === ch.id ? "..." : "Remover"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal / Form */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={closeForm} />
          <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-5 border-b border-[#e8e8e8] flex items-center justify-between">
              <h2 className="text-[16px] font-semibold text-[#1f1f1f]">
                {editingId ? "Editar Canal" : "Novo Canal"}
              </h2>
              <button onClick={closeForm} className="text-[#8a8a8a] hover:text-[#1f1f1f]">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              {error && (
                <div className="px-4 py-2.5 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-700">
                  {error}
                </div>
              )}

              {/* Name */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Nome</label>
                <input
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                  placeholder="Ex: WhatsApp Principal"
                  value={form.name}
                  onChange={f("name")}
                />
              </div>

              {/* Phone */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Telefone</label>
                <input
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                  placeholder="+5511999999999"
                  value={form.phone}
                  onChange={f("phone")}
                />
              </div>

              {/* Provider */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Provider</label>
                <select
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                  value={form.provider}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      provider: e.target.value as "meta_cloud" | "evolution",
                    }))
                  }
                >
                  <option value="meta_cloud">Meta Cloud API</option>
                  <option value="evolution">Evolution API</option>
                </select>
              </div>

              {/* Dynamic provider config */}
              {form.provider === "meta_cloud" ? (
                <>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Phone Number ID</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="123456789"
                      value={form.phone_number_id}
                      onChange={f("phone_number_id")}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Access Token</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="EAAxxxxxx..."
                      value={form.access_token}
                      onChange={f("access_token")}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">App Secret</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="abc123..."
                      value={form.app_secret}
                      onChange={f("app_secret")}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Verify Token</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="meu_token_secreto"
                      value={form.verify_token}
                      onChange={f("verify_token")}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">API URL</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="https://evolution.meudominio.com"
                      value={form.api_url}
                      onChange={f("api_url")}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">API Key</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="chave-da-api"
                      value={form.api_key}
                      onChange={f("api_key")}
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Instance</label>
                    <input
                      className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                      placeholder="instancia-principal"
                      value={form.instance}
                      onChange={f("instance")}
                    />
                  </div>
                </>
              )}

              {/* Agent Profile */}
              <div>
                <label className="block text-[11px] text-[#8a8a8a] uppercase mb-1.5 font-medium tracking-wide">Perfil de Agente</label>
                <select
                  className="w-full bg-[#f6f7ed] border-none rounded-lg text-[13px] px-3 py-2.5 outline-none focus:ring-2 focus:ring-[#1f1f1f]/20"
                  value={form.agent_profile_id}
                  onChange={f("agent_profile_id")}
                >
                  <option value="">Nenhum (Humano)</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="px-6 py-4 border-t border-[#e8e8e8] flex justify-end gap-2.5">
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
                {saving ? "Salvando..." : editingId ? "Salvar alteracoes" : "Criar canal"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

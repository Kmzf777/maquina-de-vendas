"use client";

import { useState, useEffect, useRef, useCallback } from "react";

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
  agent_profiles: AgentProfile | null;
  is_active: boolean;
  created_at: string;
}

interface FormData {
  name: string;
  provider: "meta_cloud" | "evolution";
  phone: string;
  agent_profile_id: string;
  is_active: boolean;
  // Evolution fields
  evo_api_url: string;
  evo_api_key: string;
  evo_instance: string;
  // Meta fields
  meta_phone_number_id: string;
  meta_access_token: string;
  meta_app_secret: string;
  meta_verify_token: string;
}

const EMPTY_FORM: FormData = {
  name: "",
  provider: "evolution",
  phone: "",
  agent_profile_id: "",
  is_active: true,
  evo_api_url: "",
  evo_api_key: "",
  evo_instance: "",
  meta_phone_number_id: "",
  meta_access_token: "",
  meta_app_secret: "",
  meta_verify_token: "",
};

export default function CanaisPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // QR Code modal state
  const [qrChannelId, setQrChannelId] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [qrStatus, setQrStatus] = useState<"idle" | "loading" | "scanning" | "connected">("idle");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Connection status cache
  const [connectionStatus, setConnectionStatus] = useState<Record<string, { connected: boolean; number?: string }>>({});

  const fetchChannels = useCallback(async () => {
    const res = await fetch("/api/channels");
    const data = await res.json();
    setChannels(data);
    setLoading(false);
  }, []);

  const fetchProfiles = useCallback(async () => {
    const res = await fetch("/api/agent-profiles");
    const data = await res.json();
    setProfiles(data);
  }, []);

  useEffect(() => {
    fetchChannels();
    fetchProfiles();
  }, [fetchChannels, fetchProfiles]);

  // Check connection status for Evolution channels
  useEffect(() => {
    const evoChannels = channels.filter((c) => c.provider === "evolution");
    evoChannels.forEach(async (ch) => {
      try {
        const res = await fetch(`/api/channels/${ch.id}/status`);
        const data = await res.json();
        setConnectionStatus((prev) => ({ ...prev, [ch.id]: data }));
      } catch {
        setConnectionStatus((prev) => ({ ...prev, [ch.id]: { connected: false } }));
      }
    });
  }, [channels]);

  const handleSave = async () => {
    setSaving(true);
    const providerConfig =
      form.provider === "evolution"
        ? { api_url: form.evo_api_url, api_key: form.evo_api_key, instance: form.evo_instance }
        : {
            phone_number_id: form.meta_phone_number_id,
            access_token: form.meta_access_token,
            app_secret: form.meta_app_secret,
            verify_token: form.meta_verify_token,
          };

    const body = {
      name: form.name,
      phone: form.provider === "meta_cloud" ? form.phone : "",
      provider: form.provider,
      provider_config: providerConfig,
      agent_profile_id: form.agent_profile_id || null,
      is_active: form.is_active,
    };

    if (editingId) {
      await fetch(`/api/channels/${editingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } else {
      await fetch("/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }

    setSaving(false);
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    fetchChannels();
  };

  const handleEdit = (ch: Channel) => {
    const config = ch.provider_config || {};
    setForm({
      name: ch.name,
      provider: ch.provider,
      phone: ch.phone || "",
      agent_profile_id: ch.agent_profile_id || "",
      is_active: ch.is_active,
      evo_api_url: config.api_url || "",
      evo_api_key: config.api_key || "",
      evo_instance: config.instance || "",
      meta_phone_number_id: config.phone_number_id || "",
      meta_access_token: config.access_token || "",
      meta_app_secret: config.app_secret || "",
      meta_verify_token: config.verify_token || "",
    });
    setEditingId(ch.id);
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Tem certeza que deseja excluir este canal?")) return;
    await fetch(`/api/channels/${id}`, { method: "DELETE" });
    fetchChannels();
  };

  const handleToggleActive = async (ch: Channel) => {
    await fetch(`/api/channels/${ch.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !ch.is_active }),
    });
    fetchChannels();
  };

  // QR Code connection flow
  const handleConnect = async (channelId: string) => {
    setQrChannelId(channelId);
    setQrStatus("loading");
    setQrCode(null);

    try {
      const res = await fetch(`/api/channels/${channelId}/connect`, { method: "POST" });
      const data = await res.json();

      if (data.connected) {
        setQrStatus("connected");
        fetchChannels();
        return;
      }

      if (data.qrcode) {
        setQrCode(data.qrcode);
        setQrStatus("scanning");

        // Start polling for connection
        pollRef.current = setInterval(async () => {
          try {
            const statusRes = await fetch(`/api/channels/${channelId}/status`);
            const statusData = await statusRes.json();
            if (statusData.connected) {
              clearInterval(pollRef.current!);
              pollRef.current = null;
              setQrStatus("connected");
              setConnectionStatus((prev) => ({ ...prev, [channelId]: statusData }));
              fetchChannels();
            }
          } catch { /* ignore polling errors */ }
        }, 3000);

        // Timeout after 60s
        setTimeout(() => {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setQrStatus("idle");
            setQrChannelId(null);
          }
        }, 60000);
      }
    } catch {
      setQrStatus("idle");
    }
  };

  const handleDisconnect = async (channelId: string) => {
    await fetch(`/api/channels/${channelId}/disconnect`, { method: "POST" });
    setConnectionStatus((prev) => ({ ...prev, [channelId]: { connected: false } }));
    fetchChannels();
  };

  const closeQrModal = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setQrChannelId(null);
    setQrCode(null);
    setQrStatus("idle");
  };

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-[#8a8a8a] text-sm">Carregando...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-[28px] font-bold text-[#1f1f1f]">Canais</h1>
        <button
          onClick={() => { setForm(EMPTY_FORM); setEditingId(null); setShowForm(true); }}
          className="px-5 py-2.5 text-[13px] font-medium text-white rounded-xl transition-all hover:opacity-90"
          style={{ background: "var(--accent-olive)" }}
        >
          + Novo Canal
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl border border-[#e5e7eb] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#f0f0f0]">
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Nome</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Telefone</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Provider</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Agente</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Conexao</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Ativo</th>
              <th className="text-right px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((ch) => {
              const connStatus = connectionStatus[ch.id];
              return (
                <tr key={ch.id} className="border-b border-[#f8f8f8] last:border-0 hover:bg-[#fafafa] transition-colors">
                  <td className="px-5 py-3.5 text-[13px] font-medium text-[#1f1f1f]">{ch.name}</td>
                  <td className="px-5 py-3.5 text-[13px] text-[#5f6368]">{ch.phone || "\u2014"}</td>
                  <td className="px-5 py-3.5">
                    <span className={`inline-flex px-2.5 py-1 text-[11px] font-semibold rounded-full ${
                      ch.provider === "meta_cloud"
                        ? "bg-blue-50 text-blue-700"
                        : "bg-emerald-50 text-emerald-700"
                    }`}>
                      {ch.provider === "meta_cloud" ? "Meta" : "Evolution"}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-[13px] text-[#5f6368]">
                    {ch.agent_profiles?.name || <span className="text-[#b0b0b0]">Sem agente</span>}
                  </td>
                  <td className="px-5 py-3.5">
                    {ch.provider === "evolution" ? (
                      connStatus?.connected ? (
                        <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 font-medium">
                          <span className="w-2 h-2 rounded-full bg-emerald-500" />
                          Conectado
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-[12px] text-red-500 font-medium">
                          <span className="w-2 h-2 rounded-full bg-red-400" />
                          Desconectado
                        </span>
                      )
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[12px] text-blue-600 font-medium">
                        <span className="w-2 h-2 rounded-full bg-blue-500" />
                        Webhook
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    <button
                      onClick={() => handleToggleActive(ch)}
                      className={`relative w-10 h-5 rounded-full transition-colors ${ch.is_active ? "bg-emerald-500" : "bg-gray-300"}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${ch.is_active ? "translate-x-5" : ""}`} />
                    </button>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {ch.provider === "evolution" && (
                        connStatus?.connected ? (
                          <button onClick={() => handleDisconnect(ch.id)} className="px-3 py-1.5 text-[11px] font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors">
                            Desconectar
                          </button>
                        ) : (
                          <button onClick={() => handleConnect(ch.id)} className="px-3 py-1.5 text-[11px] font-medium text-emerald-700 bg-emerald-50 rounded-lg hover:bg-emerald-100 transition-colors">
                            Conectar
                          </button>
                        )
                      )}
                      <button onClick={() => handleEdit(ch)} className="px-3 py-1.5 text-[11px] font-medium text-[#5f6368] bg-[#f6f7ed] rounded-lg hover:bg-[#eef0dc] transition-colors">
                        Editar
                      </button>
                      <button onClick={() => handleDelete(ch.id)} className="px-3 py-1.5 text-[11px] font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors">
                        Excluir
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {channels.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-12 text-center text-[13px] text-[#8a8a8a]">
                  Nenhum canal configurado. Clique em &quot;+ Novo Canal&quot; para comecar.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => { setShowForm(false); setEditingId(null); }}>
          <div className="bg-white rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-[#1f1f1f] mb-5">
              {editingId ? "Editar Canal" : "Novo Canal"}
            </h2>

            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Nome</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                  placeholder="Ex: Atendimento Principal"
                />
              </div>

              {/* Provider */}
              <div>
                <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Provider</label>
                <select
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value as "meta_cloud" | "evolution" })}
                  className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                >
                  <option value="evolution">Evolution API</option>
                  <option value="meta_cloud">Meta Cloud API (Oficial)</option>
                </select>
              </div>

              {/* Evolution-specific fields */}
              {form.provider === "evolution" && (
                <>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">API URL</label>
                    <input
                      value={form.evo_api_url}
                      onChange={(e) => setForm({ ...form, evo_api_url: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      placeholder="https://evolution.seudominio.com"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">API Key</label>
                    <input
                      value={form.evo_api_key}
                      onChange={(e) => setForm({ ...form, evo_api_key: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Nome da Instancia</label>
                    <input
                      value={form.evo_instance}
                      onChange={(e) => setForm({ ...form, evo_instance: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      placeholder="minha-instancia"
                    />
                  </div>
                </>
              )}

              {/* Meta-specific fields */}
              {form.provider === "meta_cloud" && (
                <>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Telefone</label>
                    <input
                      value={form.phone}
                      onChange={(e) => setForm({ ...form, phone: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      placeholder="5534999999999"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Phone Number ID</label>
                    <input
                      value={form.meta_phone_number_id}
                      onChange={(e) => setForm({ ...form, meta_phone_number_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Access Token</label>
                    <input
                      value={form.meta_access_token}
                      onChange={(e) => setForm({ ...form, meta_access_token: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">App Secret</label>
                    <input
                      value={form.meta_app_secret}
                      onChange={(e) => setForm({ ...form, meta_app_secret: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Verify Token</label>
                    <input
                      value={form.meta_verify_token}
                      onChange={(e) => setForm({ ...form, meta_verify_token: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                    />
                  </div>
                </>
              )}

              {/* Agent Profile */}
              <div>
                <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Agente IA</label>
                <select
                  value={form.agent_profile_id}
                  onChange={(e) => setForm({ ...form, agent_profile_id: e.target.value })}
                  className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                >
                  <option value="">Nenhum (100% humano)</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              {/* Active toggle */}
              <div className="flex items-center justify-between">
                <label className="text-[12px] font-semibold text-[#5f6368]">Ativo</label>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, is_active: !form.is_active })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${form.is_active ? "bg-emerald-500" : "bg-gray-300"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${form.is_active ? "translate-x-5" : ""}`} />
                </button>
              </div>
            </div>

            {/* Webhook info for Meta (only when editing) */}
            {editingId && form.provider === "meta_cloud" && (
              <div className="mt-5 p-4 bg-blue-50 rounded-xl">
                <p className="text-[12px] font-semibold text-blue-700 mb-2">Configuracao do Webhook no Meta</p>
                <div className="space-y-2">
                  <div>
                    <span className="text-[11px] text-blue-600">URL do Webhook:</span>
                    <code className="block text-[12px] bg-white px-3 py-1.5 rounded-lg mt-1 text-[#1f1f1f] select-all">
                      {backendUrl}/webhook/meta
                    </code>
                  </div>
                  <div>
                    <span className="text-[11px] text-blue-600">Verify Token:</span>
                    <code className="block text-[12px] bg-white px-3 py-1.5 rounded-lg mt-1 text-[#1f1f1f] select-all">
                      {form.meta_verify_token || "\u2014"}
                    </code>
                  </div>
                </div>
              </div>
            )}

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => { setShowForm(false); setEditingId(null); }}
                className="px-5 py-2.5 text-[13px] font-medium text-[#5f6368] bg-[#f6f7ed] rounded-xl hover:bg-[#eef0dc] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.name}
                className="px-5 py-2.5 text-[13px] font-medium text-white rounded-xl transition-all hover:opacity-90 disabled:opacity-50"
                style={{ background: "var(--accent-olive)" }}
              >
                {saving ? "Salvando..." : editingId ? "Salvar" : "Criar"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* QR Code Modal */}
      {qrChannelId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={closeQrModal}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-6 text-center" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-[#1f1f1f] mb-4">Conectar WhatsApp</h2>

            {qrStatus === "loading" && (
              <p className="text-[13px] text-[#8a8a8a] py-8">Gerando QR Code...</p>
            )}

            {qrStatus === "scanning" && qrCode && (
              <div>
                <img
                  src={qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`}
                  alt="QR Code"
                  className="mx-auto w-64 h-64 rounded-xl"
                />
                <p className="text-[12px] text-[#8a8a8a] mt-3">Escaneie o QR Code com o WhatsApp</p>
              </div>
            )}

            {qrStatus === "connected" && (
              <div className="py-8">
                <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-emerald-100 flex items-center justify-center">
                  <svg className="w-8 h-8 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-[14px] font-medium text-emerald-700">Conectado com sucesso!</p>
              </div>
            )}

            <button
              onClick={closeQrModal}
              className="mt-4 px-5 py-2.5 text-[13px] font-medium text-[#5f6368] bg-[#f6f7ed] rounded-xl hover:bg-[#eef0dc] transition-colors"
            >
              Fechar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

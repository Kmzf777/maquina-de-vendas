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

  const backendUrl = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-[#7b7b78] text-[14px]">Carregando...</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0 flex items-end justify-between">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">Instâncias</h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">Canais de WhatsApp conectados</p>
        </div>
        <button
          onClick={() => { setForm(EMPTY_FORM); setEditingId(null); setShowForm(true); }}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
        >
          + Novo Canal
        </button>
      </div>

      <div className="p-8 overflow-auto flex-1 bg-[#faf9f6]">
      {/* Table */}
      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#dedbd6]">
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Nome</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Telefone</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Provider</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Agente</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Conexao</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Ativo</th>
              <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-right font-normal">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((ch) => {
              const connStatus = connectionStatus[ch.id];
              return (
                <tr key={ch.id} className="border-b border-[#dedbd6] hover:bg-[#faf9f6] transition-colors">
                  <td className="px-4 py-3 text-[14px] text-[#111111]">{ch.name}</td>
                  <td className="px-4 py-3 text-[14px] text-[#7b7b78]">{ch.phone || "\u2014"}</td>
                  <td className="px-4 py-3">
                    <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]">
                      {ch.provider === "meta_cloud" ? "Meta" : "Evolution"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[14px] text-[#7b7b78]">
                    {ch.agent_profiles?.name || <span className="text-[#7b7b78]">Sem agente</span>}
                  </td>
                  <td className="px-4 py-3">
                    {ch.provider === "evolution" ? (
                      connStatus?.connected ? (
                        <span className="bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20">
                          Conectado
                        </span>
                      ) : (
                        <span className="bg-[#c41c1c]/10 text-[#c41c1c] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#c41c1c]/20">
                          Desconectado
                        </span>
                      )
                    ) : (
                      <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]">
                        Webhook
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleToggleActive(ch)}
                      className={`relative w-10 h-5 rounded-full transition-colors ${ch.is_active ? "bg-[#0bdf50]" : "bg-[#dedbd6]"}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${ch.is_active ? "translate-x-5" : ""}`} />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {ch.provider === "evolution" && (
                        connStatus?.connected ? (
                          <button onClick={() => handleDisconnect(ch.id)} className="bg-[#c41c1c]/10 text-[#c41c1c] border border-[#c41c1c]/20 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                            Desconectar
                          </button>
                        ) : (
                          <button onClick={() => handleConnect(ch.id)} className="bg-[#0bdf50]/10 text-[#0bdf50] border border-[#0bdf50]/20 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                            Conectar
                          </button>
                        )
                      )}
                      <button onClick={() => handleEdit(ch)} className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                        Editar
                      </button>
                      <button onClick={() => handleDelete(ch.id)} className="bg-[#c41c1c]/10 text-[#c41c1c] border border-[#c41c1c]/20 px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]">
                        Excluir
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {channels.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center text-[14px] text-[#7b7b78]">
                  Nenhum canal configurado. Clique em &quot;+ Novo Canal&quot; para comecar.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      </div>

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={() => { setShowForm(false); setEditingId(null); }}>
          <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-[14px] font-normal text-[#111111]">
                {editingId ? "Editar Canal" : "Novo Canal"}
              </h2>
              <button onClick={() => { setShowForm(false); setEditingId(null); }} className="text-[#7b7b78] hover:text-[#111111] text-xl transition-colors">&times;</button>
            </div>

            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="Ex: Atendimento Principal"
                />
              </div>

              {/* Provider */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Provider</label>
                <select
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value as "meta_cloud" | "evolution" })}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="evolution">Evolution API</option>
                  <option value="meta_cloud">Meta Cloud API (Oficial)</option>
                </select>
              </div>

              {/* Evolution-specific fields */}
              {form.provider === "evolution" && (
                <>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">API URL</label>
                    <input
                      value={form.evo_api_url}
                      onChange={(e) => setForm({ ...form, evo_api_url: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      placeholder="https://evolution.seudominio.com"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">API Key</label>
                    <input
                      value={form.evo_api_key}
                      onChange={(e) => setForm({ ...form, evo_api_key: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Nome da Instancia</label>
                    <input
                      value={form.evo_instance}
                      onChange={(e) => setForm({ ...form, evo_instance: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      placeholder="minha-instancia"
                    />
                  </div>
                </>
              )}

              {/* Meta-specific fields */}
              {form.provider === "meta_cloud" && (
                <>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Telefone</label>
                    <input
                      value={form.phone}
                      onChange={(e) => setForm({ ...form, phone: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      placeholder="5534999999999"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Phone Number ID</label>
                    <input
                      value={form.meta_phone_number_id}
                      onChange={(e) => setForm({ ...form, meta_phone_number_id: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Access Token</label>
                    <input
                      value={form.meta_access_token}
                      onChange={(e) => setForm({ ...form, meta_access_token: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">App Secret</label>
                    <input
                      value={form.meta_app_secret}
                      onChange={(e) => setForm({ ...form, meta_app_secret: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Verify Token</label>
                    <input
                      value={form.meta_verify_token}
                      onChange={(e) => setForm({ ...form, meta_verify_token: e.target.value })}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                    />
                  </div>
                </>
              )}

              {/* Agent Profile */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Agente IA</label>
                <select
                  value={form.agent_profile_id}
                  onChange={(e) => setForm({ ...form, agent_profile_id: e.target.value })}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
                >
                  <option value="">Nenhum (100% humano)</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              {/* Active toggle */}
              <div className="flex items-center justify-between">
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Ativo</label>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, is_active: !form.is_active })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${form.is_active ? "bg-[#0bdf50]" : "bg-[#dedbd6]"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${form.is_active ? "translate-x-5" : ""}`} />
                </button>
              </div>
            </div>

            {/* Webhook info for Meta (only when editing) */}
            {editingId && form.provider === "meta_cloud" && (
              <div className="mt-5 p-4 bg-[#faf9f6] border border-[#dedbd6] rounded-[8px]">
                <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">Configuracao do Webhook no Meta</p>
                <div className="space-y-2">
                  <div>
                    <span className="text-[11px] text-[#7b7b78]">URL do Webhook:</span>
                    <code className="block text-[12px] bg-white border border-[#dedbd6] px-3 py-1.5 rounded-[6px] mt-1 text-[#111111] select-all">
                      {backendUrl}/webhook/meta
                    </code>
                  </div>
                  <div>
                    <span className="text-[11px] text-[#7b7b78]">Verify Token:</span>
                    <code className="block text-[12px] bg-white border border-[#dedbd6] px-3 py-1.5 rounded-[6px] mt-1 text-[#111111] select-all">
                      {form.meta_verify_token || "\u2014"}
                    </code>
                  </div>
                </div>
              </div>
            )}

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => { setShowForm(false); setEditingId(null); }}
                className="bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
              >
                Cancelar
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.name}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
              >
                {saving ? "Salvando..." : editingId ? "Salvar" : "Criar"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* QR Code Modal */}
      {qrChannelId && (
        <div className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4" onClick={closeQrModal}>
          <div className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-sm p-6 text-center" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-[14px] font-normal text-[#111111] mb-4">Conectar WhatsApp</h2>

            {qrStatus === "loading" && (
              <p className="text-[14px] text-[#7b7b78] py-8">Gerando QR Code...</p>
            )}

            {qrStatus === "scanning" && qrCode && (
              <div>
                <img
                  src={qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`}
                  alt="QR Code"
                  className="mx-auto w-64 h-64 rounded-[8px]"
                />
                <p className="text-[12px] text-[#7b7b78] mt-3">Escaneie o QR Code com o WhatsApp</p>
              </div>
            )}

            {qrStatus === "connected" && (
              <div className="py-8">
                <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-[#0bdf50]/10 border border-[#0bdf50]/20 flex items-center justify-center">
                  <svg className="w-8 h-8 text-[#0bdf50]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-[14px] text-[#0bdf50]">Conectado com sucesso!</p>
              </div>
            )}

            <button
              onClick={closeQrModal}
              className="mt-4 bg-transparent text-[#111111] border border-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85]"
            >
              Fechar
            </button>
          </div>
        </div>
      )}

    </div>
  );
}

"use client";

import { useState, useEffect, useCallback } from "react";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";

interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud";
  provider_config: Record<string, string>;
  is_active: boolean;
  mode: "ai" | "human";
  owner_user_id: string | null;
  created_at: string;
}

interface CrmUser {
  id: string;
  email: string;
  name: string;
}

interface FormData {
  name: string;
  phone: string;
  is_active: boolean;
  mode: "ai" | "human";
  meta_phone_number_id: string;
  owner_user_id: string;
}

const EMPTY_FORM: FormData = {
  name: "",
  phone: "",
  is_active: true,
  mode: "ai",
  meta_phone_number_id: "",
  owner_user_id: "",
};

function IconPencil({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
    </svg>
  );
}

function IconTrash({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

export default function CanaisPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [users, setUsers] = useState<CrmUser[]>([]);

  const fetchChannels = useCallback(async () => {
    const res = await fetch("/api/channels");
    const data = await res.json();
    setChannels(data);
    setLoading(false);
  }, []);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await fetch("/api/users");
      if (res.ok) setUsers(await res.json());
    } catch { /* silently ignore */ }
  }, []);

  useEffect(() => {
    fetchChannels();
    fetchUsers();
  }, [fetchChannels, fetchUsers]);

  const handleSave = async () => {
    setSaving(true);
    const body = {
      name: form.name,
      phone: form.phone,
      provider: "meta_cloud",
      provider_config: { phone_number_id: form.meta_phone_number_id },
      is_active: form.is_active,
      mode: form.mode,
      owner_user_id: form.owner_user_id || null,
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
      phone: ch.phone || "",
      is_active: ch.is_active,
      mode: ch.mode ?? "ai",
      meta_phone_number_id: config.phone_number_id || "",
      owner_user_id: ch.owner_user_id || "",
    });
    setEditingId(ch.id);
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Tem certeza que deseja excluir este canal?")) return;
    await fetch(`/api/channels/${id}`, { method: "DELETE" });
    fetchChannels();
  };

  const handleToggleActive = async (ch: Channel, newValue: boolean) => {
    await fetch(`/api/channels/${ch.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: newValue }),
    });
    fetchChannels();
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
  };

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
          <h1
            style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
            className="text-[32px] font-normal text-[#111111]"
          >
            Canais
          </h1>
          <p className="text-[14px] text-[#7b7b78] mt-0.5">
            Canais de WhatsApp conectados via Meta Cloud API
          </p>
        </div>
        <button
          onClick={() => { setForm(EMPTY_FORM); setEditingId(null); setShowForm(true); }}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85]"
        >
          + Novo Canal
        </button>
      </div>

      {/* Content */}
      <div className="p-8 overflow-auto flex-1 bg-[#faf9f6]">
        <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-x-auto">
          <table className="w-full min-w-[760px]">
            <thead>
              <tr className="border-b border-[#dedbd6]">
                <th className="px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Nome</th>
                <th className="px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Telefone</th>
                <th className="px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Phone ID</th>
                <th className="px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Provider</th>
                <th className="px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Modo</th>
                <th className="px-5 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Ativo</th>
                <th className="px-5 py-3 w-[1%]" />
              </tr>
            </thead>
            <tbody>
              {channels.map((ch) => (
                <tr
                  key={ch.id}
                  className="border-b border-[#dedbd6] last:border-b-0 hover:bg-[#faf9f6] transition-colors group"
                >
                  {/* Nome */}
                  <td className="px-5 py-3.5 text-[14px] font-medium text-[#111111] whitespace-nowrap">
                    {ch.name}
                  </td>

                  {/* Telefone */}
                  <td className="px-5 py-3.5 text-[13px] font-mono text-[#7b7b78] whitespace-nowrap">
                    {ch.phone || "—"}
                  </td>

                  {/* Phone ID */}
                  <td className="px-5 py-3.5 text-[12px] font-mono text-[#7b7b78] max-w-[180px]">
                    <span
                      className="block truncate"
                      title={ch.provider_config?.phone_number_id || "—"}
                    >
                      {ch.provider_config?.phone_number_id || "—"}
                    </span>
                  </td>

                  {/* Provider */}
                  <td className="px-5 py-3.5 whitespace-nowrap">
                    <Badge className="bg-[#1877F2]/10 text-[#1877F2] border border-[#1877F2]/20 text-[10px] uppercase tracking-[0.5px] font-semibold rounded-[4px] px-2 py-0.5 h-auto">
                      Meta
                    </Badge>
                  </td>

                  {/* Modo */}
                  <td className="px-5 py-3.5 whitespace-nowrap">
                    {ch.mode === "ai" ? (
                      <Badge className="bg-[#0bdf50]/10 text-[#0bdf50] border border-[#0bdf50]/20 text-[10px] uppercase tracking-[0.5px] font-semibold rounded-[4px] px-2 py-0.5 h-auto">
                        IA
                      </Badge>
                    ) : (
                      <Badge
                        variant="outline"
                        className="text-[#7b7b78] border-[#dedbd6] text-[10px] uppercase tracking-[0.5px] font-semibold rounded-[4px] px-2 py-0.5 h-auto"
                      >
                        Humano
                      </Badge>
                    )}
                  </td>

                  {/* Ativo */}
                  <td className="px-5 py-3.5 whitespace-nowrap">
                    <Switch
                      checked={ch.is_active}
                      onCheckedChange={(checked) => handleToggleActive(ch, checked)}
                      className="data-checked:bg-[#0bdf50]"
                    />
                  </td>

                  {/* Ações (sem cabeçalho) */}
                  <td className="px-5 py-3.5 whitespace-nowrap">
                    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => handleEdit(ch)}
                        title="Editar"
                        className="p-1.5 rounded-[4px] text-[#7b7b78] hover:text-[#111111] hover:bg-[#f0ede8] transition-colors"
                      >
                        <IconPencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(ch.id)}
                        title="Excluir"
                        className="p-1.5 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] hover:bg-[#c41c1c]/8 transition-colors"
                      >
                        <IconTrash className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {channels.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-5 py-14 text-center">
                    <p className="text-[14px] text-[#7b7b78]">Nenhum canal configurado.</p>
                    <p className="text-[13px] text-[#b5b2ad] mt-1">
                      Clique em &quot;+ Novo Canal&quot; para começar.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create / Edit Modal */}
      {showForm && (
        <div
          className="fixed inset-0 bg-[#111111]/40 z-50 flex items-center justify-center p-4"
          onClick={closeForm}
        >
          <div
            className="bg-white border border-[#dedbd6] rounded-[8px] w-full max-w-lg max-h-[90vh] overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-start justify-between mb-5">
              <div>
                <h2 className="text-[18px] font-normal text-[#111111]">
                  {editingId ? "Editar Canal" : "Novo Canal"}
                </h2>
                <div className="flex items-center gap-1.5 mt-1">
                  <Badge className="bg-[#1877F2]/10 text-[#1877F2] border border-[#1877F2]/20 text-[10px] uppercase tracking-[0.5px] font-semibold rounded-[4px] px-2 py-0.5 h-auto">
                    Meta
                  </Badge>
                  <span className="text-[12px] text-[#7b7b78]">Cloud API Oficial</span>
                </div>
              </div>
              <button
                onClick={closeForm}
                className="text-[#7b7b78] hover:text-[#111111] text-xl leading-none transition-colors mt-0.5"
              >
                &times;
              </button>
            </div>

            <div className="space-y-4">
              {/* Nome */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Nome
                </label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#b5b2ad] focus:border-[#111111] focus:outline-none w-full"
                  placeholder="Ex: Atendimento Principal"
                />
              </div>

              {/* Telefone */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Telefone
                </label>
                <input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] font-mono text-[#111111] placeholder:text-[#b5b2ad] placeholder:font-sans focus:border-[#111111] focus:outline-none w-full"
                  placeholder="5534999999999"
                />
              </div>

              {/* Phone Number ID */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Phone Number ID
                </label>
                <input
                  value={form.meta_phone_number_id}
                  onChange={(e) => setForm({ ...form, meta_phone_number_id: e.target.value })}
                  className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] font-mono text-[#111111] placeholder:text-[#b5b2ad] placeholder:font-sans focus:border-[#111111] focus:outline-none w-full"
                  placeholder="ID do número na Meta"
                />
              </div>

              {/* Modo do Canal */}
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1.5">
                  Modo do Canal
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, mode: "ai" })}
                    className={`flex-1 px-3 py-2 rounded-[6px] text-[14px] border transition-colors ${
                      form.mode === "ai"
                        ? "bg-[#111111] text-white border-[#111111]"
                        : "bg-white text-[#7b7b78] border-[#dedbd6] hover:border-[#111111]"
                    }`}
                  >
                    IA
                  </button>
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, mode: "human" })}
                    className={`flex-1 px-3 py-2 rounded-[6px] text-[14px] border transition-colors ${
                      form.mode === "human"
                        ? "bg-[#111111] text-white border-[#111111]"
                        : "bg-white text-[#7b7b78] border-[#dedbd6] hover:border-[#111111]"
                    }`}
                  >
                    Humano
                  </button>
                </div>
              </div>

              {/* Responsável */}
              <div>
                <label className="block text-[13px] text-[#7b7b78] mb-1">
                  Responsável (vendedor/atendente)
                </label>
                <select
                  value={form.owner_user_id}
                  onChange={(e) => setForm({ ...form, owner_user_id: e.target.value })}
                  className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] bg-white focus:outline-none focus:border-[#111111]"
                >
                  <option value="">— Nenhum (somente admins) —</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name || u.email}
                    </option>
                  ))}
                </select>
                <p className="text-[12px] text-[#7b7b78] mt-1">
                  Vendedores só veem conversas dos seus canais. Admins veem tudo.
                </p>
              </div>

              {/* Ativo */}
              <div className="flex items-center justify-between py-1">
                <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Ativo</label>
                <Switch
                  checked={form.is_active}
                  onCheckedChange={(checked) => setForm({ ...form, is_active: checked })}
                  className="data-checked:bg-[#0bdf50]"
                />
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-[#dedbd6]">
              <button
                onClick={closeForm}
                className="bg-transparent text-[#111111] border border-[#dedbd6] px-[14px] py-2 rounded-[4px] text-[14px] hover:border-[#111111] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.name}
                className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-40 disabled:pointer-events-none"
              >
                {saving ? "Salvando..." : editingId ? "Salvar" : "Criar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

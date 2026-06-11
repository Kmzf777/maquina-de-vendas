"use client";

import { useEffect, useState } from "react";

const WEEKDAYS = [
  { v: 0, label: "Dom" },
  { v: 1, label: "Seg" },
  { v: 2, label: "Ter" },
  { v: 3, label: "Qua" },
  { v: 4, label: "Qui" },
  { v: 5, label: "Sex" },
  { v: 6, label: "Sáb" },
];

interface Channel { id: string; name?: string; phone?: string }
interface Vendedor { id: string; email: string }
interface Config {
  user_id: string;
  channel_id: string;
  display_name: string;
  window_start_minute: number;
  window_end_minute: number;
  active_weekdays: number[];
  active: boolean;
}
interface Override {
  id: string;
  user_id: string | null;
  start_date: string;
  end_date: string;
  reason: string | null;
}

function minToTime(m: number): string {
  const h = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(m % 60).padStart(2, "0");
  return `${h}:${mm}`;
}
function timeToMin(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

export function SlaTab() {
  const [configs, setConfigs] = useState<Config[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [vendedores, setVendedores] = useState<Vendedor[]>([]);
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [target, setTarget] = useState<number>(20);
  const [loading, setLoading] = useState(true);

  // form: novo vendedor
  const [newUserId, setNewUserId] = useState("");
  const [newChannelId, setNewChannelId] = useState("");
  const [newName, setNewName] = useState("");

  // form: nova anulação
  const [ovUser, setOvUser] = useState<string>(""); // "" = global
  const [ovStart, setOvStart] = useState("");
  const [ovEnd, setOvEnd] = useState("");
  const [ovReason, setOvReason] = useState("");

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadAll() {
    const [cfgRes, chRes, venRes, ovRes, tgtRes] = await Promise.all([
      fetch("/api/admin/sla/config"),
      fetch("/api/channels"),
      fetch("/api/admin/sla/vendedores"),
      fetch("/api/admin/sla/overrides"),
      fetch("/api/admin/sla/target"),
    ]);
    if (cfgRes.ok) setConfigs(await cfgRes.json());
    if (chRes.ok) setChannels(await chRes.json());
    if (venRes.ok) setVendedores(await venRes.json());
    if (ovRes.ok) setOverrides(await ovRes.json());
    if (tgtRes.ok) setTarget((await tgtRes.json()).target_minutes ?? 20);
    setLoading(false);
  }

  async function saveConfig(cfg: Config) {
    const res = await fetch("/api/admin/sla/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    if (res.ok) void loadAll();
  }

  async function addVendedor(e: React.FormEvent) {
    e.preventDefault();
    if (!newUserId || !newChannelId) return;
    await saveConfig({
      user_id: newUserId,
      channel_id: newChannelId,
      display_name: newName.trim(),
      window_start_minute: 600,
      window_end_minute: 960,
      active_weekdays: [1, 2, 3, 4, 5],
      active: true,
    });
    setNewUserId("");
    setNewChannelId("");
    setNewName("");
  }

  async function saveTarget() {
    await fetch("/api/admin/sla/target", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_minutes: target }),
    });
  }

  async function addOverride(e: React.FormEvent) {
    e.preventDefault();
    if (!ovStart || !ovEnd) return;
    const res = await fetch("/api/admin/sla/overrides", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: ovUser || null,
        start_date: ovStart,
        end_date: ovEnd,
        reason: ovReason.trim() || null,
      }),
    });
    if (res.ok) {
      setOvStart("");
      setOvEnd("");
      setOvReason("");
      setOvUser("");
      void loadAll();
    }
  }

  async function deleteOverride(id: string) {
    if (!confirm("Remover esta anulação?")) return;
    const res = await fetch(`/api/admin/sla/overrides/${id}`, { method: "DELETE" });
    if (res.ok) void loadAll();
  }

  function nameForUser(userId: string | null): string {
    if (userId === null) return "Global (todos)";
    const cfg = configs.find((c) => c.user_id === userId);
    if (cfg?.display_name) return cfg.display_name;
    const v = vendedores.find((x) => x.id === userId);
    return v?.email ?? userId.slice(0, 8);
  }

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-6">
        <div className="w-4 h-4 border-2 border-[#dedbd6] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#7b7b78] text-[14px]">Carregando configuração de SLA...</p>
      </div>
    );
  }

  const inputCls =
    "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none";
  const btnDark =
    "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-105 active:scale-[0.9]";

  return (
    <div className="space-y-6">
      {/* Alvo global */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111] mb-4">Alvo de SLA</h2>
        <div className="flex items-center gap-3">
          <span className="text-[14px] text-[#7b7b78]">Lead em atraso após</span>
          <input
            type="number"
            min={1}
            value={target}
            onChange={(e) => setTarget(Number(e.target.value))}
            className={`${inputCls} w-24`}
          />
          <span className="text-[14px] text-[#7b7b78]">minutos comerciais sem resposta</span>
          <button onClick={saveTarget} className={btnDark}>Salvar</button>
        </div>
      </div>

      {/* Vendedores */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111] mb-4">Vendedores</h2>

        <div className="space-y-3 mb-5">
          {configs.length === 0 && (
            <p className="text-[#7b7b78] text-[14px]">Nenhum vendedor configurado.</p>
          )}
          {configs.map((cfg) => (
            <div key={cfg.user_id} className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-wrap items-center gap-3">
              <input
                type="text"
                value={cfg.display_name}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, display_name: e.target.value } : c))
                  )
                }
                placeholder="Nome"
                className={`${inputCls} w-32`}
              />
              <select
                value={cfg.channel_id}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, channel_id: e.target.value } : c))
                  )
                }
                className={inputCls}
              >
                {channels.map((ch) => (
                  <option key={ch.id} value={ch.id}>{ch.name ?? ch.phone ?? ch.id.slice(0, 8)}</option>
                ))}
              </select>
              <input
                type="time"
                value={minToTime(cfg.window_start_minute)}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, window_start_minute: timeToMin(e.target.value) } : c))
                  )
                }
                className={inputCls}
              />
              <span className="text-[#7b7b78]">até</span>
              <input
                type="time"
                value={minToTime(cfg.window_end_minute)}
                onChange={(e) =>
                  setConfigs((prev) =>
                    prev.map((c) => (c.user_id === cfg.user_id ? { ...c, window_end_minute: timeToMin(e.target.value) } : c))
                  )
                }
                className={inputCls}
              />
              <div className="flex items-center gap-1">
                {WEEKDAYS.map((wd) => {
                  const on = cfg.active_weekdays.includes(wd.v);
                  return (
                    <button
                      key={wd.v}
                      type="button"
                      onClick={() =>
                        setConfigs((prev) =>
                          prev.map((c) =>
                            c.user_id === cfg.user_id
                              ? {
                                  ...c,
                                  active_weekdays: on
                                    ? c.active_weekdays.filter((d) => d !== wd.v)
                                    : [...c.active_weekdays, wd.v].sort(),
                                }
                              : c
                          )
                        )
                      }
                      className={`px-2 py-1 rounded-[4px] text-[12px] border ${
                        on ? "bg-[#111111] text-white border-[#111111]" : "bg-white text-[#7b7b78] border-[#dedbd6]"
                      }`}
                    >
                      {wd.label}
                    </button>
                  );
                })}
              </div>
              <label className="flex items-center gap-1 text-[13px] text-[#7b7b78]">
                <input
                  type="checkbox"
                  checked={cfg.active}
                  onChange={(e) =>
                    setConfigs((prev) =>
                      prev.map((c) => (c.user_id === cfg.user_id ? { ...c, active: e.target.checked } : c))
                    )
                  }
                />
                Ativo
              </label>
              <button onClick={() => saveConfig(cfg)} className={`${btnDark} ml-auto`}>Salvar</button>
            </div>
          ))}
        </div>

        {/* Adicionar vendedor */}
        <form onSubmit={addVendedor} className="flex flex-wrap items-center gap-3 p-4 bg-white border border-[#dedbd6] rounded-[8px]">
          <select value={newUserId} onChange={(e) => setNewUserId(e.target.value)} className={inputCls} required>
            <option value="">Selecione o vendedor…</option>
            {vendedores.map((v) => (
              <option key={v.id} value={v.id}>{v.email}</option>
            ))}
          </select>
          <select value={newChannelId} onChange={(e) => setNewChannelId(e.target.value)} className={inputCls} required>
            <option value="">Selecione o canal…</option>
            {channels.map((ch) => (
              <option key={ch.id} value={ch.id}>{ch.name ?? ch.phone ?? ch.id.slice(0, 8)}</option>
            ))}
          </select>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Nome de exibição"
            className={`${inputCls} w-40`}
          />
          <button type="submit" className={btnDark}>+ Adicionar</button>
        </form>
      </div>

      {/* Anulações */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111] mb-1">Anulações</h2>
        <p className="text-[13px] text-[#7b7b78] mb-4">Dias removidos da medição (folgas, viagens, feriados).</p>

        <div className="space-y-2 mb-5">
          {overrides.length === 0 && (
            <p className="text-[#7b7b78] text-[14px]">Nenhuma anulação cadastrada.</p>
          )}
          {overrides.map((ov) => (
            <div key={ov.id} className="flex items-center gap-3 bg-white border border-[#dedbd6] rounded-[8px] px-4 py-2">
              <span className="text-[14px] text-[#111111] font-normal w-40">{nameForUser(ov.user_id)}</span>
              <span className="text-[14px] text-[#7b7b78]">{ov.start_date} → {ov.end_date}</span>
              {ov.reason && <span className="text-[13px] text-[#7b7b78] italic">{ov.reason}</span>}
              <button
                onClick={() => deleteOverride(ov.id)}
                className="ml-auto p-2 rounded-[4px] text-[#7b7b78] hover:text-[#c41c1c] transition-colors"
                title="Remover"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          ))}
        </div>

        <form onSubmit={addOverride} className="flex flex-wrap items-center gap-3 p-4 bg-white border border-[#dedbd6] rounded-[8px]">
          <select value={ovUser} onChange={(e) => setOvUser(e.target.value)} className={inputCls}>
            <option value="">Global (todos)</option>
            {configs.map((c) => (
              <option key={c.user_id} value={c.user_id}>{c.display_name || c.user_id.slice(0, 8)}</option>
            ))}
          </select>
          <input type="date" value={ovStart} onChange={(e) => setOvStart(e.target.value)} className={inputCls} required />
          <span className="text-[#7b7b78]">até</span>
          <input type="date" value={ovEnd} onChange={(e) => setOvEnd(e.target.value)} className={inputCls} required />
          <input
            type="text"
            value={ovReason}
            onChange={(e) => setOvReason(e.target.value)}
            placeholder="Motivo (folga, viagem…)"
            className={`${inputCls} w-44`}
          />
          <button type="submit" className={btnDark}>+ Adicionar</button>
        </form>
      </div>
    </div>
  );
}

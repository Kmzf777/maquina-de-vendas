"use client";

import { useEffect, useState } from "react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";

interface BlingStatus {
  configured: boolean;
  connected: boolean;
  enabled: boolean;
  access_expires_at: string | null;
  refresh_expires_at: string | null;
  scope: string | null;
}

interface CrmUser {
  id: string;
  email: string;
  name: string;
  role: string;
}

interface BlingSeller {
  id: number;
  nome: string;
  situacao: string | null;
}

/**
 * O refresh_token do Bling dura 30 dias. Se ele expirar, não há renovação
 * automática possível: alguém precisa refazer o OAuth no navegador. Cinco dias
 * de antecedência é o aviso.
 */
const REFRESH_WARN_DAYS = 5;

const SYNC_LABELS: Record<string, string> = {
  produtos: "Produtos",
  contatos: "Contatos",
  formas_pagamento: "Formas de pagamento",
  vendedores: "Vendedores",
};

function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  return (ms - Date.now()) / 86_400_000;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return "—";
  return new Date(ms).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function BlingSettings() {
  const [status, setStatus] = useState<BlingStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [connecting, setConnecting] = useState(false);

  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<Record<string, number> | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const [users, setUsers] = useState<CrmUser[]>([]);
  const [sellers, setSellers] = useState<BlingSeller[]>([]);
  const [sellerMap, setSellerMap] = useState<Record<string, number | null>>({});
  const [savingEmail, setSavingEmail] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  const [backfillOpen, setBackfillOpen] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillResult, setBackfillResult] = useState<string | null>(null);
  const [backfillError, setBackfillError] = useState<string | null>(null);

  useEffect(() => {
    void loadAll();
  }, []);

  async function loadStatus() {
    try {
      const res = await fetch("/api/bling/status", { cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setStatusError(body?.error ?? "Não foi possível ler o estado da integração.");
        setStatus(null);
        return;
      }
      setStatusError(null);
      setStatus(body as BlingStatus);
    } catch {
      setStatusError("Backend inacessível.");
      setStatus(null);
    }
  }

  async function loadAll() {
    setLoading(true);
    const [, usersRes, sellersRes, mapRes] = await Promise.all([
      loadStatus(),
      fetch("/api/users", { cache: "no-store" }),
      fetch("/api/bling/sellers", { cache: "no-store" }),
      fetch("/api/bling/seller-map", { cache: "no-store" }),
    ]);

    if (usersRes.ok) {
      const list = (await usersRes.json()) as CrmUser[];
      setUsers(
        [...list]
          .filter((u) => !!u.email)
          .sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email, "pt-BR"))
      );
    }
    if (sellersRes.ok) {
      const body = await sellersRes.json();
      setSellers((body?.data ?? []) as BlingSeller[]);
    }
    if (mapRes.ok) {
      const body = await mapRes.json();
      const rows = (body?.data ?? []) as { user_email: string; bling_seller_id: number }[];
      setSellerMap(Object.fromEntries(rows.map((r) => [r.user_email, r.bling_seller_id])));
    }
    setLoading(false);
  }

  async function connect() {
    setConnecting(true);
    setStatusError(null);
    try {
      const res = await fetch("/api/bling/oauth/authorize", { cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body?.url) {
        setStatusError(
          body?.error === "not_configured"
            ? "Credenciais do app Bling não configuradas no servidor (BLING_CLIENT_ID / BLING_CLIENT_SECRET)."
            : "Não foi possível iniciar a conexão com o Bling."
        );
        setConnecting(false);
        return;
      }
      window.location.href = body.url as string;
    } catch {
      setStatusError("Backend inacessível.");
      setConnecting(false);
    }
  }

  async function runSync() {
    setSyncing(true);
    setSyncError(null);
    setSyncResult(null);
    try {
      const res = await fetch("/api/bling/sync", { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setSyncError(body?.error ?? "Falha ao sincronizar.");
      } else {
        setSyncResult(body as Record<string, number>);
        // Vendedores novos podem ter entrado agora — recarrega o que a tela mostra.
        void loadAll();
      }
    } catch {
      setSyncError("Backend inacessível.");
    } finally {
      setSyncing(false);
    }
  }

  async function saveSellerMap(email: string, value: string) {
    const sellerId = value === "" ? null : Number(value);
    setSavingEmail(email);
    setMapError(null);
    const anterior = sellerMap[email] ?? null;
    setSellerMap((prev) => ({ ...prev, [email]: sellerId }));
    try {
      const res = await fetch("/api/bling/seller-map", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_email: email, bling_seller_id: sellerId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setMapError(body?.error ?? "Não foi possível salvar o vínculo.");
        setSellerMap((prev) => ({ ...prev, [email]: anterior }));
      }
    } catch {
      setMapError("Backend inacessível.");
      setSellerMap((prev) => ({ ...prev, [email]: anterior }));
    } finally {
      setSavingEmail(null);
    }
  }

  async function runBackfill() {
    setBackfillOpen(false);
    setBackfilling(true);
    setBackfillError(null);
    setBackfillResult(null);
    try {
      const res = await fetch("/api/bling/backfill?months=12", { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBackfillError(body?.error ?? "Falha na importação do histórico.");
      } else {
        setBackfillResult(
          `${body?.pedidos ?? 0} pedidos importados em ${body?.janelas ?? 0} janelas.`
        );
      }
    } catch {
      setBackfillError(
        "A conexão caiu antes de o job terminar. A importação pode continuar rodando no servidor — confira os logs antes de repetir."
      );
    } finally {
      setBackfilling(false);
    }
  }

  const inputCls =
    "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none";
  const btnDark =
    "bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-105 active:scale-[0.9] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100";
  const btnGhost =
    "bg-white border border-[#dedbd6] text-[#111111] px-[14px] py-2 rounded-[4px] text-[14px] hover:bg-[#f0ede8] transition-colors disabled:opacity-40 disabled:cursor-not-allowed";

  if (loading) {
    return (
      <div className="flex items-center gap-3 py-6">
        <div className="w-4 h-4 border-2 border-[#dedbd6] border-t-transparent rounded-full animate-spin" />
        <p className="text-[#7b7b78] text-[14px]">Carregando integração com o Bling…</p>
      </div>
    );
  }

  const conectado = !!status?.connected;
  const diasRefresh = daysUntil(status?.refresh_expires_at);
  const refreshExpirando =
    conectado && diasRefresh !== null && diasRefresh < REFRESH_WARN_DAYS;

  return (
    <div className="space-y-6">
      {/* ---------------------------------------------------------------- */}
      {/* Conexão                                                          */}
      {/* ---------------------------------------------------------------- */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-[14px] font-normal text-[#111111]">Conexão com o Bling</h2>
            <p className="text-[13px] text-[#7b7b78] mt-1">
              O Bling é a fonte da verdade do faturamento. O pedido nasce aqui e é criado lá.
            </p>
          </div>
          <span className="flex items-center gap-2 text-[13px] whitespace-nowrap">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: conectado ? "#1f9d57" : "#7b7b78" }}
            />
            <span className={conectado ? "text-[#111111]" : "text-[#7b7b78]"}>
              {conectado ? "Conectado" : "Desconectado"}
            </span>
          </span>
        </div>

        {statusError && (
          <p className="text-[13px] text-[#c41c1c] mb-4">{statusError}</p>
        )}

        {status && !status.configured && (
          <p className="text-[13px] text-[#c41c1c] mb-4">
            Credenciais do app Bling ausentes no servidor. Configure BLING_CLIENT_ID,
            BLING_CLIENT_SECRET e BLING_REDIRECT_URI antes de conectar.
          </p>
        )}

        {status && status.configured && !status.enabled && (
          <p className="text-[13px] text-[#7b7b78] mb-4">
            Integração desligada por configuração (BLING_ENABLED). Os workers de sync e de
            fila não rodam enquanto ela estiver assim.
          </p>
        )}

        {refreshExpirando && (
          <div
            className="mb-4 rounded-[6px] border px-4 py-3"
            style={{ borderColor: "#ff5600", backgroundColor: "#ff56000d" }}
          >
            <p className="text-[13px] text-[#111111]">
              <strong className="font-medium">Autorização expirando.</strong> O acesso ao
              Bling vence em {Math.max(0, Math.ceil(diasRefresh ?? 0))} dia(s)
              ({formatDate(status?.refresh_expires_at)}). Reconecte antes disso — depois de
              expirar, só o fluxo de autorização manual traz a integração de volta.
            </p>
          </div>
        )}

        {conectado && (
          <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-5">
            <div>
              <dt className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Access token</dt>
              <dd className="text-[13px] text-[#111111] mt-1">{formatDate(status?.access_expires_at)}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Autorização até</dt>
              <dd className="text-[13px] text-[#111111] mt-1">{formatDate(status?.refresh_expires_at)}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Escopos</dt>
              <dd className="text-[13px] text-[#111111] mt-1 break-words">{status?.scope || "—"}</dd>
            </div>
          </dl>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={connect}
            disabled={connecting || (status ? !status.configured : false)}
            className={btnDark}
          >
            {connecting ? "Abrindo o Bling…" : conectado ? "Reconectar" : "Conectar ao Bling"}
          </button>
          <button
            type="button"
            onClick={runSync}
            disabled={syncing || !conectado}
            className={btnGhost}
            title={conectado ? "" : "Conecte a conta antes de sincronizar"}
          >
            {syncing ? "Sincronizando…" : "Sincronizar agora"}
          </button>
        </div>

        {syncError && <p className="text-[13px] text-[#c41c1c] mt-3">{syncError}</p>}
        {syncResult && (
          <div className="flex flex-wrap gap-2 mt-3">
            {Object.entries(syncResult).map(([key, value]) => (
              <span
                key={key}
                className="text-[12px] text-[#7b7b78] bg-white border border-[#dedbd6] rounded-full px-3 py-1"
              >
                {SYNC_LABELS[key] ?? key}: <span className="text-[#111111]">{String(value)}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Vendedores                                                       */}
      {/* ---------------------------------------------------------------- */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111]">Vendedores</h2>
        <p className="text-[13px] text-[#7b7b78] mt-1 mb-4">
          Quem vende no CRM ↔ quem aparece como vendedor no pedido do Bling. Sem vínculo, o
          pedido é criado sem vendedor — a venda não é bloqueada por isso.
        </p>

        {mapError && <p className="text-[13px] text-[#c41c1c] mb-3">{mapError}</p>}

        {sellers.length === 0 && (
          <p className="text-[13px] text-[#7b7b78] mb-3">
            Nenhum vendedor espelhado ainda. Rode &quot;Sincronizar agora&quot; para trazer a
            lista do Bling.
          </p>
        )}

        <div className="space-y-2">
          {users.length === 0 && (
            <p className="text-[13px] text-[#7b7b78]">Nenhum usuário no CRM.</p>
          )}
          {users.map((u) => (
            <div
              key={u.id}
              className="bg-white border border-[#dedbd6] rounded-[8px] px-4 py-3 flex flex-wrap items-center gap-3"
            >
              <div className="min-w-[180px]">
                <p className="text-[13px] text-[#111111] truncate">{u.name || u.email}</p>
                <p className="text-[12px] text-[#7b7b78] truncate">{u.email}</p>
              </div>
              <select
                value={sellerMap[u.email] != null ? String(sellerMap[u.email]) : ""}
                onChange={(e) => void saveSellerMap(u.email, e.target.value)}
                disabled={sellers.length === 0 || savingEmail === u.email}
                className={`${inputCls} ml-auto min-w-[200px] disabled:opacity-50`}
              >
                <option value="">Sem vínculo</option>
                {sellers.map((s) => (
                  <option key={s.id} value={String(s.id)}>
                    {s.nome}
                  </option>
                ))}
              </select>
              <span className="text-[12px] text-[#7b7b78] w-[60px]">
                {savingEmail === u.email ? "salvando…" : ""}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Histórico                                                        */}
      {/* ---------------------------------------------------------------- */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111]">Histórico de pedidos</h2>
        <p className="text-[13px] text-[#7b7b78] mt-1 mb-4">
          Importa os pedidos dos últimos 12 meses do Bling para dentro do CRM. Roda uma vez,
          sob demanda, e leva vários minutos.
        </p>
        <button
          type="button"
          onClick={() => setBackfillOpen(true)}
          disabled={backfilling || !conectado}
          className={btnGhost}
          title={conectado ? "" : "Conecte a conta antes de importar"}
        >
          {backfilling ? "Importando…" : "Importar histórico (12 meses)"}
        </button>
        {backfillError && <p className="text-[13px] text-[#c41c1c] mt-3">{backfillError}</p>}
        {backfillResult && <p className="text-[13px] text-[#111111] mt-3">{backfillResult}</p>}
      </div>

      {/* Confirmação explícita: o job é longo e consome cota da API do Bling. */}
      <AlertDialog
        open={backfillOpen}
        onOpenChange={(open) => { if (!open) setBackfillOpen(false); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Importar histórico de 12 meses?</AlertDialogTitle>
            <AlertDialogDescription>
              A importação percorre todos os pedidos de venda dos últimos 12 meses no Bling.
              É um job longo (vários minutos), consome cota da API e não deve ser disparado
              duas vezes ao mesmo tempo. Pedidos já importados são atualizados, não duplicados.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={runBackfill}>Importar agora</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

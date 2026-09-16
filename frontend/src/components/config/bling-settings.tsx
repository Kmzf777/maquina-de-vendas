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
import {
  CONTA_PADRAO,
  contaPadrao,
  contasDisponiveis,
  precisaSeletor,
  type ContaBling,
} from "@/lib/bling-accounts";
import {
  comVinculo,
  indexarVinculos,
  vinculoDe,
  type MapaVendedores,
} from "@/lib/bling-seller-map";

/**
 * Uma linha de `accounts` em `GET /api/bling/status` (formato aditivo, ver
 * Tasks 4/11): estende `ContaBling` com os campos de token que so a tela de
 * admin mostra. `ContaBling` sozinho (usado pelo seletor de venda) nao tem
 * esses tres campos de proposito — sao informacao de administracao.
 */
interface ContaStatus extends ContaBling {
  access_expires_at: string | null;
  refresh_expires_at: string | null;
  scope: string | null;
}

interface BlingStatus {
  configured: boolean;
  connected: boolean;
  enabled: boolean;
  access_expires_at: string | null;
  refresh_expires_at: string | null;
  scope: string | null;
  // Os seis campos acima sao sempre os dados da conta DEFAULT (ver comentario
  // de app/bling/router.py:bling_status no backend) — mantidos por
  // compatibilidade. Esta tela migrou para ler `accounts`; `contasDoStatus`
  // abaixo so recorre a eles quando `accounts` falta (resposta de formato
  // antigo, durante uma transicao de deploy).
  accounts?: ContaStatus[];
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

/** Uma conta veio de `sync_all`: contagens por recurso, ou um erro isolado
 *  (a falha numa conta nao derruba a outra — ver backend/app/bling/sync.py). */
interface SyncCounts {
  produtos?: number;
  contatos?: number;
  formas_pagamento?: number;
  vendedores?: number;
  situacoes?: number;
  erro?: string;
}

/** `POST /bling/sync` aninhou o retorno por conta (Task 6): antes era
 *  `{produtos: N, ...}`, agora e `{default: {produtos: N, ...}, secundaria: {...}}`. */
type SyncResult = Record<string, SyncCounts>;

/**
 * O refresh_token do Bling dura 30 dias. Se ele expirar, nao ha renovacao
 * automatica possivel: alguem precisa refazer o OAuth no navegador. Cinco dias
 * de antecedencia e o aviso.
 */
const REFRESH_WARN_DAYS = 5;

const SYNC_LABELS: Record<string, string> = {
  produtos: "Produtos",
  contatos: "Contatos",
  formas_pagamento: "Formas de pagamento",
  vendedores: "Vendedores",
  situacoes: "Situações",
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

/**
 * Lista de contas a renderizar, com fallback para o formato antigo (sem
 * `accounts`) usando os seis campos de topo — todos da conta default, mesma
 * regra do backend. Isso e o que deixa "os seis campos de topo continuam
 * funcionando" verdadeiro sem duplicar a UI: com `accounts` presente (o caso
 * normal hoje, ver router.py), o fallback nunca roda.
 */
function contasDoStatus(status: BlingStatus | null): ContaStatus[] {
  if (!status) return [];
  if (status.accounts && status.accounts.length > 0) return status.accounts;
  return [
    {
      account: CONTA_PADRAO,
      label: "Bling",
      configured: status.configured,
      connected: status.connected,
      access_expires_at: status.access_expires_at,
      refresh_expires_at: status.refresh_expires_at,
      scope: status.scope,
    },
  ];
}

export function BlingSettings() {
  const [status, setStatus] = useState<BlingStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Slug da conta cujo OAuth esta em andamento (redirecionando o navegador),
  // ou null quando nenhuma esta. Por conta porque cada linha tem seu proprio
  // botao Conectar/Reconectar agora.
  const [connecting, setConnecting] = useState<string | null>(null);

  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const [users, setUsers] = useState<CrmUser[]>([]);
  const [sellers, setSellers] = useState<BlingSeller[]>([]);
  // Conta cujo quadro de vendedores esta aberto. O Bling identifica vendedor
  // por id proprio de cada CNPJ: a lista oferecida e o vinculo salvo sao
  // SEMPRE desta conta, nunca a uniao das duas.
  const [contaVendedores, setContaVendedores] = useState<string>(CONTA_PADRAO);
  // Chave COMPOSTA (conta + e-mail): o mesmo usuario tem um id de vendedor em
  // cada CNPJ, e indexar so pelo e-mail colapsaria as duas linhas em uma.
  const [sellerMap, setSellerMap] = useState<MapaVendedores>({});
  const [savingEmail, setSavingEmail] = useState<string | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  const [backfillOpen, setBackfillOpen] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillResult, setBackfillResult] = useState<string | null>(null);
  const [backfillError, setBackfillError] = useState<string | null>(null);

  useEffect(() => {
    void loadAll();
  }, []);

  // Separado de loadAll porque refaz a busca a cada troca de conta — os
  // vendedores sao os do CNPJ selecionado, e o id de um nao existe no outro.
  useEffect(() => {
    void loadSellers(contaVendedores);
  }, [contaVendedores]);

  // O estado inicial e CONTA_PADRAO, mas ela pode nao estar conectada (a
  // segunda conta conectada primeiro, ou a autorizacao da primeira vencida).
  // Sem este ajuste o quadro ficaria preso numa conta sem espelho e o seletor
  // — que so aparece com DUAS contas disponiveis — nao daria como sair dela.
  useEffect(() => {
    const disponiveis = contasDisponiveis(contasDoStatus(status));
    if (disponiveis.length === 0) return;
    if (disponiveis.some((c) => c.account === contaVendedores)) return;
    const padrao = contaPadrao(contasDoStatus(status));
    if (padrao) setContaVendedores(padrao);
  }, [status, contaVendedores]);

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

  async function loadSellers(account: string) {
    try {
      const res = await fetch(
        `/api/bling/sellers?account=${encodeURIComponent(account)}`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        setSellers([]);
        return;
      }
      const body = await res.json().catch(() => ({}));
      setSellers((body?.data ?? []) as BlingSeller[]);
    } catch {
      setSellers([]);
    }
  }

  async function loadAll() {
    setLoading(true);
    const [, usersRes, mapRes] = await Promise.all([
      loadStatus(),
      fetch("/api/users", { cache: "no-store" }),
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
    if (mapRes.ok) {
      const body = await mapRes.json();
      setSellerMap(indexarVinculos(body?.data ?? []));
    }
    setLoading(false);
  }

  async function connect(account: string) {
    setConnecting(account);
    setStatusError(null);
    try {
      const res = await fetch(
        `/api/bling/oauth/authorize?account=${encodeURIComponent(account)}`,
        { cache: "no-store" }
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body?.url) {
        setStatusError(
          body?.error === "not_configured"
            ? "Credenciais do app Bling não configuradas no servidor (BLING_CLIENT_ID / BLING_CLIENT_SECRET)."
            : "Não foi possível iniciar a conexão com o Bling."
        );
        setConnecting(null);
        return;
      }
      window.location.href = body.url as string;
    } catch {
      setStatusError("Backend inacessível.");
      setConnecting(null);
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
        setSyncResult(body as SyncResult);
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
    const anterior = vinculoDe(sellerMap, contaVendedores, email);
    setSellerMap((prev) => comVinculo(prev, contaVendedores, email, sellerId));
    try {
      const res = await fetch("/api/bling/seller-map", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        // `account` e obrigatorio: sem ele a rota cai em CONTA_PADRAO e grava
        // um id do CNPJ 2 na linha da conta 1.
        body: JSON.stringify({
          user_email: email,
          account: contaVendedores,
          bling_seller_id: sellerId,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setMapError(body?.error ?? "Não foi possível salvar o vínculo.");
        setSellerMap((prev) => comVinculo(prev, contaVendedores, email, anterior));
      }
    } catch {
      setMapError("Backend inacessível.");
      setSellerMap((prev) => comVinculo(prev, contaVendedores, email, anterior));
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

  const contas = contasDoStatus(status);
  const multiplasContas = contas.length > 1;
  const algumaContaConfigurada = contas.some((c) => c.configured);
  const algumaContaConectada = contas.some((c) => c.connected);

  return (
    <div className="space-y-6">
      {/* ---------------------------------------------------------------- */}
      {/* Conexao                                                          */}
      {/* ---------------------------------------------------------------- */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-6">
        <h2 className="text-[14px] font-normal text-[#111111]">Conexão com o Bling</h2>
        <p className="text-[13px] text-[#7b7b78] mt-1 mb-4">
          O Bling é a fonte da verdade do faturamento. O pedido nasce aqui e é criado lá.
        </p>

        {statusError && (
          <p className="text-[13px] text-[#c41c1c] mb-4">{statusError}</p>
        )}

        {status && algumaContaConfigurada && !status.enabled && (
          <p className="text-[13px] text-[#7b7b78] mb-4">
            Integração desligada por configuração (BLING_ENABLED). Os workers de sync e de
            fila não rodam enquanto ela estiver assim.
          </p>
        )}

        <div className="space-y-3">
          {contas.map((conta) => {
            const diasRefresh = daysUntil(conta.refresh_expires_at);
            const refreshExpirando =
              conta.connected && diasRefresh !== null && diasRefresh < REFRESH_WARN_DAYS;

            return (
              <div
                key={conta.account}
                className="bg-white border border-[#dedbd6] rounded-[8px] p-4"
              >
                <div className="flex items-start justify-between gap-4 mb-3">
                  <p className="text-[13px] font-medium text-[#111111]">{conta.label}</p>
                  <span className="flex items-center gap-2 text-[13px] whitespace-nowrap">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: conta.connected ? "#1f9d57" : "#7b7b78" }}
                    />
                    <span className={conta.connected ? "text-[#111111]" : "text-[#7b7b78]"}>
                      {conta.connected ? "Conectado" : "Desconectado"}
                    </span>
                  </span>
                </div>

                {!conta.configured && (
                  <p className="text-[13px] text-[#c41c1c] mb-3">
                    {conta.account === CONTA_PADRAO
                      ? "Credenciais do app Bling ausentes no servidor. Configure BLING_CLIENT_ID, BLING_CLIENT_SECRET e BLING_REDIRECT_URI antes de conectar."
                      : `Credenciais ausentes para esta conta. Configure BLING_${conta.account.toUpperCase()}_CLIENT_ID e BLING_${conta.account.toUpperCase()}_CLIENT_SECRET, ou deixe cair para BLING_CLIENT_ID/BLING_CLIENT_SECRET (compartilhados com a conta padrão).`}
                  </p>
                )}

                {refreshExpirando && (
                  <div
                    className="mb-3 rounded-[6px] border px-4 py-3"
                    style={{ borderColor: "#ff5600", backgroundColor: "#ff56000d" }}
                  >
                    <p className="text-[13px] text-[#111111]">
                      <strong className="font-medium">Autorização expirando.</strong> O acesso
                      ao Bling{multiplasContas ? ` (${conta.label})` : ""} vence em{" "}
                      {Math.max(0, Math.ceil(diasRefresh ?? 0))} dia(s)
                      ({formatDate(conta.refresh_expires_at)}). Reconecte antes disso — depois
                      de expirar, só o fluxo de autorização manual traz a integração de volta.
                    </p>
                  </div>
                )}

                {conta.connected && (
                  <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
                    <div>
                      <dt className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Access token</dt>
                      <dd className="text-[13px] text-[#111111] mt-1">{formatDate(conta.access_expires_at)}</dd>
                    </div>
                    <div>
                      <dt className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Autorização até</dt>
                      <dd className="text-[13px] text-[#111111] mt-1">{formatDate(conta.refresh_expires_at)}</dd>
                    </div>
                    <div>
                      <dt className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Escopos</dt>
                      <dd className="text-[13px] text-[#111111] mt-1 break-words">{conta.scope || "—"}</dd>
                    </div>
                  </dl>
                )}

                <button
                  type="button"
                  onClick={() => connect(conta.account)}
                  disabled={connecting === conta.account || !conta.configured}
                  className={btnDark}
                >
                  {connecting === conta.account
                    ? "Abrindo o Bling…"
                    : conta.connected
                      ? "Reconectar"
                      : "Conectar ao Bling"}
                </button>
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-3 mt-4">
          <button
            type="button"
            onClick={runSync}
            disabled={syncing || !algumaContaConectada}
            className={btnGhost}
            title={algumaContaConectada ? "" : "Conecte ao menos uma conta antes de sincronizar"}
          >
            {syncing ? "Sincronizando…" : "Sincronizar agora"}
          </button>
        </div>

        {syncError && <p className="text-[13px] text-[#c41c1c] mt-3">{syncError}</p>}
        {syncResult && (
          <div className="space-y-3 mt-3">
            {Object.entries(syncResult).map(([account, counts]) => {
              const rotulo = contas.find((c) => c.account === account)?.label ?? account;
              return (
                <div key={account}>
                  {multiplasContas && (
                    <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1.5">
                      {rotulo}
                    </p>
                  )}
                  {counts.erro ? (
                    <p className="text-[13px] text-[#c41c1c]">{counts.erro}</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(counts).map(([key, value]) => (
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
              );
            })}
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

        {/* Seletor so aparece com mais de uma conta CONECTADA: vendedor so
            existe no espelho depois do sync, que exige OAuth. Oferecer uma
            conta sem conexao daria um dropdown vazio sem explicar por que. */}
        {precisaSeletor(contas) && (
          <div className="flex items-center gap-2 mb-4">
            <label htmlFor="conta-vendedores" className="text-[13px] text-[#111111]">
              Conta
            </label>
            <select
              id="conta-vendedores"
              value={contaVendedores}
              onChange={(e) => setContaVendedores(e.target.value)}
              className={`${inputCls} min-w-[200px]`}
            >
              {contasDisponiveis(contas).map((c) => (
                <option key={c.account} value={c.account}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        )}

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
                value={
                  vinculoDe(sellerMap, contaVendedores, u.email) != null
                    ? String(vinculoDe(sellerMap, contaVendedores, u.email))
                    : ""
                }
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
      {/* Historico                                                        */}
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
          disabled={backfilling || !algumaContaConectada}
          className={btnGhost}
          title={algumaContaConectada ? "" : "Conecte ao menos uma conta antes de importar"}
        >
          {backfilling ? "Importando…" : "Importar histórico (12 meses)"}
        </button>
        {backfillError && <p className="text-[13px] text-[#c41c1c] mt-3">{backfillError}</p>}
        {backfillResult && <p className="text-[13px] text-[#111111] mt-3">{backfillResult}</p>}
      </div>

      {/* Confirmacao explicita: o job e longo e consome cota da API do Bling. */}
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

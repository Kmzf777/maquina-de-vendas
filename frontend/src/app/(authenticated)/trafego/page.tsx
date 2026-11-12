"use client";

// Página admin "Relatório Campanhas" (/trafego): rastreio de campanhas e leads x vendas registradas.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useCurrentRole } from "@/hooks/use-current-role";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { CampaignReportTable, type CampaignRow, type ReportTotal, type ChannelSubtotals } from "@/components/trafego/campaign-report-table";
import { ConversoesEnviadas } from "@/components/trafego/conversoes-enviadas";
import { ReportSummaryPanel } from "@/components/trafego/report-summary";
import type { ReportSummary } from "@/lib/traffic-summary";
import { FRASE_MODO, MODO_PADRAO, linhaSync, type RodadaSync, type TrafficMode } from "@/lib/traffic-mode";
// F5 (jornada do lead): atribuição pela primeira/última origem, jornadas e "Sem rastreio".
import { AtribuicaoSelect } from "@/components/trafego/atribuicao-select";
import { JornadasMulticanal } from "@/components/trafego/jornadas-multicanal";
import { SemRastreioDetalhe } from "@/components/trafego/sem-rastreio-detalhe";
import { escolherAtribuicao, type Atribuicao, type JornadasResumo, type ParteAtribuida, type SemRastreioResumo } from "@/lib/traffic-jornada";

type Report = { mode: string; period: string; rows: CampaignRow[]; total: ReportTotal; channel_subtotals: ChannelSubtotals; summary?: ReportSummary;
  por_atribuicao?: Partial<Record<Atribuicao, ParteAtribuida<CampaignRow, ReportTotal, ChannelSubtotals, ReportSummary>>>;
  jornadas?: JornadasResumo; sem_rastreio?: SemRastreioResumo };

export default function TrafegoPage() {
  const { role, loading: roleLoading } = useCurrentRole();
  const [period, setPeriod] = useState("30d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dateMode, setDateMode] = useState<"preset" | "mes" | "custom">("preset");
  // Abre na visão do período (12/11/2026): leads e closer de quem entrou, pedidos e receita de
  // toda venda do período, na mesma tela. "Por turma" (coorte) é a opção para ver a conversão
  // de quem entrou no período.
  const [mode, setMode] = useState<TrafficMode>(MODO_PADRAO);
  // Padrão: última origem, como a Tati trabalha. Troca sem nova consulta (o backend manda as duas).
  const [atribuicao, setAtribuicao] = useState<Atribuicao>("ultima");
  const [view, setView] = useState<"campanhas" | "conversoes">("campanhas");
  const router = useRouter();
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [toast, setToast] = useState<{ text: string; tone: "ok" | "warn" | "erro" } | null>(null);
  const [rodadas, setRodadas] = useState<Record<string, RodadaSync>>({});

  // handler do seletor de mês (YYYY-MM) → converte p/ from/to do 1º ao último dia
  const onMonth = (ym: string) => {
    if (!ym) { setDateFrom(""); setDateTo(""); return; }
    const [y, m] = ym.split("-").map(Number);
    const last = new Date(y, m, 0).getDate();
    setDateFrom(`${ym}-01`);
    setDateTo(`${ym}-${String(last).padStart(2, "0")}`);
  };

  // Um erro de API NÃO pode se parecer com "dia sem gasto": foi exatamente essa confusão que
  // deixou o Google Ads dez dias sem sincronizar (versão v21 descontinuada, 404 silencioso)
  // enquanto o botão dizia "sem dados novos". O backend devolve `errors` por plataforma.
  const handleRefresh = async () => {
    setSyncing(true);
    try {
      const r = await fetch("/api/traffic/sync", { method: "POST" });
      const d = await r.json().catch(() => ({}));
      const errors: Record<string, string> = d?.errors ?? {};
      const avisos: Record<string, string> = d?.avisos ?? {};
      const falhou = Object.keys(errors);
      const zerou = Object.keys(avisos);
      const nomes = (ks: string[]) => ks.map((k) => (k === "google" ? "Google Ads" : "Meta Ads")).join(" e ");
      if (falhou.length > 0) {
        setToast({ text: `${nomes(falhou)} não respondeu: ${errors[falhou[0]]}`, tone: "erro" });
      } else if (zerou.length > 0) {
        setToast({ text: `${nomes(zerou)}: ${avisos[zerou[0]]}`, tone: "warn" });
      } else if (typeof d.synced === "number") {
        setToast(d.synced > 0
          ? { text: `${d.synced} linha(s) de investimento sincronizadas`, tone: "ok" }
          : { text: "APIs responderam, mas não há gasto novo no período", tone: "warn" });
      } else {
        setToast({ text: "Não foi possível sincronizar agora", tone: "erro" });
      }
    } catch {
      setToast({ text: "Não foi possível sincronizar agora", tone: "erro" });
    } finally {
      setSyncing(false);
      setRefreshTick((t) => t + 1);
      setTimeout(() => setToast(null), 9000);
    }
  };

  // Última rodada do sync por plataforma (linha embaixo do Atualizar). Fail-soft: sem resposta,
  // a linha só não aparece.
  useEffect(() => {
    if (roleLoading || role !== "admin") return;
    fetch("/api/traffic/sync-status")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setRodadas(d?.plataformas ?? {}))
      .catch(() => setRodadas({}));
  }, [role, roleLoading, refreshTick]);

  useEffect(() => {
    // A aba "Conversões enviadas" busca os próprios dados: o relatório de campanhas (pesado) só
    // é pedido quando a aba Campanhas está na tela — e de novo ao voltar para ela.
    if (roleLoading || role !== "admin" || view !== "campanhas") return;
    setLoading(true);
    const q = (dateFrom || dateTo)
      ? `mode=${mode}${dateFrom ? `&date_from=${dateFrom}` : ""}${dateTo ? `&date_to=${dateTo}` : ""}`
      : `period=${period}&mode=${mode}`;
    fetch(`/api/traffic/report?${q}`)
      .then(r => r.json())
      .then((d: Report) => setReport(d))
      .catch(() => setReport(null))
      .finally(() => setLoading(false));
  }, [period, mode, dateFrom, dateTo, role, roleLoading, refreshTick, view]);

  const parte = report ? escolherAtribuicao(report, atribuicao) : null;
  // "Ver leads" do Sem rastreio abre a maior linha dele (a lista vem com o motivo provável).
  const semRastreio = (parte?.rows ?? []).filter((r) => r.channel === "Sem rastreio")
    .sort((a, b) => b.leads - a.leads)[0];
  const abrirLinha = (r: CampaignRow) => {
    const params: Record<string, string> = { channel: r.channel, campaign: r.campaign, period, mode };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    if (atribuicao !== "ultima") params.atribuicao = atribuicao;
    router.push(`/trafego/campanha?${new URLSearchParams(params).toString()}`);
  };

  if (!roleLoading && role !== "admin") {
    return <div className="p-8 text-[14px] text-[#7b7b78]">Acesso restrito a administradores.</div>;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-4 md:py-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between flex-shrink-0">
        <div>
          <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[24px] md:text-[32px] font-normal text-[#111111]">
            Relatório Campanhas
          </h1>
          <p className="text-[13px] md:text-[14px] text-[#7b7b78] mt-0.5">
            Rastreio de campanhas e leads por origem, cruzado com vendas registradas
          </p>
        </div>
        <div className="flex items-center gap-4 flex-wrap">
          <div className="inline-flex gap-1">
            {([["campanhas", "Campanhas"], ["conversoes", "Conversões enviadas"]] as const).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={`px-3 py-1.5 rounded-[4px] text-[13px] md:text-[14px] border border-[#111111] ${
                  view === v ? "bg-[#111111] text-white" : "bg-transparent text-[#111111]"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {view === "campanhas" && (
            <div className="flex flex-col gap-0.5 max-w-[320px]">
              <label className="flex items-center gap-2 cursor-pointer">
                <span className="text-[13px] text-[#7b7b78]">Por turma</span>
                <Switch aria-label="Por turma" checked={mode === "lead"} onCheckedChange={(c) => setMode(c ? "lead" : MODO_PADRAO)} />
              </label>
              <span data-testid="frase-modo" className="text-[12px] leading-[1.35] text-[#7b7b78]">{FRASE_MODO[mode]}</span>
            </div>
          )}
          {view === "campanhas" && <AtribuicaoSelect value={atribuicao} onChange={setAtribuicao} />}
          <Select value={dateMode} onValueChange={(v) => {
            setDateMode(v as "preset" | "mes" | "custom");
            setDateFrom(""); setDateTo("");
          }}>
            <SelectTrigger className="w-[140px] text-[14px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="preset">Período</SelectItem>
              <SelectItem value="mes">Por mês</SelectItem>
              <SelectItem value="custom">Personalizado</SelectItem>
            </SelectContent>
          </Select>
          {dateMode === "preset" && (
            <Select value={period} onValueChange={setPeriod}>
              <SelectTrigger className="w-[150px] text-[14px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="7d">Últimos 7 dias</SelectItem>
                <SelectItem value="30d">Últimos 30 dias</SelectItem>
                <SelectItem value="90d">Últimos 90 dias</SelectItem>
                <SelectItem value="all">Tudo</SelectItem>
              </SelectContent>
            </Select>
          )}
          {dateMode === "mes" && (
            <input type="month" onChange={(e) => onMonth(e.target.value)}
              className="border border-[#dedbd6] rounded-[6px] px-3 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
          )}
          {dateMode === "custom" && (
            <div className="flex items-center gap-2">
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                className="border border-[#dedbd6] rounded-[6px] px-2 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
              <span className="text-[#7b7b78] text-[13px]">até</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                className="border border-[#dedbd6] rounded-[6px] px-2 py-1.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none" />
            </div>
          )}
          <div className="flex flex-col items-start gap-1">
          <button
            onClick={handleRefresh}
            disabled={syncing}
            className="inline-flex items-center gap-1.5 bg-transparent text-[#111111] border border-[#111111] px-3 py-1.5 rounded-[4px] text-[13px] md:text-[14px] transition-transform hover:scale-105 active:scale-[0.9] disabled:opacity-50"
          >
            <svg className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992V4.356M2.985 19.644v-4.992h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.99v4.99" /></svg>
            {syncing ? "Atualizando…" : "Atualizar"}
          </button>
          {Object.keys(rodadas).length > 0 && (
            <div data-testid="status-sync" className="flex flex-col text-[12px] leading-[1.35]">
              {Object.entries(rodadas).map(([p, r]) => (
                <span key={p} className={r.status === "falha" ? "text-[#c41c1c]" : r.status === "aviso" ? "text-[#a35c00]" : "text-[#7b7b78]"}>
                  {linhaSync(p, r)}
                </span>
              ))}
            </div>
          )}
          </div>
        </div>
      </div>

      {/* Content — rola como um todo: o resumo expandido não pode espremer a tabela */}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-4 px-4 md:px-8 py-4 md:py-8 bg-[#faf9f6]">
        {view === "conversoes" ? (
          <ConversoesEnviadas period={period} dateFrom={dateFrom} dateTo={dateTo} refreshTick={refreshTick} />
        ) : loading ? (
          <>
            <Skeleton className="h-[220px] w-full flex-shrink-0 rounded-[8px]" />
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 md:p-5 space-y-2">
              {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          </>
        ) : (
          <>
            {parte?.summary && (
              <div className="flex-shrink-0">
                <ReportSummaryPanel summary={parte.summary} mode={mode} />
              </div>
            )}
            <div className="flex-shrink-0 grid gap-4 md:grid-cols-2">
              <JornadasMulticanal jornadas={report?.jornadas} />
              <SemRastreioDetalhe resumo={parte?.sem_rastreio ?? report?.sem_rastreio} onAbrir={semRastreio ? () => abrirLinha(semRastreio) : undefined} />
            </div>
            <div className="bg-white border border-[#dedbd6] rounded-[8px] flex-1 min-h-[420px] flex flex-col overflow-hidden">
            <CampaignReportTable
              rows={parte?.rows ?? []}
              total={parte?.total}
              subtotals={parte?.channel_subtotals ?? {}}
              periodo={mode === "periodo"}
              onRowClick={abrirLinha}
            />
            </div>
          </>
        )}
      </div>
      {toast && (
        // Chip escuro do sistema + um ponto de status: o estado vem da cor do ponto, não de um
        // bloco colorido — mantém o tom sóbrio da página e ainda separa erro de "sem gasto".
        <div className="fixed bottom-6 right-6 z-50 flex items-start gap-2.5 max-w-[420px] bg-[#111111] text-white text-[13px] px-4 py-3 rounded-[6px] shadow-lg">
          <span
            aria-hidden
            className={`mt-[5px] w-[7px] h-[7px] rounded-full flex-shrink-0 ${
              toast.tone === "erro" ? "bg-[#ff5a4d]" : toast.tone === "warn" ? "bg-[#ffb020]" : "bg-[#0bdf50]"
            }`}
          />
          <span className="leading-[1.45]">{toast.text}</span>
        </div>
      )}
    </div>
  );
}

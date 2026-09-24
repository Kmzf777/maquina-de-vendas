"use client";

// Bloco "Relatório geral" do /trafego: lê `report.summary` (mesma requisição da tabela, nada
// de fetch novo) e resume o período em 4 faixas — funil, custo por etapa, canais, tempo/qualidade.
import { useEffect, useState, type ReactNode } from "react";
import { CHANNEL_STYLES } from "@/components/trafego/campaign-report-table";
import {
  STAGE_LABEL, collapsedLine, fmtBRLOrDash, fmtDays, fmtInt, fmtPctOrDash, fmtRoasOrDash,
  type ReportSummary, type SummaryStage,
} from "@/lib/traffic-summary";

const STORAGE_KEY = "trafego:summary-collapsed";
const LABEL = "text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78]";

function Band({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border border-[#dedbd6] rounded-[6px] p-4 flex flex-col gap-3 min-w-0">
      <h3 className={LABEL}>{title}</h3>
      {children}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <div className="text-[12px] text-[#7b7b78] leading-tight">{label}</div>
      <div className="text-[18px] md:text-[20px] text-[#111111] tabular-nums leading-none" style={{ letterSpacing: "-0.4px" }}>
        {value}
      </div>
      {hint && <div className="text-[11px] text-[#7b7b78] tabular-nums">{hint}</div>}
    </div>
  );
}

// ---- 1. Funil ------------------------------------------------------------------------------
function FunnelBand({ summary, mode }: { summary: ReportSummary; mode: "lead" | "sale" }) {
  const f = summary.funnel;
  const showRates = mode === "lead";
  const steps: { label: string; n: number; stage?: SummaryStage; rate?: number | null }[] = [
    { label: "Leads", n: f.leads },
    { label: "Conversas", n: f.conversas, stage: "conversa", rate: f.taxa_conversa },
    { label: "Closer", n: f.closer, stage: "closer", rate: f.taxa_closer },
    { label: "Clientes", n: f.clientes, stage: "cliente", rate: f.taxa_cliente },
  ];
  const width = (n: number) => (f.leads > 0 ? `${Math.max(2, (n / f.leads) * 100)}%` : "2%");

  return (
    <Band title="Funil">
      <ol className="flex flex-col">
        {steps.map((s) => {
          const isGargalo = showRates && s.stage != null && s.stage === f.gargalo;
          return (
            <li key={s.label} className="flex flex-col">
              {showRates && s.stage && (
                <div
                  className={`pl-[88px] py-1 text-[11px] tabular-nums flex items-center gap-1.5 ${isGargalo ? "text-[#ff5600]" : "text-[#7b7b78]"}`}
                  title={STAGE_LABEL[s.stage]}
                >
                  <span aria-hidden>↓</span>
                  <span>{fmtPctOrDash(s.rate)}</span>
                  {isGargalo && <span className="font-medium uppercase tracking-[0.6px]">· gargalo</span>}
                </div>
              )}
              <div className={`flex items-center gap-3 ${showRates ? "" : "py-1"}`} title={`${s.label}: ${fmtInt(s.n)}`}>
                <span className="w-[76px] flex-shrink-0 text-[12px] text-[#7b7b78]">{s.label}</span>
                <div className="flex-1 min-w-0 h-[10px]">
                  <div className="h-full rounded-r-[4px] bg-[#111111]" style={{ width: width(s.n) }} />
                </div>
                <span className="w-[56px] flex-shrink-0 text-right text-[13px] text-[#111111] tabular-nums">{fmtInt(s.n)}</span>
              </div>
            </li>
          );
        })}
      </ol>
      {showRates ? (
        <p className="text-[12px] text-[#7b7b78] border-t border-[#dedbd6] pt-2">
          Lead → cliente: <span className="text-[#111111] tabular-nums">{fmtPctOrDash(f.taxa_total)}</span>
        </p>
      ) : (
        <p className="text-[12px] text-[#7b7b78] border-t border-[#dedbd6] pt-2 leading-[1.45]">
          No modo Por venda a base já é quem comprou — leia o funil no modo Por lead.
        </p>
      )}
    </Band>
  );
}

// ---- 2. Custo por etapa --------------------------------------------------------------------
function CostBand({ summary }: { summary: ReportSummary }) {
  const c = summary.cost;
  return (
    <Band title="Custo por etapa (Google + Meta)">
      {c.investimento === 0 ? (
        <p className="text-[13px] text-[#7b7b78]">Sem investimento sincronizado no período.</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-4">
          <Stat label="Investimento" value={fmtBRLOrDash(c.investimento)} />
          <Stat label="CPL" value={fmtBRLOrDash(c.cpl)} hint={`${fmtInt(c.leads)} leads pagos`} />
          <Stat label="Custo por conversa" value={fmtBRLOrDash(c.custo_conversa)} />
          <Stat label="Custo por closer" value={fmtBRLOrDash(c.custo_closer)} />
          <Stat label="CAC" value={fmtBRLOrDash(c.cac)} hint={`${fmtInt(c.clientes)} clientes pagos`} />
          <Stat label="ROAS" value={fmtRoasOrDash(c.roas)} />
        </div>
      )}
    </Band>
  );
}

// ---- 3. Canais -----------------------------------------------------------------------------
function ChannelsBand({ summary }: { summary: ReportSummary }) {
  const chans = summary.channels;
  return (
    <Band title="Canais">
      {chans.length === 0 ? (
        <p className="text-[13px] text-[#7b7b78]">Nenhum canal no período.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-[#dedbd6]">
          {chans.map((ch) => (
            <li key={ch.channel} className="py-2 first:pt-0 last:pb-0 flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-3">
                <span className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${CHANNEL_STYLES[ch.channel] ?? CHANNEL_STYLES["Sem rastreio"]}`}>
                  {ch.channel}
                </span>
                <span className="text-[12px] text-[#7b7b78] tabular-nums">
                  Lead → cliente <span className="text-[#111111]">{fmtPctOrDash(ch.taxa_total)}</span>
                </span>
              </div>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <span className="text-[13px] text-[#111111] tabular-nums">
                  {fmtInt(ch.leads)} → {fmtInt(ch.conversas)} → {fmtInt(ch.closer)} → {fmtInt(ch.clientes)}
                </span>
                <span className="text-[12px] text-[#7b7b78] tabular-nums">
                  {fmtBRLOrDash(ch.receita)}
                  {ch.investimento > 0 && <> · ROAS {fmtRoasOrDash(ch.roas)}</>}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
      {chans.length > 0 && (
        <p className="text-[11px] text-[#7b7b78]">leads → conversas → closer → clientes</p>
      )}
    </Band>
  );
}

// ---- 4. Tempo e qualidade ------------------------------------------------------------------
function TimingBand({ summary }: { summary: ReportSummary }) {
  const t = summary.timing_quality;
  const ppc = t.pedidos_por_cliente == null
    ? "—"
    : t.pedidos_por_cliente.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <Band title="Tempo e qualidade">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-4">
        <Stat
          label="Até a 1ª compra (mediana)"
          value={fmtDays(t.dias_ate_compra_mediana)}
          hint={`${fmtInt(t.amostra_dias)} ${t.amostra_dias === 1 ? "cliente" : "clientes"}`}
        />
        <Stat label="Pedidos por cliente" value={ppc} />
        <Stat label="Recompra" value={fmtPctOrDash(t.recompra_pct)} />
        <Stat label="Sem rastreio" value={fmtPctOrDash(t.sem_rastreio_pct)} />
        <Stat label="Pagos sem campanha" value={fmtPctOrDash(t.nao_atribuido_pct)} />
      </div>
    </Band>
  );
}

export function ReportSummaryPanel({ summary, mode }: { summary: ReportSummary; mode: "lead" | "sale" }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (localStorage.getItem(STORAGE_KEY) === "1") setCollapsed(true);
    } catch { /* storage bloqueado: fica expandido */ }
  }, []);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem(STORAGE_KEY, next ? "1" : "0"); } catch { /* ignora */ }
  };

  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px]">
      <div className={`flex items-center justify-between gap-3 px-4 md:px-5 py-3 ${collapsed ? "" : "border-b border-[#dedbd6]"}`}>
        {collapsed ? (
          <p className="text-[13px] text-[#111111] tabular-nums min-w-0 truncate" title={collapsedLine(summary)}>
            {collapsedLine(summary)}
          </p>
        ) : (
          <h2 className={LABEL}>Relatório geral</h2>
        )}
        <button
          type="button"
          onClick={toggle}
          aria-expanded={!collapsed}
          className="flex-shrink-0 inline-flex items-center gap-1 text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors"
        >
          {collapsed ? "Expandir" : "Recolher"}
          <svg className={`w-3.5 h-3.5 transition-transform ${collapsed ? "" : "rotate-180"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} aria-hidden>
            <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
          </svg>
        </button>
      </div>
      {!collapsed && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 p-3 md:p-4">
          <FunnelBand summary={summary} mode={mode} />
          <CostBand summary={summary} />
          <ChannelsBand summary={summary} />
          <TimingBand summary={summary} />
        </div>
      )}
    </div>
  );
}

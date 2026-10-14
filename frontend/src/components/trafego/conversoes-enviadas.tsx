"use client";

// Aba "Conversões enviadas" do /trafego: o que o CRM mandou de volta para Meta e Google.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PLATFORMS, PLATFORM_LABEL, STAGES, STAGE_LABEL, STATUS_LABEL, traduzErro } from "@/lib/conversoes";

type Row = {
  id: string; lead_id: string | null; platform: string; stage: string; status: string;
  event_at: string; value: number | null; currency: string | null; segment: string | null;
  campaign_name: string | null; click_id_type: string | null; attempts: number;
  last_error: string | null; sent_at: string | null; lead: { name: string | null } | null;
};
type Count = { stage: string; platform: string; status: string; n: number };
type Data = { rows: Row[]; counts: Count[]; truncated: boolean };

const TODAS = "todas";
const STATUS_COLOR: Record<string, string> = {
  enviado: "#0bdf50", erro: "#ff5a4d", fora_da_janela: "#7b7b78", ignorado: "#7b7b78", pendente: "#ffb020",
};
const fmtData = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
});
const dataCurta = (iso: string) => fmtData.format(new Date(iso)).replace(",", "");

export function ConversoesEnviadas({ period, dateFrom, dateTo, refreshTick }: {
  period: string; dateFrom: string; dateTo: string; refreshTick: number;
}) {
  const [platform, setPlatform] = useState(TODAS);
  const [stage, setStage] = useState(TODAS);
  const [status, setStatus] = useState(TODAS);
  const [data, setData] = useState<Data | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    const p = new URLSearchParams();
    if (dateFrom || dateTo) {
      if (dateFrom) p.set("date_from", dateFrom);
      if (dateTo) p.set("date_to", dateTo);
    } else {
      p.set("period", period);
    }
    if (platform !== TODAS) p.set("platform", platform);
    if (stage !== TODAS) p.set("stage", stage);
    if (status !== TODAS) p.set("status", status);
    // Filtro trocado antes da resposta chegar: aborta o request velho e ignora o que ele
    // devolver — senão a resposta lenta de um filtro anterior sobrescreveria a atual.
    const ctrl = new AbortController();
    setLoading(true);
    setErro(null);
    fetch(`/api/traffic/conversoes?${p.toString()}`, { signal: ctrl.signal })
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!r.ok) {
          const msg = typeof body?.error === "string" ? body.error
            : typeof body?.detail === "string" ? body.detail : `HTTP ${r.status}`;
          throw new Error(msg);
        }
        return body as Data;
      })
      .then((d) => { if (!ctrl.signal.aborted) setData(d); })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setData(null);
        setErro(e instanceof Error ? e.message : "erro desconhecido");
      })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [period, dateFrom, dateTo, platform, stage, status, refreshTick]);

  // etapa|plataforma -> contagem por status
  const grade = useMemo(() => {
    const m: Record<string, Record<string, number>> = {};
    for (const c of data?.counts ?? []) {
      const k = `${c.stage}|${c.platform}`;
      (m[k] ??= {})[c.status] = (m[k][c.status] ?? 0) + c.n;
    }
    return m;
  }, [data]);

  const filtro = (valor: string, set: (v: string) => void, opcoes: Record<string, string>, rotulo: string) => (
    <Select value={valor} onValueChange={set}>
      <SelectTrigger className="w-[170px] text-[14px] bg-white" aria-label={rotulo}><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value={TODAS}>{rotulo}: todas</SelectItem>
        {Object.entries(opcoes).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
      </SelectContent>
    </Select>
  );

  const rows = data?.rows ?? [];
  return (
    <div className="flex flex-col gap-4">
      {loading ? (
        <Skeleton className="h-[200px] w-full rounded-[8px]" />
      ) : !erro && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {STAGES.map((s) => (
            <div key={s} data-testid={`card-${s}`} className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
              <div className="text-[13px] text-[#7b7b78] mb-2">{STAGE_LABEL[s]}</div>
              {PLATFORMS.map((pl) => {
                // A Meta não recebe a etapa lead (o sinal de lead dela é o repasse): "—", não "0".
                const naoRecebe = s === "lead" && pl === "meta";
                const c = grade[`${s}|${pl}`] ?? {};
                const detalhe = (["erro", "fora_da_janela", "pendente"] as const)
                  .filter((st) => (c[st] ?? 0) > 0)
                  .map((st) => `${STATUS_LABEL[st].toLowerCase()} ${c[st]}`)
                  .join(" · ");
                return (
                  <div key={pl} data-testid={`card-${s}-${pl}`} className="mb-2 last:mb-0">
                    <div className="flex items-baseline justify-between">
                      <span className="text-[12px] text-[#7b7b78]">{PLATFORM_LABEL[pl]}</span>
                      <span className="text-[22px] text-[#111111]" title={naoRecebe ? "A Meta não recebe a etapa lead" : undefined}>
                        {naoRecebe ? "—" : (c.enviado ?? 0)}
                      </span>
                    </div>
                    {!naoRecebe && detalhe && <div className="text-[11px] text-[#7b7b78] text-right">{detalhe}</div>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {filtro(stage, setStage, STAGE_LABEL, "Etapa")}
        {filtro(platform, setPlatform, PLATFORM_LABEL, "Plataforma")}
        {filtro(status, setStatus, STATUS_LABEL, "Status")}
      </div>

      {!loading && data?.truncated && (
        <div className="text-[13px] text-[#7b7b78]">Mostrando os 1.000 eventos mais recentes — estreite o período.</div>
      )}

      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-x-auto">
        {loading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : erro ? (
          <div role="alert" className="p-8 text-center text-[14px] text-[#ff5a4d]">
            Não foi possível carregar as conversões ({erro}). Tente de novo em instantes.
          </div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-[14px] text-[#7b7b78]">Nenhuma conversão no período.</div>
        ) : (
          <table className="w-full text-[14px] text-[#111111]">
            <thead>
              <tr className="text-left text-[12px] text-[#7b7b78] border-b border-[#dedbd6]">
                {["Data", "Lead", "Etapa", "Plataforma", "Campanha", "Valor", "Status"].map((h) => (
                  <th key={h} className="px-4 py-2 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-[#dedbd6] last:border-0 align-top">
                  <td className="px-4 py-2.5 whitespace-nowrap">{dataCurta(r.event_at)}</td>
                  <td className="px-4 py-2.5">
                    {r.lead_id ? (
                      <Link href={`/conversas?lead_id=${r.lead_id}`} className="underline-offset-2 hover:underline">
                        {r.lead?.name || "Sem nome"}
                      </Link>
                    ) : (r.lead?.name || "—")}
                  </td>
                  <td className="px-4 py-2.5">{STAGE_LABEL[r.stage] ?? r.stage}</td>
                  <td className="px-4 py-2.5">{PLATFORM_LABEL[r.platform] ?? r.platform}</td>
                  <td className="px-4 py-2.5">{r.campaign_name || "—"}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    {r.value == null ? "—" : `R$ ${Number(r.value).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2 whitespace-nowrap">
                      <span aria-hidden className="w-[7px] h-[7px] rounded-full" style={{ background: STATUS_COLOR[r.status] ?? "#7b7b78" }} />
                      {STATUS_LABEL[r.status] ?? r.status}
                    </div>
                    {r.last_error && (
                      <div className="text-[12px] text-[#7b7b78] mt-0.5 max-w-[320px]">{traduzErro(r.last_error, r.platform)}</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

"use client";

// Painel lateral do lead dentro de /trafego/campanha.
//
// A tabela da campanha responde "quem chegou". Este painel responde a pergunta
// seguinte, que é a que importa para quem paga o anúncio: "e o que aconteceu
// com essa pessoa?". Por isso a peça central não é a ficha cadastral — é a
// TRILHA: onde o lead parou. O laranja Fin aparece uma única vez na tela, no
// ponto onde ele travou, porque esse é o dado que a pessoa veio buscar.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { getTemperature, TEMPERATURE_CONFIG } from "@/lib/temperature";
import {
  buildJourney,
  buildMovements,
  computeVitals,
  fmtBRL,
  fmtDate,
  fmtDateTime,
  humanDuration,
  stageLabel,
  type Journey,
  type LeadOverview,
  type Movement,
  type MovementKind,
} from "@/lib/lead-overview";

type Payload = LeadOverview & { partial?: string[] };

export interface CampaignLeadPanelTarget {
  lead_id: string;
  name: string | null;
  phone: string | null;
  traffic_type: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
}

const DASH = "—";

/** Fin Orange é reservado ao ponto de travamento — nunca decorativo. */
const FIN = "#ff5600";

const KIND_COLOR: Record<MovementKind, string> = {
  entrada: "#111111",
  evento: "#5b8aad",
  nota: "#d4a04a",
  venda: "#1f9d57",
  oportunidade: "#9b7abf",
  disparo: "#fe4c02",
  cadencia: "#5aad65",
  followup: "#7b7b78",
};

const MOVEMENTS_PAGE = 25;

// ─── Peças ─────────────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2.5">{children}</div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">{children}</div>;
}

function Chip({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "paid" | "organic" | "neutral" }) {
  const style =
    tone === "paid"
      ? "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20"
      : tone === "organic"
        ? "bg-[#0bdf50]/10 text-[#0f9d43] border-[#0bdf50]/20"
        : "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]";
  return (
    <span
      className={`inline-flex items-center text-[11px] font-medium px-2 py-0.5 rounded-[4px] border whitespace-nowrap ${style}`}
    >
      {children}
    </span>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string | null }) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] leading-none">{label}</div>
      <div
        className="text-[17px] text-[#111111] tabular-nums mt-1.5 leading-none"
        style={{ letterSpacing: "-0.4px" }}
      >
        {value}
      </div>
      {hint && <div className="text-[11px] text-[#7b7b78] mt-1 leading-none">{hint}</div>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-[5px]">
      <span className="text-[12px] text-[#7b7b78]">{label}</span>
      <span className="text-[13px] text-[#111111] tabular-nums text-right">{value}</span>
    </div>
  );
}

/**
 * A trilha. Nó cheio = etapa cumprida; nó vazado = não chegou lá. O quadrado
 * laranja marca onde parou — quadrado, e não círculo, para o ponto de
 * travamento ser distinguível mesmo sem enxergar cor.
 */
function JourneyRail({ journey, nowMs }: { journey: Journey; nowMs: number }) {
  const { steps, stalledAt } = journey;
  const parada = stalledAt === null ? null : steps[stalledAt];
  const fechou = steps[steps.length - 1].reached;
  const paradaHa =
    parada?.at != null ? humanDuration(nowMs - Date.parse(parada.at)) : null;

  return (
    <Card>
      <SectionLabel>Trilha</SectionLabel>

      <div className="flex items-start">
        {steps.map((s, i) => {
          const proximo = steps[i + 1];
          const isStalled = stalledAt === i;
          return (
            <div key={s.key} className="flex-1 min-w-0">
              <div className="flex items-center h-[11px]">
                {isStalled ? (
                  <span
                    className="w-[11px] h-[11px] rounded-[2px] flex-shrink-0"
                    style={{ backgroundColor: FIN }}
                  />
                ) : (
                  <span
                    className={`w-[9px] h-[9px] rounded-full flex-shrink-0 ${
                      s.reached ? "bg-[#111111]" : "border border-[#dedbd6] bg-white"
                    }`}
                  />
                )}
                {proximo && (
                  <span
                    className={`flex-1 ml-1 mr-1 ${
                      proximo.reached
                        ? "h-px bg-[#111111]"
                        : "border-t border-dashed border-[#dedbd6]"
                    }`}
                  />
                )}
              </div>
              {/* 10px com tracking curto: em 460px de painel cada etapa tem
                  ~97px, e "OPORTUNIDADE" a 11px/0.6px transborda por cima do
                  rótulo seguinte. `pr` só entre colunas para a última usar a
                  largura toda. */}
              <div className={`mt-2 ${proximo ? "pr-2" : ""}`}>
                <div
                  className={`text-[10px] uppercase tracking-[0.3px] leading-tight ${
                    s.reached ? "text-[#111111]" : "text-[#b5b1aa]"
                  }`}
                >
                  {s.label}
                </div>
                <div className="text-[11px] text-[#7b7b78] tabular-nums mt-0.5">
                  {s.reached ? fmtDate(s.at) : DASH}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 pt-3 border-t border-[#dedbd6] text-[12px]">
        {fechou ? (
          <span className="text-[#1f9d57]">Ciclo fechado — o lead comprou.</span>
        ) : (
          <span style={{ color: FIN }}>
            Parou em &ldquo;{parada?.label}&rdquo;
            {paradaHa && paradaHa !== DASH ? ` · há ${paradaHa}` : ""}
          </span>
        )}
      </div>
    </Card>
  );
}

function MessageBar({ inbound, outbound }: { inbound: number; outbound: number }) {
  const total = inbound + outbound;
  if (total === 0) {
    return <div className="text-[12px] text-[#7b7b78]">Nenhuma mensagem trocada.</div>;
  }
  const pct = (inbound / total) * 100;
  return (
    <>
      <div className="flex h-1.5 rounded-[2px] overflow-hidden bg-[#f0ede8]">
        <span style={{ width: `${pct}%`, backgroundColor: "#111111" }} />
        <span style={{ width: `${100 - pct}%`, backgroundColor: "#dedbd6" }} />
      </div>
      <div className="flex items-center justify-between mt-2 text-[12px]">
        <span className="text-[#111111] tabular-nums">{inbound} do lead</span>
        <span className="text-[#7b7b78] tabular-nums">{outbound} nossas</span>
      </div>
    </>
  );
}

function MovementsRail({ movements }: { movements: Movement[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? movements : movements.slice(0, MOVEMENTS_PAGE);
  const restantes = movements.length - visible.length;

  return (
    <Card>
      <SectionLabel>Movimentações</SectionLabel>
      <ol className="border-l border-[#dedbd6] pl-4 space-y-3.5">
        {visible.map((m) => (
          <li key={m.id} className="relative">
            <span
              className="absolute -left-[18.5px] top-[5px] w-[7px] h-[7px] rounded-[1px]"
              style={{ backgroundColor: KIND_COLOR[m.kind] }}
            />
            <div className="text-[11px] text-[#7b7b78] tabular-nums leading-none">
              {fmtDateTime(m.at)}
            </div>
            <div className="text-[13px] text-[#111111] mt-1 leading-snug">{m.title}</div>
            {m.detail && (
              <div className="text-[12px] text-[#7b7b78] mt-0.5 leading-snug whitespace-pre-wrap break-words">
                {m.detail}
              </div>
            )}
          </li>
        ))}
      </ol>
      {restantes > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-3 text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors"
        >
          Ver mais {restantes} movimentaç{restantes === 1 ? "ão" : "ões"}
        </button>
      )}
    </Card>
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-28 w-full" />
      <div className="grid grid-cols-2 gap-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

// ─── Painel ────────────────────────────────────────────────────────────────────

export function CampaignLeadPanel({
  target,
  onClose,
}: {
  target: CampaignLeadPanelTarget | null;
  onClose: () => void;
}) {
  const router = useRouter();
  const leadId = target?.lead_id ?? null;
  // Payload, lead e "agora" viajam juntos num único estado. Duas razões:
  //  · o instante é carimbado quando a resposta chega, não a cada render — ler o
  //    relógio durante o render deixaria "há 6 d" mudando sozinho;
  //  · o `leadId` embutido é o que descarta a resposta do lead ANTERIOR sem
  //    precisar zerar estado dentro do efeito. Trocar de linha na tabela nunca
  //    mostra o número de um lead com o nome de outro.
  const [snapshot, setSnapshot] = useState<{ leadId: string; payload: Payload; at: number } | null>(
    null,
  );
  const [failure, setFailure] = useState<{ leadId: string; message: string } | null>(null);

  useEffect(() => {
    if (!leadId) return;
    const ctrl = new AbortController();
    fetch(`/api/leads/${leadId}/overview`, { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 403 ? "forbidden" : "failed");
        return (await r.json()) as Payload;
      })
      .then((payload) => setSnapshot({ leadId, payload, at: Date.now() }))
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setFailure({
          leadId,
          message:
            e instanceof Error && e.message === "forbidden"
              ? "Sem permissão para ver este lead."
              : "Não foi possível carregar os dados deste lead.",
        });
      });
    return () => ctrl.abort();
  }, [leadId]);

  const data = snapshot && snapshot.leadId === leadId ? snapshot.payload : null;
  // Um único "agora" para o painel inteiro — dois cards não podem discordar.
  const nowMs = data ? snapshot!.at : 0;
  const error = failure && failure.leadId === leadId ? failure.message : null;
  const loading = leadId !== null && data === null && error === null;

  const vitals = useMemo(() => (data ? computeVitals(data, nowMs) : null), [data, nowMs]);
  const journey = useMemo(() => (data ? buildJourney(data) : null), [data]);
  const movements = useMemo(() => (data ? buildMovements(data) : []), [data]);

  const go = useCallback(
    (href: string) => {
      onClose();
      router.push(href);
    },
    [onClose, router],
  );

  const nome = data?.lead.name ?? target?.name ?? target?.phone ?? DASH;
  const telefone = data?.lead.phone ?? target?.phone ?? null;
  const trafficType = data?.lead.traffic_type ?? target?.traffic_type ?? null;
  const utms = [
    data?.lead.utm_source ?? target?.utm_source,
    data?.lead.utm_medium ?? target?.utm_medium,
    data?.lead.utm_campaign ?? target?.utm_campaign,
  ].filter(Boolean) as string[];

  const temp = data ? TEMPERATURE_CONFIG[getTemperature(data.lead.last_msg_at)] : null;

  return (
    <Sheet
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        className="flex flex-col gap-0 p-0 border-l border-[#dedbd6] bg-[#faf9f6]"
        style={{ width: 460, maxWidth: "94vw" }}
      >
        {/* ── Cabeçalho ── */}
        <SheetHeader className="flex-shrink-0 gap-0 px-5 pt-5 pb-4 border-b border-[#dedbd6] bg-white">
          <div className="flex flex-wrap items-center gap-1.5 pr-8">
            <Chip tone={trafficType === "paid" ? "paid" : trafficType === "organic" ? "organic" : "neutral"}>
              {trafficType === "paid" ? "Pago" : trafficType === "organic" ? "Orgânico" : "Sem rastreio"}
            </Chip>
            {temp && (
              <span
                className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-[4px] border"
                style={{ color: temp.color, backgroundColor: temp.bg, borderColor: temp.borderColor }}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: temp.dotColor }} />
                {temp.label}
              </span>
            )}
          </div>

          <SheetTitle
            className="text-[22px] font-normal text-[#111111] mt-2.5 pr-8 break-words"
            style={{ letterSpacing: "-0.48px", lineHeight: "1.05" }}
          >
            {nome}
          </SheetTitle>
          <SheetDescription className="text-[13px] text-[#7b7b78] mt-1">
            {/* Lead sem nome já usa o telefone como título — repeti-lo aqui só
                gastaria linha. */}
            {[telefone === nome ? null : telefone, data?.lead.stage ? stageLabel(data.lead.stage) : null]
              .filter(Boolean)
              .join(" · ") || "Detalhes do lead"}
          </SheetDescription>

          {utms.length > 0 && (
            <div className="text-[11px] text-[#7b7b78] mt-2 font-mono break-all">{utms.join(" · ")}</div>
          )}

          <div className="flex items-center gap-2 mt-3.5">
            <button
              type="button"
              onClick={() => leadId && go(`/conversas?lead_id=${leadId}`)}
              className="flex-1 inline-flex items-center justify-center gap-2 bg-[#111111] text-white text-[14px] py-2.5 rounded-[4px] hover:bg-[#000000] active:scale-[0.98] transition-all"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
              Abrir conversa
            </button>
            <button
              type="button"
              onClick={() => leadId && go(`/leads?lead_id=${leadId}`)}
              className="text-[13px] text-[#111111] border border-[#dedbd6] hover:border-[#111111] px-3 py-2.5 rounded-[4px] transition-colors whitespace-nowrap"
            >
              Ficha
            </button>
          </div>
        </SheetHeader>

        {/* ── Corpo ── */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {loading && <PanelSkeleton />}

          {error && (
            <div className="border border-[#dedbd6] bg-white rounded-[8px] p-4 text-[13px] text-[#c41c1c]">
              {error}
            </div>
          )}

          {data && vitals && journey && (
            <>
              {data.partial && data.partial.length > 0 && (
                // Seção que caiu é dita em voz alta. Um array vazio silencioso
                // leria como "não existe" — e alguém tomaria decisão em cima disso.
                <div className="border border-[#e8d44d] bg-[#fefce8] rounded-[8px] px-3 py-2 text-[12px] text-[#7a5a00]">
                  Não foi possível carregar: {data.partial.join(", ")}. Os números abaixo estão incompletos.
                </div>
              )}

              <JourneyRail journey={journey} nowMs={nowMs} />

              <div className="grid grid-cols-2 gap-2">
                <Stat
                  label="Receita"
                  value={vitals.receita > 0 ? fmtBRL(vitals.receita) : DASH}
                  hint={vitals.pedidos > 0 ? `${vitals.pedidos} pedido${vitals.pedidos === 1 ? "" : "s"}` : null}
                />
                <Stat
                  label="Ticket médio"
                  value={vitals.pedidos > 0 ? fmtBRL(vitals.ticketMedio) : DASH}
                />
                <Stat
                  label="Pipeline aberto"
                  value={vitals.dealsAbertos > 0 ? fmtBRL(vitals.pipelineAberto) : DASH}
                  hint={
                    vitals.dealsTotal > 0
                      ? `${vitals.dealsAbertos} de ${vitals.dealsTotal} oportunidade${vitals.dealsTotal === 1 ? "" : "s"}`
                      : null
                  }
                />
                <Stat label="No CRM" value={`${vitals.diasNoCrm} d`} hint={fmtDate(data.lead.created_at)} />
              </div>

              <Card>
                <SectionLabel>Tempos</SectionLabel>
                <div className="divide-y divide-[#f0ede8]">
                  <Row label="Até o lead falar" value={humanDuration(vitals.tempoAteContatoMs)} />
                  <Row label="Até nossa 1ª resposta" value={humanDuration(vitals.tempoAteRespostaMs)} />
                  <Row label="Sem trocar mensagem há" value={humanDuration(vitals.inatividadeMs)} />
                  <Row
                    label="Na etapa atual há"
                    value={vitals.diasNaEtapa === null ? DASH : `${vitals.diasNaEtapa} d`}
                  />
                </div>
              </Card>

              <Card>
                <SectionLabel>Conversa · {vitals.mensagens.total} mensagens</SectionLabel>
                <MessageBar inbound={vitals.mensagens.inbound} outbound={vitals.mensagens.outbound} />
              </Card>

              {(vitals.cadencias > 0 || vitals.disparos > 0 || vitals.notas > 0) && (
                <div className="grid grid-cols-3 gap-2">
                  <Stat label="Cadências" value={String(vitals.cadencias)} />
                  <Stat label="Disparos" value={String(vitals.disparos)} />
                  <Stat label="Notas" value={String(vitals.notas)} />
                </div>
              )}

              {data.deals.length > 0 && (
                <Card>
                  <SectionLabel>Oportunidades</SectionLabel>
                  <div className="divide-y divide-[#f0ede8]">
                    {data.deals.map((d) => (
                      <div key={d.id} className="flex items-start justify-between gap-3 py-2">
                        <div className="min-w-0">
                          <div className="text-[13px] text-[#111111] truncate">{d.title}</div>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <span
                              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                              style={{ backgroundColor: d.dot_color ?? "#dedbd6" }}
                            />
                            <span className="text-[12px] text-[#7b7b78] truncate">
                              {d.stage_label ?? stageLabel(d.stage_key)}
                              {d.pipeline_name ? ` · ${d.pipeline_name}` : ""}
                            </span>
                          </div>
                          {d.lost_reason && (
                            <div className="text-[12px] text-[#c41c1c] mt-0.5">{d.lost_reason}</div>
                          )}
                        </div>
                        <span className="text-[13px] text-[#111111] tabular-nums whitespace-nowrap">
                          {fmtBRL(d.value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {data.sales.length > 0 && (
                <Card>
                  <SectionLabel>Vendas</SectionLabel>
                  <div className="divide-y divide-[#f0ede8]">
                    {data.sales.map((s) => (
                      <div key={s.id} className="flex items-start justify-between gap-3 py-2">
                        <div className="min-w-0">
                          <div className="text-[13px] text-[#111111] truncate">
                            {s.product ?? "Venda"}
                          </div>
                          <div className="text-[12px] text-[#7b7b78] tabular-nums">
                            {fmtDate(s.sold_at)}
                            {s.sold_by ? ` · ${s.sold_by}` : ""}
                          </div>
                        </div>
                        <span className="text-[13px] text-[#1f9d57] tabular-nums whitespace-nowrap">
                          {fmtBRL(s.value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {movements.length > 0 && <MovementsRail movements={movements} />}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

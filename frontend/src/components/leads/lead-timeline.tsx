"use client";

import { useEffect, useState } from "react";
import {
  ArrowRightLeft,
  Ban,
  Circle,
  GitMerge,
  LogIn,
  Megaphone,
  MessageCircle,
  ShoppingBag,
  Target,
  type LucideIcon,
} from "lucide-react";

// ── Tipos do payload de GET /api/leads/[id]/timeline ───────────────────────────────────

/** Linha de `lead_events` como a rota entrega. */
export interface TimelineEvent {
  kind: "evento";
  id: string;
  /** entrada | etapa | venda | venda_cancelada | disparo | mesclagem | atribuicao_manual | (legado) stage_change */
  event_type: string;
  /** occurred_at (quando aconteceu; no backfill ≠ inserção), ISO. */
  at: string;
  source: string | null;
  old_value: string | null;
  new_value: string | null;
  metadata: Record<string, unknown>;
}

/** Marcador diário: o cliente mandou mensagem neste dia (fuso America/Sao_Paulo). */
export interface TimelineConversou {
  kind: "conversou";
  /** `conversou:YYYY-MM-DD` */
  id: string;
  /** YYYY-MM-DD em São Paulo. */
  dia: string;
  /** Última mensagem inbound do dia (ISO) — define a posição na lista. */
  at: string;
  mensagens: number;
}

export type TimelineItem = TimelineEvent | TimelineConversou;

export interface TimelineResponse {
  /** Do mais novo para o mais antigo. */
  items: TimelineItem[];
  /** Seções que falharam: "eventos" | "conversas". */
  partial: string[];
}

export interface LeadTimelineProps {
  leadId: string;
}

// ── Apresentação ───────────────────────────────────────────────────────────────────────

type Linha = {
  icon: LucideIcon;
  cor: string;
  titulo: string;
  detalhe: string | null;
  selos: string[];
};

const TZ = "America/Sao_Paulo";
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const SECOES: Record<string, string> = { eventos: "eventos", conversas: "dias de conversa" };

function texto(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function dinheiro(v: unknown): string | null {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? BRL.format(n) : null;
}

function descrever(item: TimelineItem): Linha {
  if (item.kind === "conversou") {
    return {
      icon: MessageCircle,
      cor: "#65b5ff",
      titulo: "Conversou",
      detalhe: item.mensagens === 1 ? "1 mensagem do cliente" : `${item.mensagens} mensagens do cliente`,
      selos: [],
    };
  }
  const m = item.metadata;
  switch (item.event_type) {
    case "entrada": {
      const canal = texto(m.canal) ?? item.new_value ?? "Origem desconhecida";
      const campanha =
        texto(m.campanha_nome) ?? texto(m.utm_campaign) ?? (texto(m.meta_ad_id) ? "Campanha não identificada" : null);
      return { icon: LogIn, cor: "#0bdf50", titulo: `Entrada — ${canal}`, detalhe: campanha, selos: [] };
    }
    case "etapa": {
      const funil = texto(m.pipeline_nome) ?? "Funil";
      const de = texto(m.de_label) ?? item.old_value;
      const para = texto(m.para_label) ?? item.new_value;
      const detalhe = de && para ? `${de} → ${para}` : para ? `Entrou em ${para}` : "Entrou no funil";
      return { icon: ArrowRightLeft, cor: "#7b7b78", titulo: `Etapa — ${funil}`, detalhe, selos: [] };
    }
    case "venda":
    case "venda_cancelada": {
      const cancelada = item.event_type === "venda_cancelada";
      const partes = [dinheiro(m.valor) ?? dinheiro(item.new_value), texto(m.produto)].filter(Boolean);
      const selos: string[] = [];
      if (m.kit === true) selos.push("kit");
      if (m.origin === "bling") selos.push("Bling");
      return {
        icon: cancelada ? Ban : ShoppingBag,
        cor: cancelada ? "#c41c1c" : "#ff5600",
        titulo: cancelada ? "Venda cancelada" : "Venda",
        detalhe: partes.join(" · ") || null,
        selos,
      };
    }
    case "disparo":
      return { icon: Megaphone, cor: "#a855f7", titulo: "Disparo", detalhe: texto(m.broadcast_nome) ?? item.new_value, selos: [] };
    case "mesclagem":
      return { icon: GitMerge, cor: "#7b7b78", titulo: "Lead mesclado", detalhe: item.new_value ?? item.old_value, selos: [] };
    case "atribuicao_manual":
      return {
        icon: Target,
        cor: "#ff5600",
        titulo: "Campanha atribuída manualmente",
        detalhe: texto(m.campanha_nome) ?? item.new_value,
        selos: ["manual"],
      };
    case "stage_change":
      return {
        icon: ArrowRightLeft,
        cor: "#7b7b78",
        titulo: "Etapa",
        detalhe: item.old_value && item.new_value ? `${item.old_value} → ${item.new_value}` : item.new_value,
        selos: [],
      };
    default:
      return { icon: Circle, cor: "#9ca3af", titulo: item.event_type, detalhe: item.new_value, selos: [] };
  }
}

function quando(item: TimelineItem): string {
  if (item.kind === "conversou") {
    const [ano, mes, dia] = item.dia.split("-");
    return `${dia}/${mes}/${ano}`;
  }
  const t = Date.parse(item.at);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleString("pt-BR", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Linha do tempo do lead: entradas (canal/campanha), etapas, vendas (valor e selo "kit"),
 * cancelamentos, disparos, mesclagens, atribuições manuais e os dias em que o cliente
 * conversou. Montada como aba no lead-detail-modal (P3) e no contact-detail (P4).
 */
export function LeadTimeline({ leadId }: LeadTimelineProps) {
  // A resposta guarda o leadId que a pediu: trocar de lead volta ao "carregando" sem
  // setState síncrono no efeito.
  const [res, setRes] = useState<{ leadId: string; data: TimelineResponse | null } | null>(null);

  useEffect(() => {
    let vivo = true;
    fetch(`/api/leads/${leadId}/timeline`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as TimelineResponse;
      })
      .then((data) => {
        if (vivo) setRes({ leadId, data });
      })
      .catch(() => {
        if (vivo) setRes({ leadId, data: null });
      });
    return () => {
      vivo = false;
    };
  }, [leadId]);

  if (!res || res.leadId !== leadId) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Carregando linha do tempo">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 rounded-[4px] bg-[#f0ede8] animate-pulse" />
        ))}
      </div>
    );
  }

  if (!res.data) {
    return <p className="text-[13px] text-[#c41c1c]">Não foi possível carregar a linha do tempo.</p>;
  }

  const { items, partial } = res.data;
  return (
    <div>
      {partial.length > 0 && (
        <p
          role="status"
          className="mb-3 rounded-[4px] border border-[#fde68a] bg-[#fef3c7] px-2 py-1 text-[12px] text-[#b45309]"
        >
          Parte da linha do tempo não carregou: {partial.map((p) => SECOES[p] ?? p).join(", ")}.
        </p>
      )}
      {items.length === 0 ? (
        <p className="py-4 text-center text-[13px] text-[#7b7b78]">Nenhum evento registrado ainda.</p>
      ) : (
        <ol className="relative ml-3 border-l border-[#dedbd6]">
          {items.map((item) => {
            const l = descrever(item);
            const Icon = l.icon;
            return (
              <li
                key={item.id}
                data-tipo={item.kind === "conversou" ? "conversou" : item.event_type}
                className="relative pb-4 pl-6 last:pb-0"
              >
                <span
                  className="absolute -left-3 top-0 flex h-6 w-6 items-center justify-center rounded-full border border-[#dedbd6] bg-white"
                  style={{ color: l.cor }}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  <p className="text-[13px] font-medium text-[#111111]">{l.titulo}</p>
                  {l.selos.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center rounded-[4px] border border-[#ff5600]/20 bg-[#ff5600]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.6px] text-[#ff5600]"
                    >
                      {s}
                    </span>
                  ))}
                </div>
                {l.detalhe && <p className="text-[12px] text-[#7b7b78]">{l.detalhe}</p>}
                <p className="text-[11px] text-[#9ca3af]">{quando(item)}</p>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

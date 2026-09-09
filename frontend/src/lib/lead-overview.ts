// Dono único da leitura de um lead no drill-down de /trafego/campanha.
//
// A tabela da campanha responde "quem chegou"; este módulo responde "e daí?".
// Toda a derivação vive aqui, fora do React, porque é ela que erra: somar
// receita, decidir se o lead conversou de verdade, e ordenar a trilha de
// movimentações. O componente só desenha o que sai daqui.
//
// Regra transversal: dado ausente vira travessão ou é descartado — nunca vira
// zero, nunca vira 1970. Um "R$ 0,00" mente; um "—" diz a verdade.

import { AGENT_STAGES, DEAL_STAGES } from "@/lib/constants";

const DASH = "—";
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** Etapas que encerram a oportunidade — não contam como pipeline aberto. */
const CLOSED_STAGE_KEYS = new Set(["fechado_ganho", "fechado_perdido"]);

// ─── Formato do payload de /api/leads/[id]/overview ────────────────────────────

export interface OverviewLead {
  id: string;
  name: string | null;
  phone: string | null;
  company: string | null;
  email: string | null;
  stage: string | null;
  status: string | null;
  channel: string | null;
  assigned_to: string | null;
  created_at: string;
  last_msg_at: string | null;
  last_customer_message_at: string | null;
  first_response_at: string | null;
  entered_stage_at: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  traffic_type: string | null;
  notes: string | null;
}

export interface OverviewDeal {
  id: string;
  title: string;
  value: number;
  stage_key: string | null;
  stage_label: string | null;
  dot_color: string | null;
  pipeline_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  lost_reason: string | null;
}

export interface OverviewSale {
  id: string;
  value: number;
  product: string | null;
  sold_at: string | null;
  sold_by: string | null;
  origin: string | null;
  status: string | null;
}

export interface OverviewEvent {
  id: string;
  event_type: string;
  old_value: string | null;
  new_value: string | null;
  created_at: string;
}

export interface OverviewNote {
  id: string;
  author: string | null;
  content: string;
  created_at: string;
}

export interface OverviewMessages {
  total: number;
  inbound: number;
  outbound: number;
  /** Primeira mensagem DO CLIENTE — marca o instante em que a conversa existiu. */
  first_inbound_at: string | null;
  last_at: string | null;
}

export interface OverviewCadence {
  id: string;
  name: string;
  status: string | null;
  enrolled_at: string | null;
}

export interface OverviewBroadcast {
  id: string;
  name: string;
  message_status: string | null;
  sent_at: string | null;
  first_replied_at: string | null;
}

export interface OverviewFollowup {
  sequence: number | null;
  job_type: string | null;
  status: string | null;
  fire_at: string | null;
  sent_at: string | null;
  objetivo: string | null;
}

export interface LeadOverview {
  lead: OverviewLead;
  deals: OverviewDeal[];
  sales: OverviewSale[];
  events: OverviewEvent[];
  notes: OverviewNote[];
  messages: OverviewMessages;
  cadences: OverviewCadence[];
  broadcasts: OverviewBroadcast[];
  followups: OverviewFollowup[];
}

// ─── Formatação ────────────────────────────────────────────────────────────────

/** "R$ 1.234,50" — mesma pontuação da tabela de leads da campanha. */
export function fmtBRL(v: number): string {
  return `R$ ${v.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return DASH;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return DASH;
  return new Date(t).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDate(iso: string | null): string {
  if (!iso) return DASH;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return DASH;
  return new Date(t).toLocaleDateString("pt-BR");
}

/**
 * Duração legível, truncando para baixo. "<1 min" existe para que uma resposta
 * de 12 segundos não vire "0 min" — o zero leria como "não respondeu".
 * Duração negativa (relógio torto entre webhook e banco) vira travessão em vez
 * de "-3 h", que só assustaria quem lê.
 */
export function humanDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms) || ms < 0) return DASH;
  if (ms < MIN) return "<1 min";
  if (ms < HOUR) return `${Math.floor(ms / MIN)} min`;
  if (ms < DAY) return `${Math.floor(ms / HOUR)} h`;
  return `${Math.floor(ms / DAY)} d`;
}

const STAGE_LABELS: Record<string, string> = {
  ...Object.fromEntries(DEAL_STAGES.map((s) => [s.key, s.label])),
  ...Object.fromEntries(AGENT_STAGES.map((s) => [s.key, s.label])),
};

/**
 * Rótulo de etapa, seja ela do funil (pipeline_stages.key) ou do agente
 * (leads.stage). Slug desconhecido volta como está: uma etapa nova criada em
 * produção precisa aparecer, não sumir atrás de um travessão.
 */
export function stageLabel(key: string | null | undefined): string {
  if (!key) return DASH;
  return STAGE_LABELS[key] ?? key;
}

const CADENCE_STATUS_LABELS: Record<string, string> = {
  active: "ativa",
  completed: "concluída",
  paused: "pausada",
  cancelled: "cancelada",
  canceled: "cancelada",
};

/** Status de inscrição em cadência em PT. Slug novo aparece cru, nunca some. */
export function cadenceStatusLabel(status: string | null): string | null {
  if (!status) return null;
  return CADENCE_STATUS_LABELS[status] ?? status;
}

type EventLike = Pick<OverviewEvent, "event_type" | "old_value" | "new_value">;

/**
 * Texto de um lead_event. Hoje a tabela grava quase só `stage_change`, mas o
 * default cai no próprio slug para que qualquer tipo novo apareça na trilha sem
 * depender de alguém lembrar de atualizar este switch.
 */
export function formatEventText(event: EventLike): string {
  const de = stageLabel(event.old_value);
  const para = stageLabel(event.new_value);
  switch (event.event_type) {
    case "stage_change":
      return `Etapa do agente: ${de} → ${para}`;
    case "stage_enter":
      return `Entrou na etapa ${para}`;
    case "deal_stage_change":
      return `Oportunidade: ${de} → ${para}`;
    case "deal_stage_enter":
      return `Oportunidade entrou em ${para}`;
    case "deal_closed_lost":
      return event.new_value ? `Oportunidade perdida: ${event.new_value}` : "Oportunidade perdida";
    case "sale_created":
      return "Venda registrada";
    case "tag_added":
      return `Tag ${event.new_value ?? ""}`.trim() + " adicionada";
    case "tag_removed":
      return `Tag ${event.old_value ?? ""}`.trim() + " removida";
    case "campaign_added":
    case "cadence_enrolled":
      return `Entrou na cadência ${event.new_value ?? ""}`.trimEnd();
    case "campaign_removed":
    case "cadence_unenrolled":
      return `Saiu da cadência ${event.new_value ?? event.old_value ?? ""}`.trimEnd();
    case "first_response":
      return "Primeira resposta recebida";
    case "optout":
      return "Lead pediu para não receber mais mensagens";
    default:
      return event.event_type;
  }
}

// ─── Sinais vitais ─────────────────────────────────────────────────────────────

export interface LeadVitals {
  diasNoCrm: number;
  diasNaEtapa: number | null;
  /** created_at → primeira mensagem do cliente. Quanto o anúncio demorou a virar conversa. */
  tempoAteContatoMs: number | null;
  /** created_at → first_response_at. Quanto NÓS demoramos a responder. */
  tempoAteRespostaMs: number | null;
  inatividadeMs: number | null;
  mensagens: { total: number; inbound: number; outbound: number };
  receita: number;
  pedidos: number;
  ticketMedio: number;
  pipelineAberto: number;
  dealsAbertos: number;
  dealsTotal: number;
  cadencias: number;
  disparos: number;
  notas: number;
}

function elapsed(fromIso: string | null | undefined, toMs: number): number | null {
  if (!fromIso) return null;
  const t = Date.parse(fromIso);
  return Number.isNaN(t) ? null : toMs - t;
}

function inDays(ms: number | null): number | null {
  return ms === null ? null : Math.max(0, Math.floor(ms / DAY));
}

/**
 * Instante em que o CLIENTE falou pela primeira vez, ou null se nunca falou.
 * Fonte única para os vitais e para a trilha — se as duas divergissem, o painel
 * mostraria "conversou" no funil e "—" no tempo até o contato.
 */
function firstCustomerContactAt(o: LeadOverview): string | null {
  return o.messages.first_inbound_at ?? o.lead.last_customer_message_at ?? null;
}

/**
 * `nowMs` entra por parâmetro em vez de `Date.now()` para o cálculo ser
 * determinístico no teste — e para o painel inteiro usar o MESMO "agora",
 * sem dois cards discordando por milissegundos.
 */
export function computeVitals(o: LeadOverview, nowMs: number): LeadVitals {
  const receita = o.sales.reduce((acc, s) => acc + (Number(s.value) || 0), 0);
  const pedidos = o.sales.length;
  const abertos = o.deals.filter((d) => !CLOSED_STAGE_KEYS.has(d.stage_key ?? ""));

  const criado = Date.parse(o.lead.created_at);

  /** Tempo entre a entrada do lead e um marco posterior. */
  const desdeAEntrada = (iso: string | null) => {
    if (!iso) return null;
    const t = Date.parse(iso);
    return Number.isNaN(t) || Number.isNaN(criado) ? null : t - criado;
  };

  return {
    diasNoCrm: inDays(elapsed(o.lead.created_at, nowMs)) ?? 0,
    diasNaEtapa: inDays(elapsed(o.lead.entered_stage_at, nowMs)),
    tempoAteContatoMs: desdeAEntrada(firstCustomerContactAt(o)),
    tempoAteRespostaMs: desdeAEntrada(o.lead.first_response_at),
    inatividadeMs: elapsed(o.lead.last_msg_at, nowMs),
    mensagens: {
      total: o.messages.total,
      inbound: o.messages.inbound,
      outbound: o.messages.outbound,
    },
    receita,
    pedidos,
    ticketMedio: pedidos > 0 ? receita / pedidos : 0,
    pipelineAberto: abertos.reduce((acc, d) => acc + (Number(d.value) || 0), 0),
    dealsAbertos: abertos.length,
    dealsTotal: o.deals.length,
    cadencias: o.cadences.length,
    disparos: o.broadcasts.length,
    notas: o.notes.length,
  };
}

// ─── Trilha do funil ───────────────────────────────────────────────────────────

export type JourneyKey = "entrou" | "conversou" | "oportunidade" | "comprou";

export interface JourneyStep {
  key: JourneyKey;
  label: string;
  reached: boolean;
  at: string | null;
}

export interface Journey {
  steps: JourneyStep[];
  /** Índice da última etapa alcançada quando o lead NÃO comprou. Null se comprou. */
  stalledAt: number | null;
}

function earliest(values: (string | null | undefined)[]): string | null {
  const times = values
    .filter((v): v is string => Boolean(v))
    .map((v) => [v, Date.parse(v)] as const)
    .filter(([, t]) => !Number.isNaN(t))
    .sort((a, b) => a[1] - b[1]);
  return times.length > 0 ? times[0][0] : null;
}

/**
 * Onde o lead parou: Entrou → Conversou → Oportunidade → Comprou.
 *
 * "Conversou" usa o mesmo critério do relatório de tráfego (`_conversed_ids`):
 * o CLIENTE falou. Mensagem só nossa é disparo, não conversa — contá-la
 * inflaria a etapa e esconderia exatamente o gargalo que a tela existe para
 * mostrar.
 */
export function buildJourney(o: LeadOverview): Journey {
  const contatoAt = firstCustomerContactAt(o);
  const conversou = contatoAt !== null || o.messages.inbound > 0;

  const raw: JourneyStep[] = [
    { key: "entrou", label: "Entrou", reached: true, at: o.lead.created_at },
    { key: "conversou", label: "Conversou", reached: conversou, at: contatoAt },
    {
      key: "oportunidade",
      label: "Oportunidade",
      reached: o.deals.length > 0,
      at: earliest(o.deals.map((d) => d.created_at)),
    },
    {
      key: "comprou",
      label: "Comprou",
      reached: o.sales.length > 0,
      at: earliest(o.sales.map((s) => s.sold_at)),
    },
  ];

  // Monotonicidade: uma etapa alcançada implica todas as anteriores. Venda vinda
  // do Bling costuma chegar sem deal no CRM; sem isto a trilha mostraria
  // "comprou, mas nunca virou oportunidade" — que lê como bug, não como dado.
  let seen = false;
  for (let i = raw.length - 1; i >= 0; i--) {
    if (raw[i].reached) seen = true;
    else if (seen) raw[i].reached = true;
  }

  const last = raw.reduce((acc, s, i) => (s.reached ? i : acc), 0);
  return { steps: raw, stalledAt: raw[raw.length - 1].reached ? null : last };
}

// ─── Movimentações ─────────────────────────────────────────────────────────────

export type MovementKind =
  | "entrada"
  | "evento"
  | "nota"
  | "venda"
  | "oportunidade"
  | "disparo"
  | "cadencia"
  | "followup";

export interface Movement {
  id: string;
  at: string;
  kind: MovementKind;
  title: string;
  detail: string | null;
}

function push(list: Movement[], at: string | null | undefined, m: Omit<Movement, "at">): void {
  // Item sem data é descartado: colocá-lo no topo (ou em 1970) inventaria uma
  // ordem que o dado não tem.
  if (!at || Number.isNaN(Date.parse(at))) return;
  list.push({ ...m, at });
}

/** Tudo que aconteceu com o lead, do mais recente ao mais antigo. */
export function buildMovements(o: LeadOverview): Movement[] {
  const out: Movement[] = [];

  const origem = [o.lead.utm_source, o.lead.utm_medium, o.lead.utm_campaign]
    .filter(Boolean)
    .join(" · ");
  push(out, o.lead.created_at, {
    id: `entrada-${o.lead.id}`,
    kind: "entrada",
    title: "Lead entrou no CRM",
    detail: origem || o.lead.channel || null,
  });

  for (const e of o.events) {
    push(out, e.created_at, {
      id: `evento-${e.id}`,
      kind: "evento",
      title: formatEventText(e),
      detail: null,
    });
  }

  for (const n of o.notes) {
    push(out, n.created_at, {
      id: `nota-${n.id}`,
      kind: "nota",
      title: n.author ? `Nota de ${n.author}` : "Nota",
      detail: n.content,
    });
  }

  for (const s of o.sales) {
    push(out, s.sold_at, {
      id: `venda-${s.id}`,
      kind: "venda",
      title: `Venda de ${fmtBRL(Number(s.value) || 0)}`,
      detail: s.product ?? s.sold_by ?? null,
    });
  }

  for (const d of o.deals) {
    push(out, d.created_at, {
      id: `oportunidade-${d.id}`,
      kind: "oportunidade",
      title: `Oportunidade criada — ${fmtBRL(Number(d.value) || 0)}`,
      detail: d.stage_label ?? stageLabel(d.stage_key),
    });
  }

  for (const b of o.broadcasts) {
    push(out, b.sent_at, {
      id: `disparo-${b.id}`,
      kind: "disparo",
      title: `Disparo "${b.name}"`,
      detail: b.first_replied_at ? "respondeu" : (b.message_status ?? null),
    });
  }

  for (const c of o.cadences) {
    push(out, c.enrolled_at, {
      id: `cadencia-${c.id}`,
      kind: "cadencia",
      title: `Entrou na cadência "${c.name}"`,
      detail: cadenceStatusLabel(c.status),
    });
  }

  for (const f of o.followups) {
    // Só follow-up ENVIADO é movimentação. O agendado é futuro, e futuro não
    // pertence a uma trilha de histórico.
    push(out, f.sent_at, {
      id: `followup-${f.sequence ?? "?"}-${f.sent_at}`,
      kind: "followup",
      title: `Follow-up T${f.sequence ?? "?"} enviado`,
      detail: f.objetivo,
    });
  }

  return out.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

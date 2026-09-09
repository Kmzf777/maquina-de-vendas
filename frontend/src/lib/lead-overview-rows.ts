// Tradutor entre as linhas cruas do PostgREST e o payload do painel do lead.
//
// Vive fora da rota de propósito: é aqui que os erros de integração moram
// (relação embutida que chega como array, `value` numérico que chega string,
// coluna `status` que significa outra coisa dependendo da tabela) e é aqui que
// dá para testar sem subir banco nenhum. A rota fica só com as consultas.

import type {
  OverviewBroadcast,
  OverviewCadence,
  OverviewDeal,
  OverviewEvent,
  OverviewFollowup,
  OverviewLead,
  OverviewNote,
  OverviewSale,
} from "@/lib/lead-overview";

export type Row = Record<string, unknown>;

/**
 * Relação embutida do PostgREST: vem como objeto quando ele prova que a FK é
 * única, e como array de um quando não prova. Ler só uma das formas deixaria o
 * campo vazio em silêncio — sem erro, sem log, sem ninguém perceber.
 */
export function embedded(value: unknown): Row | null {
  if (Array.isArray(value)) return (value[0] as Row) ?? null;
  return (value as Row) ?? null;
}

/** String de verdade, ou nulo. String vazia é ausência disfarçada. */
export const str = (v: unknown): string | null =>
  typeof v === "string" && v !== "" ? v : null;

/** Número de verdade, ou zero — `numeric` do Postgres chega como string. */
export const num = (v: unknown): number => (Number.isFinite(Number(v)) ? Number(v) : 0);

const int = (v: unknown): number | null =>
  v === null || v === undefined || !Number.isFinite(Number(v)) ? null : Number(v);

export function mapLead(r: Row): OverviewLead {
  return {
    id: String(r.id),
    name: str(r.name),
    phone: str(r.phone),
    company: str(r.company),
    email: str(r.email),
    stage: str(r.stage),
    status: str(r.status),
    channel: str(r.channel),
    assigned_to: str(r.assigned_to),
    created_at: String(r.created_at),
    last_msg_at: str(r.last_msg_at),
    last_customer_message_at: str(r.last_customer_message_at),
    first_response_at: str(r.first_response_at),
    entered_stage_at: str(r.entered_stage_at),
    utm_source: str(r.utm_source),
    utm_medium: str(r.utm_medium),
    utm_campaign: str(r.utm_campaign),
    traffic_type: str(r.traffic_type),
    notes: str(r.notes),
  };
}

export function mapDeal(r: Row): OverviewDeal {
  const stage = embedded(r.pipeline_stages);
  const pipeline = embedded(r.pipelines);
  return {
    id: String(r.id),
    title: str(r.title) ?? "Oportunidade",
    value: num(r.value),
    stage_key: str(stage?.key),
    stage_label: str(stage?.label),
    dot_color: str(stage?.dot_color),
    pipeline_name: str(pipeline?.name),
    created_at: str(r.created_at),
    updated_at: str(r.updated_at),
    lost_reason: str(r.lost_reason),
  };
}

export function mapSale(r: Row): OverviewSale {
  return {
    id: String(r.id),
    value: num(r.value),
    product: str(r.product),
    sold_at: str(r.sold_at),
    sold_by: str(r.sold_by),
    origin: str(r.origin),
    status: str(r.status),
  };
}

export function mapEvent(r: Row): OverviewEvent {
  return {
    id: String(r.id),
    event_type: str(r.event_type) ?? "evento",
    old_value: str(r.old_value),
    new_value: str(r.new_value),
    created_at: String(r.created_at),
  };
}

export function mapNote(r: Row): OverviewNote {
  return {
    id: String(r.id),
    author: str(r.author),
    content: str(r.content) ?? "",
    created_at: String(r.created_at),
  };
}

export function mapCadence(r: Row): OverviewCadence {
  return {
    id: String(r.id),
    name: str(embedded(r.campaigns)?.name) ?? "Cadência",
    status: str(r.status),
    enrolled_at: str(r.enrolled_at),
  };
}

export function mapBroadcast(r: Row): OverviewBroadcast {
  return {
    id: String(r.id),
    name: str(embedded(r.broadcasts)?.name) ?? "Disparo",
    // `status` em broadcast_leads é o status da MENSAGEM daquele lead, não o do
    // disparo. O nome muda aqui para os dois não se confundirem na leitura.
    message_status: str(r.status),
    sent_at: str(r.sent_at),
    first_replied_at: str(r.first_replied_at),
  };
}

export function mapFollowup(r: Row): OverviewFollowup {
  const md = (r.metadata ?? {}) as Row;
  return {
    sequence: int(r.sequence),
    job_type: str(r.job_type),
    status: str(r.status),
    fire_at: str(r.fire_at),
    sent_at: str(r.sent_at),
    objetivo: str(md.objetivo),
  };
}

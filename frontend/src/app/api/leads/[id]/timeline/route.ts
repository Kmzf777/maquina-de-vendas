// Linha do tempo do lead (P3 da call de 01/10): eventos de `lead_events` (gravados pelos
// triggers da migração 20261006b e pelo backfill) + marcadores diários "conversou",
// calculados na leitura a partir das mensagens inbound em `messages`.
//
// Qualquer usuário autenticado: o vendedor abre pela conversa (contact-detail). As vendas
// seguem o MESMO escopo de /api/leads/[id]/sales. Com escopo, a decisão usa o `sold_by` e o
// `origin` ATUAIS de `sales` (busca pelos `sale_id` dos eventos), não a cópia no metadata:
// a venda é editável e a cópia pode estar velha. Venda que não está mais em `sales`, ou
// falha na busca, esconde o evento (partial "vendas").
//
// Seções falham de forma independente e aparecem em `partial` (mesmo contrato da rota
// overview): sem a P0 aplicada, `occurred_at` não existe e "eventos" cai — os dias de
// conversa continuam aparecendo.

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser, type CurrentUser } from "@/lib/supabase/pipeline-access";
import { podeVerVenda, salesScopeFilter, scopeAtivo } from "@/lib/sales/sales-scope";
import type {
  TimelineConversou,
  TimelineEvent,
  TimelineItem,
  TimelineResponse,
} from "@/components/leads/lead-timeline";

/** Uma vida inteira de lead cabe folgado; acima disso a tela já não é lida. */
const MAX_EVENTS = 500;
/** max-rows do PostgREST: páginas maiores voltam cortadas em silêncio. */
const PAGE = 1000;
const MAX_MESSAGE_PAGES = 20;
const TZ = "America/Sao_Paulo";
const TIPOS_VENDA = new Set(["venda", "venda_cancelada"]);

type Row = Record<string, unknown>;
type Sb = Awaited<ReturnType<typeof getServiceSupabase>>;

function str(v: unknown): string | null {
  return typeof v === "string" && v !== "" ? v : null;
}

function obj(v: unknown): Row {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Row) : {};
}

function ts(iso: string): number {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
}

const diaSP = new Intl.DateTimeFormat("en-CA", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function mapEvento(r: Row): TimelineEvent {
  return {
    kind: "evento",
    id: String(r.id),
    event_type: str(r.event_type) ?? "evento",
    at: str(r.occurred_at) ?? str(r.created_at) ?? "",
    source: str(r.source),
    old_value: str(r.old_value),
    new_value: str(r.new_value),
    metadata: obj(r.metadata),
  };
}

/** Um marcador por dia (São Paulo) com mensagem do cliente, posicionado na última do dia. */
function diasConversou(inbound: string[]): TimelineConversou[] {
  const porDia = new Map<string, { ultimo: number; n: number }>();
  for (const iso of inbound) {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) continue;
    const dia = diaSP.format(t);
    const atual = porDia.get(dia);
    if (atual) {
      atual.n += 1;
      atual.ultimo = Math.max(atual.ultimo, t);
    } else {
      porDia.set(dia, { ultimo: t, n: 1 });
    }
  }
  return [...porDia].map(([dia, { ultimo, n }]) => ({
    kind: "conversou",
    id: `conversou:${dia}`,
    dia,
    at: new Date(ultimo).toISOString(),
    mensagens: n,
  }));
}

type Dono = { sold_by: string | null; origin: string | null };

/** false = sem escopo (admin ou flag desligada). E-mail inválido conta como escopo. */
function temEscopo(user: CurrentUser, escopo: boolean): boolean {
  try {
    return salesScopeFilter({ userId: user.userId, email: user.email, role: user.role }, escopo) !== null;
  } catch {
    return true;
  }
}

/** sold_by/origin atuais das vendas citadas nos eventos; null se a busca falhou. */
async function donosAtuais(sb: Sb, eventos: TimelineEvent[]): Promise<Map<string, Dono> | null> {
  const ids = [
    ...new Set(
      eventos
        .filter((e) => TIPOS_VENDA.has(e.event_type))
        .map((e) => str(e.metadata.sale_id))
        .filter((v): v is string => v !== null),
    ),
  ];
  if (ids.length === 0) return new Map();
  try {
    const { data, error } = await sb.from("sales").select("id, sold_by, origin").in("id", ids);
    if (error) return null;
    return new Map(
      ((data ?? []) as unknown as Row[]).map((r) => [String(r.id), { sold_by: str(r.sold_by), origin: str(r.origin) }]),
    );
  } catch {
    return null;
  }
}

function vendaVisivel(
  e: TimelineEvent,
  user: CurrentUser,
  escopo: boolean,
  donos: Map<string, Dono> | null,
): boolean {
  if (!TIPOS_VENDA.has(e.event_type)) return true;
  const saleId = str(e.metadata.sale_id);
  const dono = donos && saleId ? donos.get(saleId) : undefined;
  if (!dono) return false;
  try {
    return podeVerVenda(dono, { userId: user.userId, email: user.email, role: user.role }, escopo);
  } catch {
    // e-mail ausente/inválido: na dúvida, esconde (mesma postura do escopo de /painel-vendas)
    return false;
  }
}

async function carregarEventos(sb: Sb, id: string, partial: string[]): Promise<TimelineEvent[]> {
  try {
    const { data, error } = await sb
      .from("lead_events")
      .select("id, event_type, old_value, new_value, metadata, occurred_at, created_at, source")
      .eq("lead_id", id)
      .order("occurred_at", { ascending: false })
      .limit(MAX_EVENTS);
    if (error) throw new Error(error.message);
    return ((data ?? []) as unknown as Row[]).map(mapEvento);
  } catch {
    partial.push("eventos");
    return [];
  }
}

async function carregarInbound(sb: Sb, id: string, partial: string[]): Promise<string[]> {
  const out: string[] = [];
  try {
    for (let pagina = 0; pagina < MAX_MESSAGE_PAGES; pagina++) {
      const { data, error } = await sb
        .from("messages")
        .select("created_at")
        .eq("lead_id", id)
        .eq("role", "user")
        .order("created_at", { ascending: false })
        .range(pagina * PAGE, pagina * PAGE + PAGE - 1);
      if (error) throw new Error(error.message);
      const rows = (data ?? []) as unknown as Row[];
      for (const r of rows) {
        const c = str(r.created_at);
        if (c) out.push(c);
      }
      if (rows.length < PAGE) break;
    }
    return out;
  } catch {
    partial.push("conversas");
    return [];
  }
}

/** Entrada gravada antes do mapa anúncio→campanha sincronizar: completa na leitura. */
async function completarCampanhas(sb: Sb, eventos: TimelineEvent[]): Promise<TimelineEvent[]> {
  const semNome = [
    ...new Set(
      eventos
        .filter((e) => e.event_type === "entrada" && !str(e.metadata.campanha_nome) && str(e.metadata.meta_ad_id))
        .map((e) => String(e.metadata.meta_ad_id)),
    ),
  ];
  if (semNome.length === 0) return eventos;
  try {
    const { data, error } = await sb
      .from("meta_ad_campaigns")
      .select("ad_id, campaign_id, campaign_name")
      .in("ad_id", semNome);
    if (error) return eventos;
    const porAd = new Map(((data ?? []) as unknown as Row[]).map((r) => [String(r.ad_id), r]));
    return eventos.map((e) => {
      const c = e.event_type === "entrada" ? porAd.get(String(e.metadata.meta_ad_id)) : undefined;
      if (!c || !str(c.campaign_name)) return e;
      return {
        ...e,
        metadata: {
          ...e.metadata,
          campanha_id: str(e.metadata.campanha_id) ?? str(c.campaign_id),
          campanha_nome: str(c.campaign_name),
        },
      };
    });
  } catch {
    return eventos;
  }
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  let user: CurrentUser;
  try {
    user = await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const sb = await getServiceSupabase();

  const { data: lead, error: leadError } = await sb.from("leads").select("id").eq("id", id).maybeSingle();
  if (leadError) return NextResponse.json({ error: leadError.message }, { status: 500 });
  if (!lead) return NextResponse.json({ error: "lead_not_found" }, { status: 404 });

  const partial: string[] = [];
  const [eventos, inbound] = await Promise.all([
    carregarEventos(sb, id, partial),
    carregarInbound(sb, id, partial),
  ]);

  const escopo = scopeAtivo();
  let filtrados = eventos;
  if (temEscopo(user, escopo)) {
    const donos = await donosAtuais(sb, eventos);
    if (donos === null) partial.push("vendas");
    filtrados = eventos.filter((e) => vendaVisivel(e, user, escopo, donos));
  }
  const visiveis = await completarCampanhas(sb, filtrados);

  const items: TimelineItem[] = [...visiveis, ...diasConversou(inbound)].sort(
    (a, b) => ts(b.at) - ts(a.at),
  );
  const payload: TimelineResponse = { items, partial };
  return NextResponse.json(payload);
}

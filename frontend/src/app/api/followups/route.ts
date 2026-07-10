import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

const VALID_STATUSES = new Set(["pending", "awaiting_reopen", "sent", "cancelled"]);
const MAX_LIMIT = 200;

/** Lista global de follow_up_jobs para o painel do motor (aba Follow-up).
 *  pending/awaiting_reopen: próximos primeiro (fire_at asc);
 *  sent/cancelled: mais recentes primeiro. */
export async function GET(request: NextRequest) {
  const status = request.nextUrl.searchParams.get("status") ?? "pending";
  if (!VALID_STATUSES.has(status)) {
    return NextResponse.json({ error: `status inválido: ${status}` }, { status: 400 });
  }
  const rawLimit = Number(request.nextUrl.searchParams.get("limit") ?? 100);
  const limit = Math.min(Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : 100, MAX_LIMIT);

  const supabase = await getServiceSupabase();
  const ascending = status === "pending" || status === "awaiting_reopen";
  const orderColumn = status === "sent" ? "sent_at" : "fire_at";

  const { data, error } = await supabase
    .from("follow_up_jobs")
    .select("id, sequence, job_type, status, fire_at, sent_at, cancel_reason, metadata, lead_id, conversation_id, leads(name, phone)")
    .eq("env_tag", APP_ENV)
    .eq("status", status)
    .order(orderColumn, { ascending, nullsFirst: false })
    .limit(limit);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows = (data ?? []).map((j) => {
    const md = (j.metadata ?? {}) as Record<string, unknown>;
    // Join singular: supabase-js tipa embed como array | objeto dependendo do FK — normaliza.
    const lead = (Array.isArray(j.leads) ? j.leads[0] : j.leads) as
      | { name: string | null; phone: string | null }
      | null
      | undefined;
    return {
      id: j.id,
      sequence: j.sequence,
      job_type: j.job_type,
      status: j.status,
      fire_at: j.fire_at,
      sent_at: j.sent_at,
      cancel_reason: j.cancel_reason,
      objetivo: (md.objetivo as string | undefined) ?? null,
      lead_id: j.lead_id,
      conversation_id: j.conversation_id,
      lead_name: lead?.name ?? null,
      lead_phone: lead?.phone ?? null,
    };
  });

  return NextResponse.json(rows);
}

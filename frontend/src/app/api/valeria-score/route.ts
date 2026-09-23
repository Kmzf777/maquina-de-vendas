import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";

const PAGE_SIZE_DEFAULT = 25;
const PAGE_SIZE_MAX = 100;

function integerParam(value: string | null, fallback: number, maximum: number) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(1, parsed)) : fallback;
}

function selectedValues<T extends string>(value: string | null, allowed: readonly T[]): T[] {
  return (value ?? "").split(",").filter((candidate): candidate is T => (allowed as readonly string[]).includes(candidate));
}

/** Directory view keeps UTM and Click-to-WhatsApp campaign attribution in one query. */
export async function GET(request: NextRequest) {
  let user: Awaited<ReturnType<typeof getCurrentUser>>;
  try {
    user = await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "Não autenticado" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const page = integerParam(searchParams.get("page"), 1, Number.MAX_SAFE_INTEGER);
  const pageSize = integerParam(searchParams.get("page_size"), PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX);
  const q = (searchParams.get("q")?.trim() ?? "").replace(/[^\p{L}\p{N}\s+@-]/gu, "");
  const scores = selectedValues(searchParams.get("score"), ["0", "1", "2", "3", "4", "5", "6", "10"] as const).map(Number);
  const priorities = selectedValues(searchParams.get("priority"), ["low", "moderate", "high", "maximum"] as const);
  const status = searchParams.get("status");
  const campaign = searchParams.get("campaign")?.trim() ?? "";
  const trafficType = searchParams.get("traffic_type");
  const supabase = await getServiceSupabase();

  let directory = supabase
    .from("valeria_score_directory")
    .select("lead_id, name, phone, company, traffic_type, campaign_name, last_interaction_at, segment, monthly_volume_kg, supplier_reason, purchase_timing, purchase_intent, evidence, normal_score, final_score, priority, priority_rank, is_provisional, score_updated_at", { count: "exact" })
    .order("priority_rank", { ascending: false, nullsFirst: false })
    .order("last_interaction_at", { ascending: false, nullsFirst: false })
    .range((page - 1) * pageSize, page * pageSize - 1);
  if (q) directory = directory.or(`name.ilike.%${q}%,phone.ilike.%${q}%,company.ilike.%${q}%`);
  if (scores.length) directory = directory.in("final_score", scores);
  if (priorities.length) directory = directory.in("priority", priorities);
  if (status === "provisional") directory = directory.eq("is_provisional", true);
  if (status === "consolidated") directory = directory.eq("is_provisional", false);
  if (campaign) directory = directory.eq("campaign_name", campaign);
  if (trafficType === "paid" || trafficType === "organic") directory = directory.eq("traffic_type", trafficType);
  if (trafficType === "unattributed") directory = directory.is("traffic_type", null);

  const { data: rows, error, count } = await directory;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const leadIds = (rows ?? []).map((row: { lead_id: string }) => row.lead_id);
  const { data: feelings, error: feelingsError } = leadIds.length
    ? await supabase.from("lead_seller_feelings").select("lead_id, user_id, seller_email, feeling, justification, updated_at").in("lead_id", leadIds).order("updated_at", { ascending: false })
    : { data: [], error: null };
  if (feelingsError) return NextResponse.json({ error: feelingsError.message }, { status: 500 });

  const latestFeelingByLead = new Map<string, unknown>();
  const ownFeelingByLead = new Map<string, unknown>();
  for (const feeling of feelings ?? []) {
    const leadId = (feeling as { lead_id: string; user_id: string }).lead_id;
    if (!latestFeelingByLead.has(leadId)) latestFeelingByLead.set(leadId, feeling);
    if ((feeling as { user_id: string }).user_id === user.userId) ownFeelingByLead.set(leadId, feeling);
  }
  const items = (rows ?? []).map((row: Record<string, unknown>) => ({
    id: row.lead_id,
    name: row.name,
    phone: row.phone,
    company: row.company,
    campaign: row.campaign_name,
    traffic_type: row.traffic_type,
    last_interaction_at: row.last_interaction_at,
    score: row.final_score == null ? null : {
      segment: row.segment, monthly_volume_kg: row.monthly_volume_kg, supplier_reason: row.supplier_reason,
      purchase_timing: row.purchase_timing, purchase_intent: row.purchase_intent, evidence: row.evidence,
      normal_score: row.normal_score, final_score: row.final_score, priority: row.priority,
      is_provisional: row.is_provisional, updated_at: row.score_updated_at,
    },
    feeling: latestFeelingByLead.get(row.lead_id as string) ?? null,
    own_feeling: ownFeelingByLead.get(row.lead_id as string) ?? null,
  }));

  const { count: campaignCount, error: campaignCountError } = await supabase.from("valeria_score_campaign_options").select("campaign_name", { count: "exact", head: true });
  if (campaignCountError) return NextResponse.json({ error: campaignCountError.message }, { status: 500 });
  const campaignRows: Array<{ campaign_name: string | null }> = [];
  for (let offset = 0; offset < (campaignCount ?? 0); offset += 1000) {
    const { data, error: campaignsError } = await supabase.from("valeria_score_campaign_options").select("campaign_name").order("campaign_name").range(offset, offset + 999);
    if (campaignsError) return NextResponse.json({ error: campaignsError.message }, { status: 500 });
    campaignRows.push(...(data ?? []));
  }
  const campaigns = [...new Set(campaignRows.map((row) => row.campaign_name).filter((name): name is string => Boolean(name)))].sort();
  return NextResponse.json({ items, total: count ?? 0, page, page_size: pageSize, campaigns, current_user_id: user.userId, current_user_role: user.role ?? null });
}

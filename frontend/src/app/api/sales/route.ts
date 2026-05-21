import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const leadId = searchParams.get("lead_id");
  const soldBy = searchParams.get("sold_by");
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const search = searchParams.get("search");
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const limit = Math.min(100, Math.max(1, parseInt(searchParams.get("limit") ?? "25", 10) || 25));
  const offset = (page - 1) * limit;

  const supabase = await getServiceSupabase();

  let query = supabase
    .from("sales")
    .select("*, leads(id, name, phone, company), deals(id, title)", { count: "exact" })
    .order("sold_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (leadId) query = query.eq("lead_id", leadId);
  if (soldBy) query = query.eq("sold_by", soldBy);
  if (from) query = query.gte("sold_at", from.length === 10 ? `${from}T00:00:00.000Z` : from);
  if (to) query = query.lte("sold_at", to.length === 10 ? `${to}T23:59:59.999Z` : to);
  if (search) query = query.ilike("product", `%${search}%`);

  const { data, error, count } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data: data ?? [], count: count ?? 0 });
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  if (!body.lead_id) return NextResponse.json({ error: "lead_id é obrigatório" }, { status: 400 });
  if (!body.product?.trim()) return NextResponse.json({ error: "product é obrigatório" }, { status: 400 });
  if (body.value == null || isNaN(Number(body.value))) {
    return NextResponse.json({ error: "value é obrigatório" }, { status: 400 });
  }

  const { data, error } = await supabase
    .from("sales")
    .insert({
      lead_id: body.lead_id,
      sold_at: body.sold_at || new Date().toISOString(),
      value: Number(body.value),
      product: body.product.trim(),
      sold_by: body.sold_by || null,
      deal_id: body.deal_id || null,
      conversation_id: body.conversation_id || null,
      notes: body.notes?.trim() || null,
    })
    .select("*, leads(id, name, phone, company), deals(id, title)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fire-and-forget: notify automation engine of the new sale
  const backendUrl = (process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000").replace(/\/+$/, "");
  void fetch(`${backendUrl}/api/automation/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: "sale_created",
      lead_id: data.lead_id,
      data: {
        sale_id: data.id,
        value: data.value,
        product: data.product,
        deal_id: data.deal_id,
      },
    }),
  }).catch(() => {});

  if (body.deal_id) {
    const { data: wonStage } = await supabase
      .from("pipeline_stages")
      .select("id")
      .eq("key", "fechado_ganho")
      .limit(1)
      .maybeSingle();
    if (wonStage) {
      await supabase
        .from("deals")
        .update({
          stage_id: wonStage.id,
          closed_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        })
        .eq("id", body.deal_id);
    }
  }

  return NextResponse.json(data, { status: 201 });
}

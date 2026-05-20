import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const status = new URL(request.url).searchParams.get("status");
  const supabase = await getServiceSupabase();
  let q = supabase.from("campaign_enrollments").select("*, leads!inner(id, name, phone, stage)").eq("campaign_id", id);
  if (status) q = q.eq("status", status);
  const { data, error } = await q.order("enrolled_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data: nodes } = await supabase.from("campaign_nodes").select("*").eq("campaign_id", id);
  const trigger = nodes?.find((n: { type: string }) => n.type === "trigger");
  if (!trigger?.next_node_id) return NextResponse.json({ error: "Campaign sem fluxo" }, { status: 400 });
  const { data, error } = await supabase
    .from("campaign_enrollments")
    .insert({ campaign_id: id, lead_id: body.lead_id, deal_id: body.deal_id ?? null, current_node_id: trigger.next_node_id, next_execute_at: new Date().toISOString(), env_tag: APP_ENV })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

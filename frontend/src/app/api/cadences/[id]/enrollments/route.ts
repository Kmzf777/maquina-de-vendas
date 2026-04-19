import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const status = request.nextUrl.searchParams.get("status");
  const supabase = await getServiceSupabase();

  let query = supabase
    .from("cadence_enrollments")
    .select("*, leads!inner(id, name, phone, company, stage)")
    .eq("cadence_id", id)
    .order("enrolled_at", { ascending: false });

  if (status) query = query.eq("status", status);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data: cadence } = await supabase
    .from("cadences")
    .select("env_tag")
    .eq("id", id)
    .single();

  if (cadence?.env_tag !== APP_ENV) {
    return NextResponse.json(
      { error: "Cadência pertence a outro ambiente" },
      { status: 403 }
    );
  }

  const { data, error } = await supabase
    .from("cadence_enrollments")
    .insert({
      cadence_id: id,
      lead_id: body.lead_id,
      deal_id: body.deal_id || null,
      status: "active",
      current_step: 0,
      total_messages_sent: 0,
      env_tag: APP_ENV,
    })
    .select("*, leads!inner(id, name, phone, company, stage)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

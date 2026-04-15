import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("cadence_steps")
    .select("*")
    .eq("cadence_id", id)
    .order("step_order");

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

  const { data, error } = await supabase
    .from("cadence_steps")
    .insert({
      cadence_id: id,
      step_order: body.step_order,
      message_text: body.message_text,
      delay_days: body.delay_days ?? 0,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

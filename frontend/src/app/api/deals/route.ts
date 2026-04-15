import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("deals")
    .select("*, leads(id, name, company, phone, nome_fantasia)")
    .order("updated_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase
    .from("deals")
    .insert({
      lead_id: body.lead_id,
      title: body.title,
      value: body.value || 0,
      stage: "novo",
      category: body.category || null,
      expected_close_date: body.expected_close_date || null,
      assigned_to: body.assigned_to || null,
    })
    .select("*, leads(id, name, company, phone, nome_fantasia)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("quick_send_phones")
    .select("id, phone, label")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const { phone, label } = await request.json();

  if (!phone || typeof phone !== "string") {
    return NextResponse.json({ error: "phone é obrigatório" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("quick_send_phones")
    .insert({ phone, label: label ?? null })
    .select("id, phone, label")
    .single();

  if (error) {
    if (error.code === "23505") {
      return NextResponse.json({ error: "Número já salvo" }, { status: 409 });
    }
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data, { status: 201 });
}

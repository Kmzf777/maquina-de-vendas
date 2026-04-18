import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(request: NextRequest) {
  const { phone } = await request.json();

  if (!phone || typeof phone !== "string") {
    return NextResponse.json({ error: "phone é obrigatório" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  const { data: existing } = await supabase
    .from("leads")
    .select("id")
    .eq("phone", phone)
    .maybeSingle();

  if (existing) {
    return NextResponse.json({ id: existing.id, created: false });
  }

  const { data, error } = await supabase
    .from("leads")
    .insert({ phone, status: "imported", stage: "pending" })
    .select("id")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ id: data.id, created: true }, { status: 201 });
}

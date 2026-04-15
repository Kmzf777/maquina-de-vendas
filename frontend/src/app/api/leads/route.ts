import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();

  const { data: leads, error } = await supabase
    .from("leads")
    .select("*, lead_tags(tag_id, tags(*))")
    .order("last_msg_at", { ascending: false, nullsFirst: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(leads);
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const body = await request.json();

  const { data: existing } = await supabase
    .from("leads")
    .select("id")
    .eq("phone", body.phone)
    .maybeSingle();

  if (existing) {
    return NextResponse.json(
      { error: "Lead com este telefone ja existe" },
      { status: 409 }
    );
  }

  const { data, error } = await supabase
    .from("leads")
    .insert({
      phone: body.phone,
      name: body.name || null,
      email: body.email || null,
      instagram: body.instagram || null,
      company: body.company || null,
      cnpj: body.cnpj || null,
      stage: body.stage || "secretaria",
      channel: body.channel || "manual",
      status: "active",
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data, { status: 201 });
}

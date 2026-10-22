import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { normalizePhoneBR } from "@/lib/phone";
import { findLeadByPhoneVariants } from "@/lib/lead-phone-lookup";

export async function POST(request: NextRequest) {
  const { phone } = await request.json();

  if (!phone || typeof phone !== "string") {
    return NextResponse.json({ error: "phone é obrigatório" }, { status: 400 });
  }

  // Canônico + busca em todas as formas antigas: sem isso o disparo rápido
  // criava um segundo lead para número já gravado sem o 9/sem o 55 (cartão b747da43).
  const canonical = normalizePhoneBR(phone);
  if (!canonical) {
    const n = phone.replace(/\D/g, "").length;
    return NextResponse.json(
      { error: `Telefone inválido: ${n} dígito(s). Use DDD + número (ex.: 34 99999-9999)` },
      { status: 422 },
    );
  }

  const supabase = await getServiceSupabase();

  let existing;
  try {
    existing = await findLeadByPhoneVariants(supabase, canonical);
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : String(err) }, { status: 500 });
  }

  if (existing) {
    return NextResponse.json({ id: existing.id, created: false });
  }

  const { data, error } = await supabase
    .from("leads")
    .insert({ phone: canonical, status: "imported", stage: "pending", origem_cadastro: "manual" })
    .select("id")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ id: data.id, created: true }, { status: 201 });
}

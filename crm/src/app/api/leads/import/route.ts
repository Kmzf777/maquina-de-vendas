import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

interface ImportLead {
  phone: string;
  name?: string;
  email?: string;
  instagram?: string;
  company?: string;
  cnpj?: string;
  razao_social?: string;
  nome_fantasia?: string;
  endereco?: string;
  telefone_comercial?: string;
  stage?: string;
  seller_stage?: string;
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { leads, skipDuplicates } = (await request.json()) as {
    leads: ImportLead[];
    skipDuplicates: boolean;
  };

  const phones = leads.map((l) => l.phone);
  const { data: existing } = await supabase
    .from("leads")
    .select("phone")
    .in("phone", phones);

  const existingPhones = new Set((existing || []).map((e) => e.phone));

  const toInsert: ImportLead[] = [];
  const toUpdate: ImportLead[] = [];
  const skipped: string[] = [];

  for (const lead of leads) {
    if (existingPhones.has(lead.phone)) {
      if (skipDuplicates) {
        skipped.push(lead.phone);
      } else {
        toUpdate.push(lead);
      }
    } else {
      toInsert.push(lead);
    }
  }

  let insertedCount = 0;
  let updatedCount = 0;

  if (toInsert.length > 0) {
    const rows = toInsert.map((l) => ({
      phone: l.phone,
      name: l.name || null,
      email: l.email || null,
      instagram: l.instagram || null,
      company: l.company || null,
      cnpj: l.cnpj || null,
      razao_social: l.razao_social || null,
      nome_fantasia: l.nome_fantasia || null,
      endereco: l.endereco || null,
      telefone_comercial: l.telefone_comercial || null,
      stage: l.stage || "secretaria",
      seller_stage: l.seller_stage || "novo",
      channel: "manual" as const,
      status: "active" as const,
    }));
    const { error } = await supabase.from("leads").insert(rows);
    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }
    insertedCount = rows.length;
  }

  for (const lead of toUpdate) {
    const updateData: Record<string, unknown> = {};
    if (lead.name) updateData.name = lead.name;
    if (lead.email) updateData.email = lead.email;
    if (lead.company) updateData.company = lead.company;
    if (lead.cnpj) updateData.cnpj = lead.cnpj;
    if (lead.razao_social) updateData.razao_social = lead.razao_social;
    if (lead.nome_fantasia) updateData.nome_fantasia = lead.nome_fantasia;
    if (lead.endereco) updateData.endereco = lead.endereco;
    if (lead.telefone_comercial) updateData.telefone_comercial = lead.telefone_comercial;

    if (Object.keys(updateData).length > 0) {
      await supabase.from("leads").update(updateData).eq("phone", lead.phone);
      updatedCount++;
    }
  }

  return NextResponse.json({
    inserted: insertedCount,
    updated: updatedCount,
    skipped: skipped.length,
  });
}

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { buildImportDeals, type ImportDealLead } from "@/lib/import-deals";

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
}

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { leads, skipDuplicates, pipelineId, stageId } = (await request.json()) as {
    leads: ImportLead[];
    skipDuplicates: boolean;
    pipelineId?: string;
    stageId?: string;
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

  let dealsCreated = 0;

  if (pipelineId) {
    // 1. Resolver e validar o stage (mesmo padrão de POST /api/deals):
    //    aceita o stage informado se pertencer ao funil e não for protegido;
    //    caso contrário, usa o primeiro stage não-protegido do funil.
    let resolvedStageId: string | null = null;

    if (stageId) {
      const { data: providedStage } = await supabase
        .from("pipeline_stages")
        .select("id")
        .eq("id", stageId)
        .eq("pipeline_id", pipelineId)
        .eq("is_protected", false)
        .maybeSingle();
      if (providedStage) resolvedStageId = providedStage.id;
    }

    if (!resolvedStageId) {
      const { data: firstStage, error: stageError } = await supabase
        .from("pipeline_stages")
        .select("id")
        .eq("pipeline_id", pipelineId)
        .eq("is_protected", false)
        .order("order_index", { ascending: true })
        .limit(1)
        .maybeSingle();
      if (stageError) console.error("[leads/import] stage fallback query failed:", stageError);
      resolvedStageId = firstStage?.id ?? null;
    }

    // 2. Nome do funil (para o título do card).
    const { data: pipeline } = await supabase
      .from("pipelines")
      .select("name")
      .eq("id", pipelineId)
      .maybeSingle();

    if (resolvedStageId && pipeline) {
      // 3. Buscar todos os leads importados (novos + duplicados existentes) por telefone.
      const { data: importedLeads } = await supabase
        .from("leads")
        .select("id, name, phone")
        .in("phone", phones);

      const leadList: ImportDealLead[] = (importedLeads ?? []).map((l) => ({
        id: l.id,
        name: l.name,
        phone: l.phone,
      }));

      if (leadList.length > 0) {
        // 4. Quais desses leads já têm deal nesse funil? (anti-duplicação)
        const leadIds = leadList.map((l) => l.id);
        const { data: existingDeals } = await supabase
          .from("deals")
          .select("lead_id")
          .eq("pipeline_id", pipelineId)
          .in("lead_id", leadIds);
        const existingDealLeadIds = new Set(
          (existingDeals ?? []).map((d: { lead_id: string }) => d.lead_id)
        );

        // 5. Montar e inserir os deals.
        const dealRows = buildImportDeals({
          leads: leadList,
          pipelineId,
          stageId: resolvedStageId,
          pipelineName: pipeline.name,
          existingDealLeadIds,
        });

        if (dealRows.length > 0) {
          const { error: dealError } = await supabase.from("deals").insert(dealRows);
          if (dealError) {
            return NextResponse.json({ error: dealError.message }, { status: 500 });
          }
          dealsCreated = dealRows.length;
        }
      }
    }
  }

  return NextResponse.json({
    inserted: insertedCount,
    updated: updatedCount,
    skipped: skipped.length,
    dealsCreated,
  });
}

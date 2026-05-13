import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const pipelineId = searchParams.get("pipeline_id");
  const stageId = searchParams.get("stage_id");
  const dealCategory = searchParams.get("deal_category");
  const noDeal = searchParams.get("no_deal") === "true";
  const createdAfter = searchParams.get("created_after");
  const createdBefore = searchParams.get("created_before");

  try {
    const supabase = await getServiceSupabase();

    if (pipelineId || stageId || dealCategory || noDeal) {
      if (noDeal) {
        const { data: leadsWithDeals } = await supabase
          .from("deals")
          .select("lead_id");
        const excludeIds = (leadsWithDeals ?? []).map((d: { lead_id: string }) => d.lead_id);

        let q = supabase
          .from("leads")
          .select("*, lead_tags(tag_id, tags(*))")
          .order("last_msg_at", { ascending: false, nullsFirst: false });

        if (excludeIds.length > 0) q = q.not("id", "in", `(${excludeIds.join(",")})`);
        if (createdAfter) q = q.gte("created_at", createdAfter);
        if (createdBefore) q = q.lte("created_at", createdBefore);

        const { data, error } = await q;
        if (error) {
          console.error("[leads] noDeal leads query failed:", error);
          return NextResponse.json({ error: `leads: ${error.message}` }, { status: 500 });
        }
        return NextResponse.json(data ?? []);
      }

      // Step 1: find which lead_ids are in the requested pipeline/stage/category
      let dealQuery = supabase
        .from("deals")
        .select("lead_id")
        .limit(5000);
      if (pipelineId) dealQuery = dealQuery.eq("pipeline_id", pipelineId);
      if (stageId) dealQuery = dealQuery.eq("stage_id", stageId);
      if (dealCategory) dealQuery = dealQuery.eq("category", dealCategory);

      const { data: matchingDeals, error: dealError } = await dealQuery;
      if (dealError) {
        console.error("[leads] deals filter query failed:", dealError);
        return NextResponse.json({ error: `deals: ${dealError.message}` }, { status: 500 });
      }

      const leadIds = [...new Set((matchingDeals ?? []).map((d: { lead_id: string }) => d.lead_id))];
      if (leadIds.length === 0) return NextResponse.json([]);

      // Step 2: fetch lead rows for those ids
      let q = supabase
        .from("leads")
        .select("*, lead_tags(tag_id, tags(*))")
        .in("id", leadIds)
        .order("last_msg_at", { ascending: false, nullsFirst: false });

      if (createdAfter) q = q.gte("created_at", createdAfter);
      if (createdBefore) q = q.lte("created_at", createdBefore);

      const { data, error } = await q;
      if (error) {
        console.error("[leads] leads.in() query failed:", error);
        return NextResponse.json({ error: `leads: ${error.message}` }, { status: 500 });
      }
      return NextResponse.json(data ?? []);
    }

    // No deal filter — plain leads query
    let q = supabase
      .from("leads")
      .select("*, lead_tags(tag_id, tags(*))")
      .order("last_msg_at", { ascending: false, nullsFirst: false });

    if (createdAfter) q = q.gte("created_at", createdAfter);
    if (createdBefore) q = q.lte("created_at", createdBefore);

    const { data, error } = await q;
    if (error) {
      console.error("[leads] plain leads query failed:", error);
      return NextResponse.json({ error: `leads: ${error.message}` }, { status: 500 });
    }
    return NextResponse.json(data ?? []);
  } catch (err) {
    console.error("[leads] unhandled exception:", err);
    return NextResponse.json(
      { error: `Erro interno: ${err instanceof Error ? err.message : String(err)}` },
      { status: 500 }
    );
  }
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

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

function sanitizePhone(raw: string | undefined | null): { digits: string; error?: string } {
  const digits = (raw ?? "").replace(/\D/g, "");
  if (digits.length < 8 || digits.length > 15) {
    return { digits, error: `Telefone inválido: ${digits.length} dígito(s) (esperado: 8–15)` };
  }
  return { digits };
}

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

      // Single query: fetch deals with embedded lead data (avoids large .in() URL)
      let dealQuery = supabase
        .from("deals")
        .select("leads(*, lead_tags(tag_id, tags(*)))");
      if (pipelineId) dealQuery = dealQuery.eq("pipeline_id", pipelineId);
      if (stageId) dealQuery = dealQuery.eq("stage_id", stageId);
      if (dealCategory) dealQuery = dealQuery.eq("category", dealCategory);

      const { data: dealRows, error: dealError } = await dealQuery;
      if (dealError) {
        console.error("[leads] deals+leads embedded query failed:", dealError);
        return NextResponse.json({ error: `deals: ${dealError.message}` }, { status: 500 });
      }

      // Deduplicate leads (a lead may have multiple deals in the same pipeline)
      const seen = new Set<string>();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let leads = (dealRows ?? []).map((d: any) => d.leads).filter((l: any) => {
        if (!l || seen.has(l.id)) return false;
        seen.add(l.id);
        return true;
      });

      if (leads.length === 0) return NextResponse.json([]);

      // Apply date filters client-side (they are on leads.created_at)
      if (createdAfter) leads = leads.filter((l: any) => l.created_at >= createdAfter);
      if (createdBefore) leads = leads.filter((l: any) => l.created_at <= createdBefore);

      return NextResponse.json(leads);
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

  const { digits: phoneDigits, error: phoneError } = sanitizePhone(body.phone);
  if (phoneError) {
    return NextResponse.json({ error: phoneError }, { status: 422 });
  }

  const { data: existing } = await supabase
    .from("leads")
    .select("id")
    .eq("phone", phoneDigits)
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
      phone: phoneDigits,
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

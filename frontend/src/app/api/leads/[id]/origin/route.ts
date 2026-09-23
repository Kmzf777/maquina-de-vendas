import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import {
  LEAD_ORIGIN_COLUMNS,
  describeLeadOrigin,
  resolveGoogleCampaignName,
  type LeadOriginInput,
} from "@/lib/lead-origin";

/**
 * Origem detalhada do lead (canal + campanha) para os painéis de /leads e
 * /conversas. Qualquer usuário autenticado — o vendedor usa /conversas.
 * O lookup da campanha é best-effort: se falhar, a origem sai sem o nome.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const sb = await getServiceSupabase();

  const { data, error } = await sb.from("leads").select(LEAD_ORIGIN_COLUMNS).eq("id", id).maybeSingle();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "not found" }, { status: 404 });
  const lead = data as unknown as LeadOriginInput;

  let campaignName: string | null = null;
  try {
    if (lead.meta_ad_id) {
      const { data: mac } = await sb
        .from("meta_ad_campaigns")
        .select("campaign_name")
        .eq("ad_id", lead.meta_ad_id)
        .maybeSingle();
      campaignName = (mac as { campaign_name?: string | null } | null)?.campaign_name ?? null;
    } else if (lead.gclid || lead.utm_campaign) {
      // ad_spend tem uma linha por campanha por dia e o PostgREST corta em
      // 1.000 linhas: do mais recente para trás, para as campanhas ativas
      // entrarem (a UTM do lead é last-touch). Sem casar, a UI mostra o slug.
      const { data: rows } = await sb
        .from("ad_spend")
        .select("campaign_name")
        .eq("platform", "google")
        .order("date", { ascending: false });
      const names = [
        ...new Set(((rows ?? []) as { campaign_name: string | null }[]).map((r) => r.campaign_name ?? "").filter(Boolean)),
      ];
      campaignName = resolveGoogleCampaignName(lead.utm_campaign, lead.utm_medium, names);
    }
  } catch {
    campaignName = null;
  }

  return NextResponse.json(describeLeadOrigin(lead, campaignName));
}

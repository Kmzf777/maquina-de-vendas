import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { buildPreviewArgs, faltaEtapa, PREVIEW_LIMIT } from "@/lib/esteiras-preview";

/**
 * POST /api/automation/esteiras/preview
 *
 * Quantos cards ficam elegíveis se esta esteira for ligada AGORA, com a configuração que
 * está na tela (salva ou não). É o anteparo da §5.1 da spec: `entered_stage_at` nasce com
 * a data da última movimentação de cada card, então ligar a reposição num banco com meses
 * de histórico torna elegível, de uma vez, todo card parado há mais de 15 dias.
 *
 * Roda a MESMA RPC do gatilho em vez de uma consulta paralela — número aproximado seria
 * pior que número nenhum, porque induziria a ligar achando que o volume é outro.
 *
 * Nunca é um erro fatal: qualquer falha vira `elegiveis: null` com um motivo, e a tela
 * pede confirmação assim mesmo. A migration pode não ter sido aplicada ainda (este repo
 * não roda migration no deploy) e isso não pode travar a configuração da esteira.
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (!body?.campaign_id) {
    return NextResponse.json({ elegiveis: null, motivo: "sem_campanha" });
  }

  const supabase = await getServiceSupabase();

  const { data: campanha } = await supabase
    .from("campaigns")
    .select("id, audience")
    .eq("id", body.campaign_id)
    .maybeSingle();

  const { data: nos } = await supabase
    .from("campaign_nodes")
    .select("id, type, config")
    .eq("campaign_id", body.campaign_id)
    .eq("type", "trigger")
    .limit(1);

  const gatilho = (nos?.[0]?.config ?? null) as Record<string, unknown> | null;
  if (!gatilho) {
    return NextResponse.json({ elegiveis: null, motivo: "sem_gatilho" });
  }

  const args = buildPreviewArgs(
    gatilho,
    {
      canal_id: body.canal_id ?? null,
      funil_id: body.funil_id ?? null,
      etapa_id: body.etapa_id ?? null,
      dias: body.dias ?? null,
    },
    (campanha?.audience as string | undefined) ?? null
  );

  if (faltaEtapa(args)) {
    return NextResponse.json({ elegiveis: null, motivo: "sem_etapa" });
  }

  const { data, error } = await supabase.rpc("get_deals_stage_stagnant", args);
  if (error) {
    // Causa mais provável: 20260904_esteiras_vendedor.sql ainda não foi executada.
    return NextResponse.json({ elegiveis: null, motivo: "rpc_indisponivel" });
  }

  const total = Array.isArray(data) ? data.length : 0;
  return NextResponse.json({ elegiveis: total, truncado: total >= PREVIEW_LIMIT });
}

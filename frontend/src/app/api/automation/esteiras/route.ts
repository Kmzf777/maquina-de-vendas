import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

const FASTAPI_URL =
  process.env.NEXT_PUBLIC_FASTAPI_URL ||
  process.env.FASTAPI_URL ||
  "http://api:8000";

/**
 * GET /api/automation/esteiras
 *
 * Encaminha para o FastAPI (`app/campaigns/esteiras_router.py`), que devolve as quatro
 * esteiras em formato achatado. A rota é um proxy e NÃO reimplementa a tradução do grafo.
 *
 * Acrescenta dois campos que o contrato do backend não traz e a tela precisa:
 *
 * - `campaign_id`, para o link "abrir no builder". O id é `uuid5(namespace, env_tag, key)`
 *   — determinístico, mas o env_tag mora no backend, e recalculá-lo aqui duplicaria uma
 *   decisão que não é nossa. Resolvemos por (name, env_tag), que é único.
 * - `gatilho`, a config do nó de gatilho. É o que permite a tela DIZER o que a esteira
 *   faz ("15 dias sem conversa, não importa quem falou por último") em vez de mostrar um
 *   número solto. Sem isso a tela vira o builder de novo: correta e ilegível.
 *
 * Sem correspondência (seed não rodou, campanha renomeada no builder) os dois campos ficam
 * null e a tela degrada — esconde o link e omite a explicação. Nunca aponta para a
 * campanha errada.
 */
export async function GET() {
  let upstream: Response;
  try {
    upstream = await fetch(`${FASTAPI_URL}/api/automation/esteiras`, {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Backend indisponível" }, { status: 502 });
  }

  const payload = await upstream.json().catch(() => null);
  if (!upstream.ok || !payload || !Array.isArray(payload.esteiras)) {
    return NextResponse.json(payload ?? { error: "Resposta inválida do backend" }, {
      status: upstream.ok ? 502 : upstream.status,
    });
  }

  const esteiras = payload.esteiras as Array<Record<string, unknown>>;
  const nomes = esteiras.map((e) => String(e.nome ?? "")).filter(Boolean);

  const porNome = new Map<string, string>();
  const gatilhoPorCampanha = new Map<string, unknown>();
  if (nomes.length > 0) {
    try {
      const supabase = await getServiceSupabase();
      const { data: campanhas } = await supabase
        .from("campaigns")
        .select("id, name")
        .eq("env_tag", APP_ENV)
        .in("name", nomes);
      for (const c of campanhas ?? []) porNome.set(c.name as string, c.id as string);

      const ids = [...porNome.values()];
      if (ids.length > 0) {
        const { data: nos } = await supabase
          .from("campaign_nodes")
          .select("campaign_id, type, config")
          .in("campaign_id", ids)
          .eq("type", "trigger");
        for (const n of nos ?? []) gatilhoPorCampanha.set(n.campaign_id as string, n.config);
      }
    } catch {
      // Enriquecimento é opcional: falhar aqui não pode derrubar a listagem.
    }
  }

  return NextResponse.json({
    esteiras: esteiras.map((e) => {
      const campaignId = (e.campaign_id as string | null) ?? porNome.get(String(e.nome ?? "")) ?? null;
      return {
        ...e,
        campaign_id: campaignId,
        gatilho: e.gatilho ?? (campaignId ? gatilhoPorCampanha.get(campaignId) ?? null : null),
      };
    }),
  });
}

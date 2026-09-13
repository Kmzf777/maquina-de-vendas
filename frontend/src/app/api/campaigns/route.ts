import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET() {
  const supabase = await getServiceSupabase();
  // campaign_nodes(count) = agregado do PostgREST (COUNT + GROUP BY numa única
  // query, sem N+1) — o card da listagem mostrava "0 nós" porque a rota não trazia
  // contagem nenhuma e o front caía no fallback.
  const { data, error } = await supabase
    .from("campaigns")
    .select("*, campaign_nodes(count)")
    .eq("env_tag", APP_ENV)
    .order("created_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  const rows = (data ?? []).map((c) => {
    const { campaign_nodes, ...campaign } = c as { campaign_nodes?: { count: number }[] } & Record<string, unknown>;
    return { ...campaign, nodes_count: campaign_nodes?.[0]?.count ?? 0 };
  });
  return NextResponse.json({ data: rows });
}

// campaigns.audience ('ia' | 'humano' | 'ambos', default 'ia' no banco) escolhe quem a
// cadência alcança. Sem validar contra lista fechada, um valor solto no body vazaria
// pro banco; sem o fallback "ia", o builder poderia criar campanha invisível para
// TODOS os leads (nem ia, nem humano) por um typo. "ia" é o comportamento histórico,
// nunca o mais permissivo.
const AUDIENCIAS = ["ia", "humano", "ambos"];

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .insert({
      name: body.name,
      description: body.description ?? null,
      status: "draft",
      channel_id: body.channel_id ?? null,
      priority: body.priority ?? null,
      frequency_cap: body.frequency_cap ?? null,
      audience: AUDIENCIAS.includes(body.audience) ? body.audience : "ia",
      env_tag: APP_ENV,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

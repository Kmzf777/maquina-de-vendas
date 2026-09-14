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

// Janela de disparo (send_start_hour/send_end_hour, colunas NOT NULL DEFAULT 7/18 no
// banco) + skip_weekends (NOT NULL DEFAULT false). Hora precisa ser inteiro 0-23 —
// mandar `null` pra uma coluna NOT NULL vira erro 500 do Postgres em vez de um 400
// legível, então campo ausente/writeInvalid é omitido do insert (DB aplica o
// default) e só um valor presente e fora do intervalo vira 400.
function isValidHour(v: unknown): v is number {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 23;
}

export async function POST(request: NextRequest) {
  const body = await request.json();

  const hasStart = body.send_start_hour !== undefined;
  const hasEnd = body.send_end_hour !== undefined;
  if (hasStart && !isValidHour(body.send_start_hour)) {
    return NextResponse.json({ error: "send_start_hour inválido — use um inteiro entre 0 e 23" }, { status: 400 });
  }
  if (hasEnd && !isValidHour(body.send_end_hour)) {
    return NextResponse.json({ error: "send_end_hour inválido — use um inteiro entre 0 e 23" }, { status: 400 });
  }
  // Janela invertida (ex.: 12 às 8) é erro do chamador, não do servidor.
  if (hasStart && hasEnd && body.send_start_hour >= body.send_end_hour) {
    return NextResponse.json({ error: "janela invertida — send_start_hour deve ser menor que send_end_hour" }, { status: 400 });
  }
  if (body.skip_weekends !== undefined && typeof body.skip_weekends !== "boolean") {
    return NextResponse.json({ error: "skip_weekends inválido — use true ou false" }, { status: 400 });
  }

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
      ...(hasStart ? { send_start_hour: body.send_start_hour } : {}),
      ...(hasEnd ? { send_end_hour: body.send_end_hour } : {}),
      ...(body.skip_weekends !== undefined ? { skip_weekends: body.skip_weekends } : {}),
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { resolverEscopoDeVendas } from "@/lib/sales/sales-scope-route";
import { vendedorDaRecompra } from "@/lib/sales/sales-scope";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const soldBy = searchParams.get("sold_by");
  const supabase = await getServiceSupabase();

  const escopoRes = await resolverEscopoDeVendas();
  if (!escopoRes.ok) return escopoRes.resposta;
  const escopo = escopoRes.escopo;

  let periodQuery = supabase.from("sales").select("value");
  if (from) periodQuery = periodQuery.gte("sold_at", from.length === 10 ? `${from}T00:00:00.000Z` : from);
  if (to) periodQuery = periodQuery.lte("sold_at", to.length === 10 ? `${to}T23:59:59.999Z` : to);
  // O filtro de vendedor da barra precisa mover os cards, nao so a lista — era
  // a queixa: escolher "joao" mudava a tabela e deixava os quatro numeros
  // falando da operacao inteira.
  if (soldBy) periodQuery = periodQuery.eq("sold_by", soldBy);
  if (escopo) periodQuery = periodQuery.or(escopo);

  const { data: periodSales, error } = await periodQuery;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const total_value = periodSales.reduce((sum, s) => sum + Number(s.value), 0);
  const count = periodSales.length;
  const avg_value = count > 0 ? total_value / count : 0;

  // Recompra agregada no banco via RPC (não carrega a tabela inteira no Node).
  // O vendedor NÃO vem cru da URL: a RPC não passa pelo filtro `or` do escopo,
  // então aceitar o parâmetro como veio deixaria um vendedor ler o ciclo de
  // outro. `vendedorDaRecompra` decide — e o período fica de fora de propósito
  // (ver o comentário da migration 20260824_repurchase_por_vendedor.sql).
  const { data: rpcValue } = await supabase.rpc("get_avg_repurchase_cycle_days", {
    p_sold_by: vendedorDaRecompra(escopoRes.user, soldBy),
  });
  const avg_repurchase_cycle_days: number | null = rpcValue == null ? null : Number(rpcValue);

  return NextResponse.json({ total_value, count, avg_value, avg_repurchase_cycle_days });
}

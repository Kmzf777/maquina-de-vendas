import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { resolverEscopoDeVendas } from "@/lib/sales/sales-scope-route";
import { vendedorDaRecompra } from "@/lib/sales/sales-scope";
import { freteDaVenda, limitesDoDiaBRT, padraoVendedor, receitaDaVenda, vendaCancelada } from "@/lib/sales/receita";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const from = searchParams.get("from");
  const to = searchParams.get("to");
  const soldBy = searchParams.get("sold_by");
  const supabase = await getServiceSupabase();

  const escopoRes = await resolverEscopoDeVendas();
  if (!escopoRes.ok) return escopoRes.resposta;
  const escopo = escopoRes.escopo;

  const { gte, lte } = limitesDoDiaBRT(from, to);
  // Vendedor comparado sem diferenciar caixa, sem deixar curinga virar padrao.
  const vendedor = soldBy ? padraoVendedor(soldBy) : null;

  // D7 (1e6381fe): pagina de 1.000 em 1.000 (o PostgREST corta em 1.000 linhas
  // e o card mostrava so parte do periodo) e deixa a cancelada de fora ja no
  // banco. `status` nulo conta como valida, por isso o `or`. O escopo e outro
  // `.or`: o supabase-js manda dois parametros `or=` e o PostgREST os combina
  // com AND, entao o escopo continua so restringindo.
  const PAGINA = 1000;
  const periodSales: { value: number | string | null; freight: number | string | null; status: string | null }[] = [];
  for (let i = 0; ; i += PAGINA) {
    let periodQuery = supabase
      .from("sales")
      .select("value, freight, status")
      .or("status.is.null,status.neq.cancelada");
    if (gte) periodQuery = periodQuery.gte("sold_at", gte);
    if (lte) periodQuery = periodQuery.lte("sold_at", lte);
    // O filtro de vendedor da barra precisa mover os cards, nao so a lista — era
    // a queixa: escolher "joao" mudava a tabela e deixava os quatro numeros
    // falando da operacao inteira.
    if (soldBy) {
      periodQuery = vendedor === null
        ? periodQuery.eq("sold_by", soldBy)
        : periodQuery.ilike("sold_by", vendedor);
    }
    if (escopo) periodQuery = periodQuery.or(escopo);

    const { data, error } = await periodQuery.order("id").range(i, i + PAGINA - 1);
    if (error) return NextResponse.json({ error: error.message }, { status: 500 });
    periodSales.push(...(data ?? []));
    if (!data || data.length < PAGINA) break;
  }

  // O filtro do banco so pega "cancelada" exata; os helpers pegam qualquer
  // variacao ("Cancelado", " cancelada ").
  const validas = periodSales.filter((s) => !vendaCancelada(s));
  const total_value = Math.round(validas.reduce((sum, s) => sum + receitaDaVenda(s), 0) * 100) / 100;
  const freight_value = Math.round(validas.reduce((sum, s) => sum + freteDaVenda(s), 0) * 100) / 100;
  const count = validas.length;
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

  return NextResponse.json({ total_value, freight_value, count, avg_value, avg_repurchase_cycle_days });
}

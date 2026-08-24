import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { resolverEscopoDeVendas } from "@/lib/sales/sales-scope-route";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const escopoRes = await resolverEscopoDeVendas();
  if (!escopoRes.ok) return escopoRes.resposta;
  const escopo = escopoRes.escopo;

  let query = supabase
    .from("sales")
    // sale_items embutido pelo mesmo motivo do /api/sales: esta lista alimenta
    // o "editar venda" do painel de contato (contact-detail.tsx via
    // useLeadSales). Os campos do Bling entram aqui porque o modal decide por
    // eles: sem `bling_order_id` o gate `blingEditable` nunca enxerga pedido no
    // ERP a partir desta tela, e editar cairia no PATCH local — o CRM mudaria e
    // o Bling não, em silêncio. Divergência silenciosa é justamente o que a
    // integração existe para evitar.
    .select(
      "id, sold_at, value, product, sold_by, deal_id, notes, " +
        "bling_order_id, bling_order_number, bling_situacao_id, bling_situacao_nome, " +
        "origin, status, bling_divergent, bling_divergence, " +
        "deals(id, title), sale_items(*)"
    )
    .eq("lead_id", id)
    .order("sold_at", { ascending: false })
    .order("ordem", { foreignTable: "sale_items", ascending: true });

  if (escopo) query = query.or(escopo);

  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}

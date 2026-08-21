import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("sales")
    // sale_items embutido pelo mesmo motivo do /api/sales: esta lista alimenta
    // o "editar venda" do painel de contato (contact-detail.tsx via
    // useLeadSales). Nota: esta rota ainda não seleciona `bling_order_id`, então
    // o gate `blingEditable` do modal nunca vê pedido no Bling a partir daqui —
    // a edição cai no PATCH local, não no PUT que consome estes itens. Ficam
    // aqui mesmo assim para não deixar a rota inconsistente com as demais.
    .select(
      "id, sold_at, value, product, sold_by, deal_id, notes, deals(id, title), sale_items(*)"
    )
    .eq("lead_id", id)
    .order("sold_at", { ascending: false })
    .order("ordem", { foreignTable: "sale_items", ascending: true });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}

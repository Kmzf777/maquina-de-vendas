import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET() {
  const supabase = await getServiceSupabase();

  const { data: leads, error } = await supabase
    .from("leads")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const headers = [
    "nome", "telefone", "email", "instagram", "empresa", "cnpj",
    "razao_social", "nome_fantasia", "endereco", "telefone_comercial",
    "stage", "seller_stage", "canal", "valor_venda", "criado_em",
  ];

  const rows = (leads || []).map((l) => [
    l.name || "",
    l.phone,
    l.email || "",
    l.instagram || "",
    l.company || "",
    l.cnpj || "",
    l.razao_social || "",
    l.nome_fantasia || "",
    l.endereco || "",
    l.telefone_comercial || "",
    l.stage,
    l.seller_stage,
    l.channel,
    l.sale_value || 0,
    l.created_at,
  ]);

  const csvContent = [
    headers.join(","),
    ...rows.map((r) =>
      r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")
    ),
  ].join("\n");

  return new NextResponse(csvContent, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="leads-${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  });
}

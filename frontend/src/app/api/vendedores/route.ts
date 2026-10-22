import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

/**
 * Cadastro único de vendedores (cartão b67f1c6b). Alimenta as listas de seleção
 * de vendedor (deal, lead) e o nome mostrado no card a partir do id.
 * `?ativos=1` devolve só os ativos; sem o parâmetro, todos (inativos resolvem histórico).
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const supabase = await getServiceSupabase();
  let query = supabase.from("vendedores").select("id, nome, email, ativo").order("nome");
  if (searchParams.get("ativos") === "1") query = query.eq("ativo", true);
  const { data, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}

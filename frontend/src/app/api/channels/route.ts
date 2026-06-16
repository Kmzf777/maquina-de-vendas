import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";

export async function GET() {
  const supabase = await getServiceSupabase();

  // Mesma restrição de ownership aplicada em /api/conversations: o seletor de
  // canal NÃO pode oferecer canais que o vendedor não possui — selecioná-los
  // retornaria lista vazia e quebraria a tela. Admin (null) vê todos.
  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  // Vendedor sem nenhum canal próprio: vazio legítimo.
  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    return NextResponse.json([]);
  }

  let query = supabase
    .from("channels")
    .select("*, agent_profiles(id, name)")
    .order("created_at", { ascending: false });

  if (allowedChannelIds !== null) {
    query = query.in("id", allowedChannelIds);
  }

  const { data, error } = await query;

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("channels")
    .insert(body)
    .select("*, agent_profiles(id, name)")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data, { status: 201 });
}

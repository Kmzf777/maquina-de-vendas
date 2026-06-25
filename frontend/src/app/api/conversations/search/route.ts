import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { resolveSearchChannelScope } from "@/lib/message-search";

const MIN_QUERY_LEN = 2;
const MAX_RESULTS = 50;

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const q = (searchParams.get("q") || "").trim();
  const channelId = searchParams.get("channel_id");

  // Query curta: nada a buscar (não chama o RPC).
  if (q.length < MIN_QUERY_LEN) {
    return NextResponse.json([]);
  }

  // Escopo de canais do usuário. Falha de auth => 401 (nunca [] silencioso).
  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  const scope = resolveSearchChannelScope(allowedChannelIds, channelId);
  if (scope.kind === "empty") {
    return NextResponse.json([]);
  }

  const { data, error } = await supabase.rpc("search_customer_messages", {
    search_query: q,
    channel_ids: scope.kind === "all" ? null : scope.ids,
    max_results: MAX_RESULTS,
  });

  // Erro do RPC: 500 (a UI mantém o estado anterior; nunca [] silencioso em erro).
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data ?? []);
}

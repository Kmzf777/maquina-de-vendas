import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { resolveSearchChannelScope } from "@/lib/message-search";
import type { ConversationCounts } from "../list-params";

/**
 * Contadores da tela de conversas, contados NO BANCO.
 *
 * A lista agora é paginada (200 por página) e, antes disso, era cortada em 1.000
 * linhas pelo PostgREST: contar `unread_count > 0` sobre o que estava carregado
 * mentia. `count=exact` com `head=true` não devolve linhas, então não sofre o teto.
 * Mesmo escopo da listagem: canais do usuário, canal escolhido, sem bloqueadas.
 */
export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const channelId = new URL(request.url).searchParams.get("channel_id");

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
    return NextResponse.json({ total: 0, unread: 0 } satisfies ConversationCounts);
  }

  const base = () => {
    let q = supabase
      .from("conversations")
      .select("id", { count: "exact", head: true })
      .neq("status", "blocked");
    if (scope.kind === "ids") q = q.in("channel_id", scope.ids);
    return q;
  };

  const [total, unread] = await Promise.all([base(), base().gt("unread_count", 0)]);
  const error = total.error ?? unread.error;
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    total: total.count ?? 0,
    unread: unread.count ?? 0,
  } satisfies ConversationCounts);
}

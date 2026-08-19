import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { resolveSearchChannelScope } from "@/lib/message-search";
import { buildLeadSearchOrFilter } from "@/lib/search";
import {
  conversationSelect,
  enrichConversations,
  type EnrichableConversation,
} from "@/lib/supabase/conversation-enrichment";
import { CONTACT_SEARCH_MIN_LEN } from "@/lib/contact-search";

/** Teto de resultados. Alto o bastante para homônimos, baixo para caber na lista. */
const MAX_RESULTS = 30;

/**
 * Busca de CONTATOS no servidor.
 *
 * A lista de `/api/conversations` não pagina e o PostgREST corta em 1.000 linhas:
 * com 3.4k conversas, filtrar no cliente só enxergava as mais recentes e jurava
 * "Nenhum contato encontrado" para todo o resto. Aqui o filtro roda no banco,
 * sobre a base inteira, sempre dentro do escopo de canais do usuário.
 */
export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const q = (searchParams.get("q") || "").trim();
  const channelId = searchParams.get("channel_id");

  if (q.length < CONTACT_SEARCH_MIN_LEN) {
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

  // Query só de pontuação/acentos não tem o que casar — evita ida ao banco.
  const orFilter = buildLeadSearchOrFilter(q);
  if (!orFilter) {
    return NextResponse.json([]);
  }

  // INNER JOIN em leads: com o LEFT padrão o filtro esvaziaria o lead embutido
  // sem descartar a conversa, devolvendo a base inteira sem nome.
  let dbQuery = supabase
    .from("conversations")
    .select(conversationSelect({ innerLead: true }))
    .or(orFilter, { referencedTable: "leads" })
    .order("last_msg_at", { ascending: false, nullsFirst: false })
    .limit(MAX_RESULTS);

  if (scope.kind === "ids") {
    dbQuery = dbQuery.in("channel_id", scope.ids);
  }

  const { data, error } = await dbQuery;
  // Erro de query: 500 (a UI mantém o estado anterior; nunca [] silencioso em erro).
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const enriched = await enrichConversations(
    supabase,
    (data ?? []) as unknown as EnrichableConversation[],
  );

  return NextResponse.json(enriched);
}

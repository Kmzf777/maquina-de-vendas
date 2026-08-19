import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import {
  conversationSelect,
  enrichConversations,
  type EnrichableConversation,
} from "@/lib/supabase/conversation-enrichment";

/**
 * Busca UMA conversa pelo id, com os mesmos joins da listagem.
 *
 * Existe para abrir conversa que não está na lista carregada — resultado da
 * busca de mensagens ou deep-link apontando para uma conversa antiga, fora do
 * teto de 1.000 linhas do PostgREST. Antes disso o clique era um no-op mudo.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Escopo de canais do usuário. Falha de auth => 401 (nunca 404 silencioso).
  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  const { data, error } = await supabase
    .from("conversations")
    .select(conversationSelect())
    .eq("id", id)
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  if (!data) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  // Vendedor não abre conversa de canal alheio, nem por link direto.
  const channelId = (data as { channel_id?: string }).channel_id;
  if (allowedChannelIds !== null && (!channelId || !allowedChannelIds.includes(channelId))) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const [enriched] = await enrichConversations(supabase, [
    data as unknown as EnrichableConversation,
  ]);

  return NextResponse.json(enriched);
}

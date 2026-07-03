import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";

/**
 * Expõe ao client a restrição de canais do usuário logado, preservando a
 * semântica de {@link getAllowedChannelIds}:
 *
 * - `{ channel_ids: null }`     => admin, sem restrição.
 * - `{ channel_ids: string[] }` => vendedor, restrito a esses canais.
 *
 * Usado pelo hook de notificações para filtrar eventos Realtime no browser
 * (o Realtime não passa pelas rotas de API, então o escopo precisa ser
 * aplicado no client até o RLS ser habilitado).
 */
export async function GET() {
  const supabase = await getServiceSupabase();
  try {
    const channelIds = await getAllowedChannelIds(supabase);
    return NextResponse.json({ channel_ids: channelIds });
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }
}
